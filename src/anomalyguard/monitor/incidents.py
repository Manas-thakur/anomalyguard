"""Incidents: the findings of one run grouped into a few things a person can act on.

A run can store thousands of findings. People triage *incidents* instead: every
finding of a run is grouped by ``(source, column, kind)`` where ``kind`` says what
went wrong in plain language (values higher than expected, a level shift, missing
values, duplicate rows, ...). Each incident carries:

* a status tag and a one-sentence explanation,
* the expected range (a robust ``median +- 3.5 * 1.4826 * MAD`` band for a column,
  or trend + seasonality +- the same band for a time series) and the actual worst
  value, with the relative difference,
* chart data (``chart()``): a distribution with the band shaded and the flagged
  values marked, a time series with an expected band, or a run-history series.

Incidents are computed from the stored findings plus the run's data (the
uploaded dataset of an analysis, or the source file of a pipeline run if it is
still on disk) and cached per run. Triage state (``normal`` / ``confirmed``) and
mutes are stored separately, so they apply on top of the cached summaries.
"""

from __future__ import annotations

import hashlib
import math
import re
import threading
from collections import Counter, OrderedDict
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from anomalyguard.monitor.store import ANALYSIS_PREFIX, MetricsStore, severity
from anomalyguard.schema.coercion import _clean_numeric_strings

VERSION = 6
BAND_K = 3.5  # same cut-off as the MAD detector, in robust standard deviations
MAD_SCALE = 1.4826
TIMESERIES = {"rolling_zscore", "ewma", "seasonal", "cusum"}
SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}
MAX_FINDINGS = 5000
MAX_POINTS = 1500
MAX_MARKS = 300
TRIAGE_STATUSES = {"normal", "confirmed"}

TAGS = {
    ("outlier", "higher"): "Values higher than expected",
    ("outlier", "lower"): "Values lower than expected",
    ("outlier", "both"): "Values outside the expected range",
    ("pattern", "higher"): "Values higher than expected",
    ("pattern", "lower"): "Values lower than expected",
    ("pattern", "both"): "Values off the usual pattern",
    ("level_shift", None): "Level shift detected",
    ("multivariate", None): "Unusual combinations of values",
    ("missing", "higher"): "Missing values spiked",
    ("missing", None): "Missing values",
    ("duplicates", None): "Duplicate rows",
    ("invalid", None): "Values break the schema",
}


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------
def base_detector(name: str) -> str:
    """``grouped(mad by region)`` -> ``mad``; ``ensemble[vote](...)`` -> ``ensemble``."""
    m = re.match(r"^grouped\(([\w-]+) by ", name or "")
    if m:
        return m.group(1)
    return re.split(r"[(\[]", name or "")[0]


def group_of(name: str) -> str | None:
    m = re.match(r"^grouped\([\w-]+ by ([^)]+)\)$", name or "")
    return m.group(1) if m else None


def finding_kind(detector: str, column: str | None) -> str:
    if column is None:
        return "multivariate"
    base = base_detector(detector)
    if base == "cusum":
        return "level_shift"
    if base in TIMESERIES:
        return "pattern"
    return "outlier"


def incident_id(column: str | None, kind: str) -> str:
    return hashlib.sha1(f"{column or ''}\x00{kind}".encode()).hexdigest()[:12]


def source_name(pipeline: str) -> str:
    """Display name of a run's source: the pipeline, or the analysed file's stem."""
    if pipeline.startswith(ANALYSIS_PREFIX):
        return Path(pipeline[len(ANALYSIS_PREFIX) :]).name.split(".")[0] or pipeline
    return pipeline


def fmt(v: Any) -> str:
    if v is None:
        return "-"
    if isinstance(v, float) and not math.isfinite(v):
        return str(v)
    if isinstance(v, (int, np.integer)) and not isinstance(v, bool):
        return f"{int(v):,}"
    if isinstance(v, (float, np.floating)):
        a = abs(float(v))
        if a >= 100:
            return f"{math.floor(float(v) + 0.5):,}"
        if a >= 10:
            return f"{float(v):.4g}"
        if a >= 1 or a == 0:
            return f"{float(v):.3g}"
        return f"{float(v):.3g}"
    return str(v)


def _num(v: Any) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float, np.integer, np.floating)):
        f = float(v)
        return f if math.isfinite(f) else None
    s = pd.to_numeric(_clean_numeric_strings(pd.Series([v], dtype=object)), errors="coerce")
    f = s.iloc[0]
    return float(f) if pd.notna(f) and math.isfinite(float(f)) else None


def numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(_clean_numeric_strings(series), errors="coerce").astype(float)


def _pct(part: float, whole: float) -> str:
    return f"{part / whole:.1%}" if whole else "-"


def _delta(actual: float | None, lo: float | None, hi: float | None) -> float | None:
    """Relative distance of ``actual`` beyond the nearest band edge (0 inside the band)."""
    if actual is None or lo is None or hi is None:
        return None
    if lo <= actual <= hi:
        return 0.0
    edge = hi if actual > hi else lo
    if edge == 0:
        return None
    return round((actual - edge) / abs(edge), 4)


def robust_band(values: pd.Series) -> dict[str, float] | None:
    vals = values.dropna()
    if vals.empty:
        return None
    med = float(vals.median())
    mad = float((vals - med).abs().median()) * MAD_SCALE
    if mad == 0:
        q1, q3 = (float(x) for x in vals.quantile([0.25, 0.75]))
        mad = (q3 - q1) / 1.349 or float(vals.std() or 0.0)
    lo, hi = med - BAND_K * mad, med + BAND_K * mad
    # never extend the band past what the data can be (e.g. negative quantities)
    lo, hi = max(lo, float(vals.min())), min(hi, float(vals.max()))
    return {"center": med, "low": min(lo, med), "high": max(hi, med), "scale": mad}


def guess_period(times: pd.Series) -> int | None:
    t = pd.to_datetime(times, errors="coerce", format="mixed").dropna().sort_values()
    if len(t) < 3:
        return None
    step = float(t.diff().dt.total_seconds().median() or 0)
    for seconds, period in ((900, 96), (1800, 48), (3600, 24), (86400, 7)):
        if abs(step - seconds) <= seconds * 0.1:
            return period
    return None


def guess_time_column(df: pd.DataFrame) -> str | None:
    for c in df.columns:
        name = str(c).lower()
        timeish = name in ("ts", "time", "date", "datetime", "timestamp") or any(
            name.endswith(k) or name.startswith(k) for k in ("time", "date", "_at", "_ts")
        )
        if not timeish:
            continue
        if pd.api.types.is_datetime64_any_dtype(df[c]):
            return str(c)
        if df[c].dtype == object:
            parsed = pd.to_datetime(df[c].head(200), errors="coerce", format="mixed")
            if parsed.notna().mean() >= 0.9:
                return str(c)
    return None


