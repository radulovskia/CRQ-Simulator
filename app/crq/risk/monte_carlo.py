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


@dataclass(frozen=True)
class Triple:
    minimum: float
    mode: float
    maximum: float


@dataclass(frozen=True)
class FairSimulationResult:
    simulation: SimulationResult
    probability_of_loss_year: float
    expected_annual_loss_by_form: dict[str, float]
    expected_primary: float
    expected_secondary: float
    annual_samples: np.ndarray | None = None


def _as_triple(value: Triple | tuple) -> Triple:
    if isinstance(value, Triple):
        return value
    return Triple(float(value[0]), float(value[1]), float(value[2]))


def _sample_triple(triple: Triple, lambda_param: float, rng: np.random.Generator, count: int) -> np.ndarray:
    if count == 0:
        return np.array([], dtype=float)
    if triple.maximum == triple.minimum:
        return np.full(count, triple.minimum)
    return _sample_pert(fit_beta_pert(triple.minimum, triple.mode, triple.maximum, lambda_param), rng, count)


def run_fair_simulation(
    lef: Triple | tuple,
    frequency_lambda: float,
    primary: dict[str, Triple | tuple],
    secondary: dict[str, Triple | tuple],
    secondary_probability: float,
    magnitude_lambda: float,
    iterations: int = 10_000,
    seed: int | None = None,
    magnitude_reference: Triple | tuple | None = None,
    return_samples: bool = False,
) -> FairSimulationResult:
    lef_triple = _as_triple(lef)
    validate_three_point_estimate(lef_triple.minimum, lef_triple.mode, lef_triple.maximum, "Loss event frequency")
    if not lef_triple.minimum < lef_triple.maximum:
        raise ValueError("Loss event frequency: minimum must be less than maximum")
    primary_triples = {name: _as_triple(value) for name, value in primary.items()}
    secondary_triples = {name: _as_triple(value) for name, value in secondary.items()}
    for label, triple in {**primary_triples, **secondary_triples}.items():
        if triple.minimum > triple.maximum or not (triple.minimum <= triple.mode <= triple.maximum):
            raise ValueError(f"{label}: mode must satisfy minimum <= mode <= maximum")

    if seed is None:
        seed = int(np.random.default_rng().integers(0, 2**31))
    rng = np.random.default_rng(seed)

    rate = _sample_triple(lef_triple, frequency_lambda, rng, iterations)
    counts = rng.poisson(rate)
    event_count = int(counts.sum())
    if event_count > 5_000_000:
        raise ValueError("Too many simulated events; lower iterations or the frequency cap")

    form_names = list(primary_triples) + list(secondary_triples)
    form_draws = {name: np.zeros(0) for name in form_names}
    event_loss = np.zeros(0)
    if event_count:
        primary_loss = np.zeros(event_count)
        for name, triple in primary_triples.items():
            draw = _sample_triple(triple, magnitude_lambda, rng, event_count)
            form_draws[name] = draw
            primary_loss += draw
        has_secondary = rng.random(event_count) < secondary_probability
        secondary_loss = np.zeros(event_count)
        for name, triple in secondary_triples.items():
            draw = _sample_triple(triple, magnitude_lambda, rng, event_count) * has_secondary
            form_draws[name] = draw
            secondary_loss += draw
        event_loss = primary_loss + secondary_loss

    if event_count:
        owner = np.repeat(np.arange(iterations), counts)
        annual = np.bincount(owner, weights=event_loss, minlength=iterations).astype(float)
    else:
        annual = np.zeros(iterations, dtype=float)

    form_expected = {
        name: float(draw.sum() / iterations) if draw.size else 0.0 for name, draw in form_draws.items()
    }
    for name in form_names:
        form_expected.setdefault(name, 0.0)
    expected_primary = float(sum(form_expected[name] for name in primary_triples))
    expected_secondary = float(sum(form_expected[name] for name in secondary_triples))

    frequency_params = fit_beta_pert(
        lef_triple.minimum, lef_triple.mode, lef_triple.maximum, lambda_param=frequency_lambda
    )
    maximum_count = int(counts.max()) if counts.size else 0
    edges = np.arange(0, maximum_count + 2) - 0.5
    frequency_counts, frequency_edges = np.histogram(counts, bins=edges)
    frequency = _summarize_samples(counts.astype(float), frequency_params)
    frequency = VariableSimulationResult(
        mean=frequency.mean,
        median=frequency.median,
        std=frequency.std,
        p5=frequency.p5,
        p50=frequency.p50,
        p95=frequency.p95,
        p99=frequency.p99,
        min=frequency.min,
        max=frequency.max,
        distribution=frequency_params,
        histogram=Histogram(bin_edges=frequency_edges.tolist(), counts=frequency_counts.tolist()),
    )

    reference = _as_triple(magnitude_reference) if magnitude_reference is not None else _collapsed_reference(
        primary_triples, secondary_triples, secondary_probability
    )
    single_primary = len(primary_triples) == 1 and not secondary_triples
    if reference.maximum == reference.minimum:
        magnitude_params = DistributionParams(
            minimum=reference.minimum,
            mode=reference.mode,
            maximum=reference.maximum,
            alpha=1.0,
            beta=1.0,
            lambda_param=magnitude_lambda,
        )
    else:
        magnitude_params = fit_beta_pert(
            reference.minimum, reference.mode, reference.maximum, lambda_param=magnitude_lambda
        )
    if not single_primary:
        magnitude_params = DistributionParams(
            minimum=magnitude_params.minimum,
            mode=magnitude_params.mode,
            maximum=magnitude_params.maximum,
            alpha=magnitude_params.alpha,
            beta=magnitude_params.beta,
            lambda_param=magnitude_params.lambda_param,
            distribution="compound_sum",
        )
    magnitude_samples = event_loss if event_loss.size else np.array([0.0])
    magnitude = _summarize_samples(magnitude_samples, magnitude_params)

    positive = np.flatnonzero(counts > 0)
    if positive.size:
        mean_event = annual[positive] / counts[positive]
        scatter = _build_scatter(counts[positive].astype(float), mean_event, annual[positive])
    else:
        scatter = []

    simulation = SimulationResult(
        iterations=iterations,
        seed=seed,
        frequency=frequency,
        magnitude=magnitude,
        aggregate_loss=_summarize_aggregate_loss(annual),
        scatter=scatter,
    )
    return FairSimulationResult(
        simulation=simulation,
        probability_of_loss_year=float(np.mean(counts > 0)),
        expected_annual_loss_by_form=form_expected,
        expected_primary=expected_primary,
        expected_secondary=expected_secondary,
        annual_samples=annual if return_samples else None,
    )


def _collapsed_reference(
    primary: dict[str, Triple],
    secondary: dict[str, Triple],
    secondary_probability: float,
) -> Triple:
    def combine(index: int) -> float:
        primary_value = sum(getattr(triple, ("minimum", "mode", "maximum")[index]) for triple in primary.values())
        secondary_value = sum(getattr(triple, ("minimum", "mode", "maximum")[index]) for triple in secondary.values())
        return primary_value + secondary_probability * secondary_value

    return Triple(combine(0), combine(1), combine(2))
