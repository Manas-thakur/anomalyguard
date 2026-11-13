// Mirrors `anomalyguard detectors` (v0.3.0). Keep in sync with
// src/anomalyguard/detect/registry.py.
export interface DetectorRow {
	name: string;
	category: 'statistical' | 'ml' | 'timeseries' | 'contextual' | 'ensemble';
	description: string;
	threshold: string;
}

export const detectors: DetectorRow[] = [
	{ name: 'zscore', category: 'statistical', description: 'Distance from the mean in standard deviations (assumes roughly normal data).', threshold: '3.0' },
	{ name: 'mad', category: 'statistical', description: 'Modified z-score using median and median absolute deviation (robust).', threshold: '3.5' },
	{ name: 'iqr', category: 'statistical', description: 'Tukey fences: outside Q1 - k*IQR or Q3 + k*IQR (k=1.5).', threshold: '1.5' },
	{ name: 'grubbs', category: 'statistical', description: 'Iterative Grubbs test for outliers in normally distributed data.', threshold: 'alpha 0.05' },
	{ name: 'iforest', category: 'ml', description: 'Isolation Forest: anomalies are isolated by fewer random splits.', threshold: 'auto (min 0.5)' },
	{ name: 'lof', category: 'ml', description: 'Local Outlier Factor: density relative to neighbours (local outliers).', threshold: 'auto (min 1.2)' },
	{ name: 'knn', category: 'ml', description: 'Mean distance to the k nearest neighbours (global outliers).', threshold: 'auto' },
	{ name: 'rolling_zscore', category: 'timeseries', description: 'Deviation from a trailing rolling window (median/IQR or mean/std).', threshold: '4.0, window 24' },
	{ name: 'ewma', category: 'timeseries', description: 'Residual from an exponentially weighted moving average forecast.', threshold: '4.0, span 24' },
	{ name: 'seasonal', category: 'timeseries', description: 'Robust z-score of residuals after removing trend and seasonality.', threshold: '4.0, period 24' },
	{ name: 'cusum', category: 'timeseries', description: 'CUSUM change-point detection for sustained level shifts and drift.', threshold: 'h 5, k 1.0' },
	{ name: 'grouped', category: 'contextual', description: 'Runs a base detector separately within each group (contextual anomalies).', threshold: 'per base detector' },
	{ name: 'ensemble', category: 'ensemble', description: 'Combines detectors by score averaging or majority vote.', threshold: '1.0 normalised' },
];

export const categoryLabel: Record<DetectorRow['category'], string> = {
	statistical: 'Statistical',
	ml: 'Machine learning',
	timeseries: 'Time series',
	contextual: 'Contextual',
	ensemble: 'Ensemble',
};
