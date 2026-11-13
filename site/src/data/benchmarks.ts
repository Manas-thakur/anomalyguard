// Real output of `anomalyguard demo benchmark` (seed 42, default thresholds),
// v0.3.0 code. Full tables: docs/benchmarks.
export interface BenchRow {
	dataset: string;
	shape: string;
	detector: string;
	precision: string;
	recall: string;
	f1: string;
	auc: string;
	baseline: { detector: string; f1: string; auc: string };
	note: string;
}

export const best: BenchRow[] = [
	{
		dataset: 'orders',
		shape: '2,000 rows · 70 anomalies (40 point, 30 contextual)',
		detector: 'mad by region',
		precision: '0.81',
		recall: '1.00',
		f1: '0.90',
		auc: '1.000',
		baseline: { detector: 'mad (global)', f1: '0.63', auc: '0.943' },
		note: 'Prices depend on the region. Scoring within each region catches all 30 contextual anomalies; the global detector catches none.',
	},
	{
		dataset: 'sensor',
		shape: '1,440 hourly readings · 150 anomalies',
		detector: 'seasonal + cusum (ensemble max)',
		precision: '0.89',
		recall: '0.99',
		f1: '0.94',
		auc: '0.997',
		baseline: { detector: 'mad (global)', f1: '0.00', auc: '0.584' },
		note: 'A daily cycle with point, contextual, level-shift and drift anomalies. The seasonal residual and CUSUM cover each other.',
	},
	{
		dataset: 'tabular',
		shape: '2,000 rows · 6 correlated features · 100 anomalies',
		detector: 'lof',
		precision: '0.81',
		recall: '0.88',
		f1: '0.84',
		auc: '0.975',
		baseline: { detector: 'mad (global)', f1: '0.65', auc: '0.804' },
		note: 'Half the anomalies break the correlation between features while every value stays in range. Univariate detectors cannot see them.',
	},
];