def series_band(
    y: np.ndarray, period: int | None, kind: str, flagged: list[int]
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Expected value and band per point of a time-ordered series."""
    from anomalyguard.detect.timeseries import seasonal_decompose

    s = pd.Series(y, dtype=float)
    filled = s.interpolate(limit_direction="both").to_numpy()
    if np.isnan(filled).all():
        nan = np.full(len(y), np.nan)
        return nan, nan, nan
    if period and len(filled) >= 2 * period:
        trend, seasonal, _ = seasonal_decompose(filled, period)
    else:
        trend = s.rolling(7, center=True, min_periods=1).median().to_numpy()
        seasonal = np.zeros(len(filled))
    expected = trend + seasonal
    resid = filled - expected
    if kind == "level_shift" and flagged:
        first = min(flagged)
        pre = slice(0, first) if first >= max(period or 0, 10) else slice(0, len(filled))
        level = float(np.nanmedian((filled - seasonal)[pre]))
        expected = level + seasonal
        resid = (filled - trend - seasonal)[pre]
    resid = resid[np.isfinite(resid)]
    scale = float(np.median(np.abs(resid - np.median(resid)))) * MAD_SCALE if len(resid) else 0.0
    if scale == 0:
        scale = float(np.std(resid)) if len(resid) else 0.0
    return expected, expected - BAND_K * scale, expected + BAND_K * scale


# ----------------------------------------------------------------------
class IncidentEngine:
    """Builds, caches and triages incidents for runs in a metrics store.

    ``load_frame(run)`` returns ``(DataFrame | None, time_column | None)`` for a
    run; the server supplies it (analyses read the uploaded dataset, pipeline runs
    their source file when it is inside an allowed folder).
    """

    def __init__(
        self,
        store: MetricsStore,
        load_frame: Callable[[dict[str, Any]], tuple[pd.DataFrame | None, str | None]],
    ):
        self.store = store
        self.load_frame = load_frame
        self._frames: OrderedDict[int, tuple[pd.DataFrame | None, str | None]] = OrderedDict()
        self._lock = threading.Lock()

    # -- data -------------------------------------------------------------
    def _frame(self, run: dict[str, Any]) -> tuple[pd.DataFrame | None, str | None]:
        rid = int(run["id"])
        with self._lock:
            if rid in self._frames:
                self._frames.move_to_end(rid)
                return self._frames[rid]
        try:
            df, tcol = self.load_frame(run)
        except Exception:  # missing or unreadable source: incidents without bands
            df, tcol = None, None
        if df is not None and tcol is None:
            tcol = guess_time_column(df)
        with self._lock:
            self._frames[rid] = (df, tcol)
            while len(self._frames) > 6:
                self._frames.popitem(last=False)
        return df, tcol

    # -- summaries --------------------------------------------------------
    def summaries(self, run_id: int) -> list[dict[str, Any]]:
        """Incident summaries for a run (cached once the run has finished)."""
        cached = self.store.cached_incidents(run_id, VERSION)
        if cached is not None:
            return cached
        run = self.store.get_run(run_id)
        if run is None:
            raise KeyError(f"Run {run_id} not found")
        incidents = self._build(run)
        if run["status"] not in ("running",):
            self.store.cache_incidents(run_id, VERSION, incidents)
        return incidents

    def _build(self, run: dict[str, Any]) -> list[dict[str, Any]]:
        m = run.get("metrics") or {}
        rid = int(run["id"])
        source = source_name(run["pipeline"])
        common = {"run_id": rid, "pipeline": run["pipeline"], "started_at": run["started_at"]}
        out: list[dict[str, Any]] = []

        groups: dict[tuple[str | None, str], list[dict[str, Any]]] = {}
        for g in self.store.anomaly_groups(rid):
            groups.setdefault((g["column"], finding_kind(g["detector"], g["column"])), []).append(g)
        df, tcol = self._frame(run) if groups else (None, None)
        for (column, kind), parts in groups.items():
            inc = self._detector_incident(run, df, tcol, column, kind, parts)
            out.append({**common, **inc, "entity": f"{source}.{column}" if column else source})

        rows = int(run.get("rows") or m.get("rows") or 0)
        prev = self.store.previous_run(run["pipeline"], rid) if rid else None
        pm = (prev or {}).get("metrics") or {}
        nulls = m.get("null_counts") or {}
        for column, n in sorted(nulls.items(), key=lambda kv: -int(kv[1] or 0)):
            n = int(n or 0)
            if n <= 0:
                continue
            before = (pm.get("null_counts") or {}).get(column)
            expected = int(before) if before is not None else 0
            rate = n / rows if rows else 0.0
            # Only call it a spike when there is an earlier run to compare against.
            spiked = before is not None and n > expected
            sev = "high" if rate >= 0.05 else "medium" if rate >= 0.01 else "low"
            since = (
                f"; the previous run had {fmt(expected)}"
                if before is not None
                else "; this is the first run of this source, so there is no baseline yet"
            )
            out.append(
                {
                    **common,
                    "id": incident_id(column, "missing"),
                    "kind": "missing",
                    "column": column,
                    "entity": f"{source}.{column}",
                    "title": TAGS[("missing", "higher" if spiked else None)],
                    "explanation": f"{fmt(n)} of {fmt(rows)} values in {column} are empty"
                    f" ({_pct(n, rows)}){since}.",
                    "severity": sev,
                    "score": rate,
                    "n_findings": n,
                    "n_rows": n,
                    "detectors": ["completeness"],
                    "direction": "higher" if spiked else None,
                    "expected": {
                        "low": 0,
                        "high": expected,
                        "center": expected,
                        "text": fmt(expected),
                        "basis": "previous run" if before is not None else "no earlier run",
                    },
                    "actual": {"value": n, "text": f"{fmt(n)} ({_pct(n, rows)})"},
                    "delta_pct": round((n - expected) / expected, 4) if expected else None,
                    "chart": "history",
                    "sample": [],
                }
            )
        dups = int(m.get("duplicate_rows") or 0)
        if dups > 0:
            before = pm.get("duplicate_rows")
            expected = int(before or 0)
            rate = dups / rows if rows else 0.0
            out.append(
                {
                    **common,
                    "id": incident_id(None, "duplicates"),
                    "kind": "duplicates",
                    "column": None,
                    "entity": source,
                    "title": TAGS[("duplicates", None)],
                    "explanation": f"{fmt(dups)} rows repeat an earlier row ({_pct(dups, rows)} of"
                    f" {fmt(rows)}); a clean load has none.",
                    "severity": "high" if rate >= 0.05 else "medium" if rate >= 0.005 else "low",
                    "score": rate,
                    "n_findings": dups,
                    "n_rows": dups,
                    "detectors": ["uniqueness"],
                    "direction": "higher",
                    "expected": {
                        "low": 0,
                        "high": 0,
                        "center": 0,
                        "text": "0",
                        "basis": "clean load",
                    },
                    "actual": {"value": dups, "text": fmt(dups)},
                    "delta_pct": None,
                    "chart": "history",
                    "sample": [],
                }
            )
        invalid = int(m.get("invalid_rows") or 0)
        if invalid > 0:
            rules = m.get("violations") or {}
            top = ", ".join(
                f"{k} ({fmt(v)})" for k, v in sorted(rules.items(), key=lambda kv: -kv[1])[:3]
            )
            rate = invalid / rows if rows else 0.0
            out.append(
                {
                    **common,
                    "id": incident_id(None, "invalid"),
                    "kind": "invalid",
                    "column": None,
                    "entity": source,
                    "title": TAGS[("invalid", None)],
                    "explanation": f"{fmt(invalid)} rows break the schema"
                    + (f", most often {top}." if top else "."),
                    "severity": "high" if rate >= 0.05 else "medium" if rate >= 0.005 else "low",
                    "score": rate,
                    "n_findings": invalid,
                    "n_rows": invalid,
                    "detectors": ["schema"],
                    "direction": None,
                    "expected": {"low": 0, "high": 0, "center": 0, "text": "0"},
                    "actual": {"value": invalid, "text": f"{fmt(invalid)} ({_pct(invalid, rows)})"},
                    "delta_pct": None,
                    "chart": "history",
                    "sample": [],
                }
            )
        out.sort(key=lambda i: (SEVERITY_RANK.get(i["severity"], 3), -(i["score"] or 0)))
        return out

    def _findings(self, run_id: int, column: str | None, kind: str) -> list[dict[str, Any]]:
        rows = self.store.anomalies(
            run_id, limit=MAX_FINDINGS, column=column if column is not None else "(row)"
        )
        return [f for f in rows if finding_kind(f["detector"], f["column"]) == kind]

    def _detector_incident(
        self,
        run: dict[str, Any],
        df: pd.DataFrame | None,
        tcol: str | None,
        column: str | None,
        kind: str,
        parts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        rid = int(run["id"])
        findings = self._findings(rid, column, kind)
        detectors = sorted({p["detector"] for p in parts})
        max_score = max((p["max_score"] or 0 for p in parts), default=0)
        n_rows = len({repr(f["row_index"]) for f in findings})
        worst = max(findings, key=lambda f: f["score"] or 0) if findings else None
        sample = [
            {k: f[k] for k in ("id", "row_index", "value", "score", "detector", "reason")}
            for f in findings[:5]
        ]
        base = {
            "id": incident_id(column, kind),
            "kind": kind,
            "column": column,
            "severity": severity(max_score),
            "score": round(float(max_score), 4),
            "n_findings": len(findings),
            "n_rows": n_rows,
            "detectors": detectors,
            "sample": sample,
            "expected": None,
            "actual": None,
            "delta_pct": None,
            "direction": None,
        }
        groups = sorted({g for g in (group_of(d) for d in detectors) if g})
        by = f" Compared within each {', '.join(groups)}." if groups else ""

        if kind == "multivariate":
            cols: Counter[str] = Counter()
            for f in findings:
                m = re.search(r"most unusual: ([^=]+)=", f.get("reason") or "")
                if m:
                    cols[m.group(1).strip()] += 1
            common = ", ".join(c for c, _ in cols.most_common(2))
            return {
                **base,
                "title": TAGS[("multivariate", None)],
                "explanation": f"{fmt(n_rows)} rows have an unusual mix of values"
                + (f", most often driven by {common}" if common else "")
                + f" ({', '.join(detectors)}).{by}",
                "chart": None,
            }

        series = numeric(df[column]) if df is not None and column in df.columns else None
        values = [v for v in (_num(f["value"]) for f in findings) if v is not None]
        worst_v = _num(worst["value"]) if worst else None
        time_kind = kind in ("pattern", "level_shift")

        if time_kind and series is not None and series.notna().sum() >= 10:
            ordered, t = self._ordered(df, tcol)
            y = numeric(ordered[column]).to_numpy()
            pos = self._positions(ordered, findings)
            period = guess_period(ordered[tcol]) if tcol else None
            exp, lo, hi = series_band(y, period, kind, sorted(pos.values()))
            wpos = pos.get(repr(worst["row_index"])) if worst else None
            above = sum(1 for p in pos.values() if np.isfinite(y[p]) and y[p] > exp[p])
            below = len(pos) - above
            direction = "higher" if below == 0 else "lower" if above == 0 else "both"
            when = None
            if wpos is not None:
                e_lo, e_hi, e_c = float(lo[wpos]), float(hi[wpos]), float(exp[wpos])
                when = str(t.iloc[wpos])[:16] if t is not None else f"row {worst['row_index']}"
            else:
                e_lo, e_hi, e_c = (
                    float(np.nanmin(lo)),
                    float(np.nanmax(hi)),
                    float(np.nanmedian(exp)),
                )
            expected = {
                "low": e_lo,
                "high": e_hi,
                "center": e_c,
                "text": f"{fmt(e_lo)} \u2013 {fmt(e_hi)}",
            }
            actual = {
                "value": worst_v,
                "row": worst["row_index"] if worst else None,
                "at": when,
                "text": fmt(worst_v),
            }
            if kind == "level_shift":
                first = min(pos.values()) if pos else None
                start = str(t.iloc[first])[:16] if first is not None and t is not None else None
                expl = (
                    f"{column} moved to a new level"
                    + (f" from {start}" if start else "")
                    + f": {fmt(worst_v)} against a baseline near {fmt(e_c)}"
                    f" ({fmt(n_rows)} readings affected)."
                )
                title = TAGS[("level_shift", None)]
            else:
                expl = (
                    f"{fmt(n_rows)} readings of {column} do not fit the usual pattern;"
                    + (f" at {when}" if when else "")
                    + f" it read {fmt(worst_v)} where about {fmt(e_c)} was expected."
                )
                title = TAGS[("pattern", direction)]
            return {
                **base,
                "title": title,
                "explanation": expl + by,
                "expected": expected,
                "actual": actual,
                "delta_pct": _delta(worst_v, e_lo, e_hi),
                "direction": direction,
                "chart": "series",
            }

        band = robust_band(series) if series is not None else None
        if band is None and values:
            band = robust_band(pd.Series(values, dtype=float))
        per_row: dict[str, tuple[float, Any]] = {}
        for f in findings:
            v = _num(f["value"])
            if v is not None:
                per_row[repr(f["row_index"])] = (v, f["row_index"])
        if band:
            lo, hi, center = band["low"], band["high"], band["center"]
            outside = [(v, r) for v, r in per_row.values() if v < lo or v > hi]
            pool = outside or list(per_row.values())
            above = sum(1 for v, _ in pool if v > center)
            below = len(pool) - above
            direction = "higher" if below == 0 else "lower" if above == 0 else "both"
            # the actual value is the one furthest from the typical value, not the top score
            # (grouped detectors score within a group, so their top score can be mid-range)
            far = max(pool, key=lambda vr: abs(vr[0] - center)) if pool else (worst_v, None)
            actual_v, actual_row = far
            expected = {
                "low": lo,
                "high": hi,
                "center": center,
                "text": f"{fmt(lo)} \u2013 {fmt(hi)}",
            }
            word = {"higher": "above", "lower": "below", "both": "outside"}[direction]
            inside = len(per_row) - len(outside)
            if outside:
                n_out = len(outside)
                expl = (
                    f"{fmt(n_out)} {'value' if n_out == 1 else 'values'} in {column}"
                    f" {'is' if n_out == 1 else 'are'} {word} the expected range of"
                    f" {fmt(lo)} \u2013 {fmt(hi)}; the most extreme is {fmt(actual_v)}."
                )
                if inside:
                    where = f"their {', '.join(groups)}" if groups else "the rest of the row"
                    expl += f" {fmt(inside)} more {'looks' if inside == 1 else 'look'} unusual only against {where}."
            else:
                where = f"their {', '.join(groups)}" if groups else "the rest of their row"
                expl = (
                    f"{fmt(len(per_row))} values in {column} sit inside the column's typical range"
                    f" of {fmt(lo)} \u2013 {fmt(hi)} but are unusual against {where}."
                )
            by = ""
        else:
            lo = hi = None
            expected = None
            direction = "both"
            actual_v, actual_row = worst_v, worst["row_index"] if worst else None
            expl = f"{fmt(n_rows)} values in {column} were flagged by {', '.join(detectors)}."
        return {
            **base,
            "title": TAGS[(kind if kind == "outlier" else "pattern", direction)],
            "explanation": expl + by,
            "expected": expected,
            "actual": {"value": actual_v, "row": actual_row, "text": fmt(actual_v)},
            "delta_pct": _delta(actual_v, lo, hi),
            "direction": direction,
            "grouped": groups,
            "chart": "distribution" if band else None,
        }

    @staticmethod
    def _ordered(df: pd.DataFrame, tcol: str | None) -> tuple[pd.DataFrame, pd.Series | None]:
        if tcol and tcol in df.columns:
            t = pd.to_datetime(df[tcol], errors="coerce", format="mixed")
            order = np.argsort(t.to_numpy(), kind="stable")
            return df.iloc[order], t.iloc[order]
        return df, None

    @staticmethod
    def _positions(ordered: pd.DataFrame, findings: list[dict[str, Any]]) -> dict[str, int]:
        lookup = {repr(label): i for i, label in enumerate(ordered.index.tolist())}
        out = {}
        for f in findings:
            p = lookup.get(repr(f["row_index"]))
            if p is not None:
                out[repr(f["row_index"])] = p
        return out

    # -- listing with triage and mutes --------------------------------------
    def _decorate(self, incidents: list[dict[str, Any]]) -> list[dict[str, Any]]:
        triage = self.store.triage(sorted({i["run_id"] for i in incidents}))
        mutes = {(m["pipeline"], m["column"], m["kind"]): m for m in self.store.mutes()}
        out = []
        for inc in incidents:
            t = triage.get((inc["run_id"], inc["id"]))
            mute = mutes.get((inc["pipeline"], inc["column"], inc["kind"]))
            out.append(
                {
                    **inc,
                    "status": t["status"] if t else "open",
                    "triaged_at": t["updated_at"] if t else None,
                    "muted_until": mute["until"] if mute else None,
                    "mute_id": mute["id"] if mute else None,
                }
            )
        return out

    def for_run(self, run_id: int, include_muted: bool = False) -> dict[str, Any]:
        items = self._decorate(self.summaries(run_id))
        muted = [i for i in items if i["muted_until"]]
        shown = items if include_muted else [i for i in items if not i["muted_until"]]
        return {
            "run_id": run_id,
            "incidents": shown,
            "muted": len(muted),
            "open": sum(1 for i in items if i["status"] == "open" and not i["muted_until"]),
        }

    def get(self, run_id: int, inc_id: str) -> dict[str, Any]:
        for inc in self._decorate(self.summaries(run_id)):
            if inc["id"] == inc_id:
                return inc
        raise KeyError(f"Incident {inc_id} not found in run {run_id}")

    def recent(
        self, limit: int = 20, include_muted: bool = False, runs: int = 30
    ) -> list[dict[str, Any]]:
        """Incidents of the most recent finished runs, newest first."""
        found: list[dict[str, Any]] = []
        for r in self.store.runs(limit=runs, status="success"):
            found.extend(self.summaries(int(r["id"])))
        items = self._decorate(found)
        if not include_muted:
            items = [i for i in items if not i["muted_until"]]
        items.sort(
            key=lambda i: (
                -int(i["run_id"]),
                SEVERITY_RANK.get(i["severity"], 3),
                -(i["score"] or 0),
            )
        )
        return items[:limit]

    # -- triage ------------------------------------------------------------
    def triage(self, run_id: int, inc_id: str, status: str | None, note: str | None) -> dict:
        inc = self.get(run_id, inc_id)
        if status is not None and status not in TRIAGE_STATUSES:
            raise ValueError(f"status must be one of {sorted(TRIAGE_STATUSES)} or null")
        self.store.set_triage(run_id, inc_id, status, note)
        return self.get(run_id, inc["id"])

    def findings(self, run_id: int, inc_id: str) -> list[dict[str, Any]]:
        inc = self.get(run_id, inc_id)
        if inc["kind"] in ("missing", "duplicates", "invalid"):
            return []
        return self._findings(run_id, inc["column"], inc["kind"])

    def mute(self, run_id: int, inc_id: str, hours: float, note: str | None) -> dict[str, Any]:
        inc = self.get(run_id, inc_id)
        until = (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat(timespec="seconds")
        return self.store.mute(inc["pipeline"], inc["column"], inc["kind"], until, note)

    # -- charts ------------------------------------------------------------
    def chart(self, run_id: int, inc_id: str) -> dict[str, Any]:
        inc = self.get(run_id, inc_id)
        run = self.store.get_run(run_id)
        assert run is not None
        if inc["chart"] == "history":
            return self._history_chart(run, inc)
        if inc["chart"] not in ("distribution", "series"):
            return {"type": None}
        df, tcol = self._frame(run)
        findings = self._findings(run_id, inc["column"], inc["kind"])
        if inc["chart"] == "series" and df is not None:
            return self._series_chart(df, tcol, inc, findings)
        return self._distribution_chart(df, inc, findings)

    def _history_chart(self, run: dict[str, Any], inc: dict[str, Any]) -> dict[str, Any]:
        runs = self.store.runs(limit=30, pipeline=run["pipeline"], status="success")
        runs = [r for r in runs if int(r["id"]) <= int(run["id"])][:20][::-1]
        points = []
        for r in runs:
            m = (self.store.get_run(int(r["id"])) or {}).get("metrics") or {}
            if inc["kind"] == "missing":
                v = (m.get("null_counts") or {}).get(inc["column"])
                if v is None and "null_counts" in m:
                    v = 0
            elif inc["kind"] == "duplicates":
                v = m.get("duplicate_rows")
            else:
                v = m.get("invalid_rows")
            if v is not None:
                points.append({"t": r["started_at"], "v": v, "run_id": r["id"]})
        exp = inc.get("expected") or {}
        return {
            "type": "history",
            "label": {"missing": "Empty values", "duplicates": "Duplicate rows"}.get(
                inc["kind"], "Invalid rows"
            ),
            "points": points,
            "band": {"low": exp.get("low", 0), "high": exp.get("high", 0)},
            "current": run["id"],
        }

    def _distribution_chart(
        self, df: pd.DataFrame | None, inc: dict[str, Any], findings: list[dict[str, Any]]
    ) -> dict[str, Any]:
        col = inc["column"]
        if df is not None and col in df.columns:
            vals = numeric(df[col]).dropna()
        else:
            vals = pd.Series([v for v in (_num(f["value"]) for f in findings) if v is not None])
        exp = inc.get("expected") or {}
        if vals.empty:
            return {"type": None}
        lo_b, hi_b = exp.get("low"), exp.get("high")
        p1, p99 = (float(x) for x in np.percentile(vals, [1, 99]))
        if lo_b is not None and hi_b is not None:
            # keep the band readable: values far past it go to the overflow lanes
            span = (hi_b - lo_b) or abs(hi_b) or 1.0
            d_lo = min(lo_b, max(p1, lo_b - span / 2))
            d_hi = max(hi_b, min(p99, hi_b + span / 2))
        else:
            d_lo, d_hi = p1, p99
        if d_hi <= d_lo:
            d_lo, d_hi = float(vals.min()), float(vals.max())
        if d_hi <= d_lo:
            d_hi = d_lo + 1.0
        pad = (d_hi - d_lo) * 0.04
        d_lo, d_hi = d_lo - pad, d_hi + pad
        inside = vals[(vals >= d_lo) & (vals <= d_hi)]
        counts, edges = np.histogram(inside, bins=32, range=(d_lo, d_hi))
        marks, seen = [], set()
        for f in sorted(findings, key=lambda f: -(f["score"] or 0)):
            key = repr(f["row_index"])
            v = _num(f["value"])
            if key in seen or v is None:
                continue
            seen.add(key)
            marks.append({"v": v, "row": f["row_index"], "score": f["score"]})
            if len(marks) >= MAX_MARKS:
                break
        return {
            "type": "distribution",
            "column": col,
            "domain": [d_lo, d_hi],
            "edges": [float(e) for e in edges],
            "counts": [int(c) for c in counts],
            "below": int((vals < d_lo).sum()),
            "above": int((vals > d_hi).sum()),
            "min": float(vals.min()),
            "max": float(vals.max()),
            "n": len(vals),
            "band": {"low": lo_b, "high": hi_b, "center": exp.get("center")},
            "marks": marks,
        }

    def _series_chart(
        self,
        df: pd.DataFrame,
        tcol: str | None,
        inc: dict[str, Any],
        findings: list[dict[str, Any]],
    ) -> dict[str, Any]:
        col = inc["column"]
        ordered, t = self._ordered(df, tcol)
        y = numeric(ordered[col]).to_numpy()
        pos = self._positions(ordered, findings)
        period = guess_period(ordered[tcol]) if tcol else None
        exp, lo, hi = series_band(y, period, inc["kind"], sorted(pos.values()))
        n = len(y)
        flagged = sorted(set(pos.values()))
        keep = set(range(0, n, max(1, math.ceil(n / MAX_POINTS)))) | set(flagged)
        idx = sorted(keep)

        def clean(a: np.ndarray, i: int) -> float | None:
            v = float(a[i])
            return round(v, 6) if math.isfinite(v) else None

        where = {p: k for k, p in enumerate(idx)}
        xs = [str(t.iloc[i]) if t is not None and pd.notna(t.iloc[i]) else i for i in idx]
        return {
            "type": "series",
            "column": col,
            "time": tcol if t is not None else None,
            "x": xs,
            "y": [clean(y, i) for i in idx],
            "expected": [clean(exp, i) for i in idx],
            "low": [clean(lo, i) for i in idx],
            "high": [clean(hi, i) for i in idx],
            "flagged": [where[p] for p in flagged],
            "period": period,
            "focus": self._focus(
                idx, flagged, period, inc["kind"], pos.get(repr(inc["actual"]["row"]))
            ),
        }

    @staticmethod
    def _focus(
        idx: list[int], flagged: list[int], period: int | None, kind: str, worst: int | None
    ) -> list[int] | None:
        """A window (indexes into the sent points) that keeps the anomaly readable."""
        n = idx[-1] + 1 if idx else 0
        span = 14 * period if period else 300
        if not flagged or n <= span * 1.5:
            return None
        if kind == "level_shift":
            start = max(0, min(flagged) - span // 2)
            end = n - 1
        else:
            mid = worst if worst is not None else flagged[len(flagged) // 2]
            start = max(0, min(mid - span // 2, n - span))
            end = min(n - 1, start + span)
        lo = next(i for i, p in enumerate(idx) if p >= start)
        hi = max(i for i, p in enumerate(idx) if p <= end)
        return [lo, hi]

    # -- health overview -----------------------------------------------------
    def health(self) -> dict[str, Any]:
        """One row per monitored source (pipeline or analysed file) plus KPIs."""
        rows = []
        for name in self.store.pipelines():
            recent = self.store.runs(limit=20, pipeline=name)
            if not recent:
                continue
            last = recent[0]
            finished = [r for r in recent if r["status"] == "success"]
            latest = finished[0] if finished else None
            open_items: list[dict[str, Any]] = []
            muted = 0
            if latest is not None:
                listed = self.for_run(int(latest["id"]))
                open_items = [i for i in listed["incidents"] if i["status"] == "open"]
                muted = listed["muted"]
            quality = [
                {"run_id": r["id"], "t": r["started_at"], "v": r["quality_score"]}
                for r in reversed(finished)
                if r["quality_score"] is not None
            ]
            trend = None
            if len(quality) >= 2:
                trend = round(quality[-1]["v"] - quality[-2]["v"], 4)
            worst = min((SEVERITY_RANK.get(i["severity"], 3) for i in open_items), default=None)
            q_now = latest["quality_score"] if latest else None
            if last["status"] == "failed":
                status = "failing"
            elif worst == 0 or (q_now is not None and q_now < 0.9):
                status = "degraded"
            elif open_items:
                status = "warning"
            else:
                status = "healthy"
            rows.append(
                {
                    "pipeline": name,
                    "name": source_name(name),
                    "kind": "analysis" if name.startswith(ANALYSIS_PREFIX) else "pipeline",
                    "status": status,
                    "last_run": {
                        k: last.get(k) for k in ("id", "status", "started_at", "rows", "error")
                    },
                    "latest_success": latest["id"] if latest else None,
                    "quality": q_now,
                    "quality_series": quality,
                    "trend": trend,
                    "anomaly_rate": latest["anomaly_rate"] if latest else None,
                    "rows": latest["rows"] if latest else None,
                    "open_incidents": len(open_items),
                    "high_incidents": sum(1 for i in open_items if i["severity"] == "high"),
                    "muted": muted,
                    "runs": self.store.count_runs(pipeline=name),
                }
            )
        order = {"failing": 0, "degraded": 1, "warning": 2, "healthy": 3}
        rows.sort(key=lambda r: (order[r["status"]], -(r["open_incidents"]), r["name"]))
        qualities = [r["quality"] for r in rows if r["quality"] is not None]
        summary = self.store.summary()
        return {
            "sources": rows,
            "kpis": {
                "open_incidents": sum(r["open_incidents"] for r in rows),
                "high_incidents": sum(r["high_incidents"] for r in rows),
                "monitored": len(rows),
                "unhealthy": sum(1 for r in rows if r["status"] in ("failing", "degraded")),
                "avg_quality": round(sum(qualities) / len(qualities), 4) if qualities else None,
                "rows_scanned": summary["rows_processed"],
                "runs": summary["runs"] + summary["failed_runs"],
            },
        }
