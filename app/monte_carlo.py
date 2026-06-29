"""Monte Carlo simulation using the Beta PERT distribution."""

from dataclasses import dataclass

import numpy as np


DEFAULT_PERT_LAMBDA = 4.0
DEFAULT_HISTOGRAM_BINS = 40
DEFAULT_LEC_POINTS = 100
MAX_SCATTER_POINTS = 2000


@dataclass(frozen=True)
class Histogram:
    bin_edges: list[float]
    counts: list[int]


@dataclass(frozen=True)
class ExceedancePoint:
    loss: float
    exceedance_probability: float


@dataclass(frozen=True)
class ExceedanceCurve:
    points: list[ExceedancePoint]


@dataclass(frozen=True)
class ScatterPoint:
    frequency: float
    magnitude: float
    aggregate_loss: float


@dataclass(frozen=True)
class DistributionParams:
    minimum: float
    mode: float
    maximum: float
    alpha: float
    beta: float
    lambda_param: float = DEFAULT_PERT_LAMBDA
    distribution: str = "beta_pert"


@dataclass(frozen=True)
class VariableSimulationResult:
    mean: float
    median: float
    std: float
    p5: float
    p50: float
    p95: float
    p99: float
    min: float
    max: float
    distribution: DistributionParams
    histogram: Histogram
    samples: np.ndarray | None = None


@dataclass(frozen=True)
class AggregateLossResult:
    mean: float
    median: float
    std: float
    p5: float
    p50: float
    p95: float
    p99: float
    min: float
    max: float
    var_95: float
    var_99: float
    tvar_95: float
    tvar_99: float
    histogram: Histogram
    exceedance_curve: ExceedanceCurve


@dataclass(frozen=True)
class SimulationResult:
    iterations: int
    seed: int
    frequency: VariableSimulationResult
    magnitude: VariableSimulationResult
    aggregate_loss: AggregateLossResult
    scatter: list[ScatterPoint]


def validate_three_point_estimate(minimum: float, mode: float, maximum: float, label: str) -> None:
    if not (minimum < maximum):
        raise ValueError(f"{label}: minimum must be less than maximum")
    if not (minimum <= mode <= maximum):
        raise ValueError(f"{label}: mode must satisfy minimum <= mode <= maximum")


def fit_beta_pert(
    minimum: float,
    mode: float,
    maximum: float,
    lambda_param: float = DEFAULT_PERT_LAMBDA,
) -> DistributionParams:
    """
    Derive Beta PERT shape parameters from minimum, mode, and maximum.

    X = minimum + (maximum - minimum) * Beta(alpha, beta)
    alpha = 1 + lambda * (mode - minimum) / (maximum - minimum)
    beta  = 1 + lambda * (maximum - mode) / (maximum - minimum)
    """
    span = maximum - minimum
    alpha = 1.0 + lambda_param * (mode - minimum) / span
    beta = 1.0 + lambda_param * (maximum - mode) / span
    return DistributionParams(
        minimum=minimum,
        mode=mode,
        maximum=maximum,
        alpha=float(alpha),
        beta=float(beta),
        lambda_param=lambda_param,
    )


def _sample_pert(
    params: DistributionParams,
    rng: np.random.Generator,
    iterations: int,
) -> np.ndarray:
    beta_samples = rng.beta(params.alpha, params.beta, size=iterations)
    return params.minimum + (params.maximum - params.minimum) * beta_samples


def _build_histogram(samples: np.ndarray) -> Histogram:
    counts, bin_edges = np.histogram(samples, bins=DEFAULT_HISTOGRAM_BINS)
    return Histogram(
        bin_edges=bin_edges.tolist(),
        counts=counts.tolist(),
    )


def _build_exceedance_curve(samples: np.ndarray, num_points: int = DEFAULT_LEC_POINTS) -> ExceedanceCurve:
    sorted_samples = np.sort(samples)
    thresholds = np.linspace(sorted_samples[0], sorted_samples[-1], num_points)
    exceedance = np.array([(samples > threshold).mean() for threshold in thresholds])
    points = [
        ExceedancePoint(loss=float(loss), exceedance_probability=float(prob))
        for loss, prob in zip(thresholds, exceedance)
    ]
    return ExceedanceCurve(points=points)


