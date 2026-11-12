"""AnomalyGuard - data anomaly detection and remediation.

Quick use::

    import anomalyguard as ag

    df = ag.read("orders.csv")
    report = ag.detect(df, methods=["mad", "iforest"])
    result = ag.fix(df)
    result.data.to_csv("clean.csv", index=False)
"""

__version__ = "0.2.0"

from anomalyguard.api import Profile, detect, fix, profile, read

__all__ = ["Profile", "__version__", "detect", "fix", "profile", "read"]