def _compute_tvar(samples: np.ndarray, var_threshold: float) -> float:
    tail = samples[samples >= var_threshold]
    if tail.size == 0:
        return float(var_threshold)
    return float(np.mean(tail))


def _summarize_aggregate_loss(samples: np.ndarray) -> AggregateLossResult:
    p95 = float(np.percentile(samples, 95))
    p99 = float(np.percentile(samples, 99))
    return AggregateLossResult(
        mean=float(np.mean(samples)),
        median=float(np.median(samples)),
        std=float(np.std(samples)),
        p5=float(np.percentile(samples, 5)),
        p50=float(np.percentile(samples, 50)),
        p95=p95,
        p99=p99,
        min=float(np.min(samples)),
        max=float(np.max(samples)),
        var_95=p95,
        var_99=p99,
        tvar_95=_compute_tvar(samples, p95),
        tvar_99=_compute_tvar(samples, p99),
        histogram=_build_histogram(samples),
        exceedance_curve=_build_exceedance_curve(samples),
    )


def _build_scatter(
    frequency_samples: np.ndarray,
    magnitude_samples: np.ndarray,
    aggregate_samples: np.ndarray,
) -> list[ScatterPoint]:
    total = frequency_samples.size
    if total <= MAX_SCATTER_POINTS:
        indices = np.arange(total)
    else:
        indices = np.linspace(0, total - 1, MAX_SCATTER_POINTS, dtype=int)

    return [
        ScatterPoint(
            frequency=float(frequency_samples[i]),
            magnitude=float(magnitude_samples[i]),
            aggregate_loss=float(aggregate_samples[i]),
        )
        for i in indices
    ]


def _summarize_samples(
    samples: np.ndarray,
    params: DistributionParams,
    return_samples: bool = False,
) -> VariableSimulationResult:
    return VariableSimulationResult(
        mean=float(np.mean(samples)),
        median=float(np.median(samples)),
        std=float(np.std(samples)),
        p5=float(np.percentile(samples, 5)),
        p50=float(np.percentile(samples, 50)),
        p95=float(np.percentile(samples, 95)),
        p99=float(np.percentile(samples, 99)),
        min=float(np.min(samples)),
        max=float(np.max(samples)),
        distribution=params,
        histogram=_build_histogram(samples),
        samples=samples if return_samples else None,
    )


def run_monte_carlo(
    frequency_minimum: float,
    frequency_mode: float,
    frequency_maximum: float,
    magnitude_minimum: float,
    magnitude_mode: float,
    magnitude_maximum: float,
    iterations: int = 10_000,
    seed: int | None = None,
    frequency_lambda: float = DEFAULT_PERT_LAMBDA,
    magnitude_lambda: float = DEFAULT_PERT_LAMBDA,
    return_samples: bool = False,
) -> SimulationResult:
    validate_three_point_estimate(
        frequency_minimum,
        frequency_mode,
        frequency_maximum,
        "Frequency",
    )
    validate_three_point_estimate(
        magnitude_minimum,
        magnitude_mode,
        magnitude_maximum,
        "Magnitude",
    )

    frequency_params = fit_beta_pert(
        frequency_minimum,
        frequency_mode,
        frequency_maximum,
        lambda_param=frequency_lambda,
    )
    magnitude_params = fit_beta_pert(
        magnitude_minimum,
        magnitude_mode,
        magnitude_maximum,
        lambda_param=magnitude_lambda,
    )

    if seed is None:
        seed = int(np.random.default_rng().integers(0, 2**31))
    rng = np.random.default_rng(seed)

    frequency_samples = _sample_pert(frequency_params, rng, iterations)
    magnitude_samples = _sample_pert(magnitude_params, rng, iterations)
    aggregate_samples = frequency_samples * magnitude_samples

    return SimulationResult(
        iterations=iterations,
        seed=seed,
        frequency=_summarize_samples(
            frequency_samples,
            frequency_params,
            return_samples=return_samples,
        ),
        magnitude=_summarize_samples(
            magnitude_samples,
            magnitude_params,
            return_samples=return_samples,
        ),
        aggregate_loss=_summarize_aggregate_loss(aggregate_samples),
        scatter=_build_scatter(frequency_samples, magnitude_samples, aggregate_samples),
    )
