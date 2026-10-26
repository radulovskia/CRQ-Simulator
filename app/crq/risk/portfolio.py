import numpy as np

from crq.risk.appetite import get_appetite
from crq.risk.monte_carlo import _build_exceedance_curve, _summarize_aggregate_loss, run_fair_simulation
from crq.risk.risk_engine import (
    PRIMARY,
    SECONDARY,
    apply_controls,
    collapse,
    data_quality,
    effective_factors,
    load_scenario_context,
)
from crq.risk.scenarios import list_scenarios


def _contexts() -> list[dict]:
    return [load_scenario_context(item["scenario_id"]) for item in list_scenarios()["items"]]


def _zero_summary(applied: dict, forms: dict[str, float] | None = None) -> dict:
    form_values = forms or {name: 0.0 for name in (*PRIMARY, *SECONDARY)}
    return {
        "eliminated": applied["eliminated"],
        "eliminated_by": applied["eliminated_by"],
        "applied_control_ids": [control["control_id"] for control in applied["applied_controls"]],
        "annual_control_cost": applied["annual_control_cost"],
        "annual_control_cost_known": applied["annual_control_cost_known"],
        "mean": 0.0,
        "median": 0.0,
        "std": 0.0,
        "p95": 0.0,
        "p99": 0.0,
        "var_95": 0.0,
        "var_99": 0.0,
        "tvar_95": 0.0,
        "tvar_99": 0.0,
        "probability_of_loss_year": 0.0,
        "expected_annual_loss_by_form": form_values,
        "reduction_vs_inherent_pct": None,
    }


def _summary(fair, applied: dict, inherent_mean: float | None) -> dict:
    aggregate = fair.simulation.aggregate_loss
    reduction = None
    if inherent_mean is not None:
        reduction = None if inherent_mean == 0 else 100 * (1 - aggregate.mean / inherent_mean)
    return {
        "eliminated": applied["eliminated"],
        "eliminated_by": applied["eliminated_by"],
        "applied_control_ids": [control["control_id"] for control in applied["applied_controls"]],
        "annual_control_cost": applied["annual_control_cost"],
        "annual_control_cost_known": applied["annual_control_cost_known"],
        "mean": aggregate.mean,
        "median": aggregate.median,
        "std": aggregate.std,
        "p95": aggregate.p95,
        "p99": aggregate.p99,
        "var_95": aggregate.var_95,
        "var_99": aggregate.var_99,
        "tvar_95": aggregate.tvar_95,
        "tvar_99": aggregate.tvar_99,
        "probability_of_loss_year": fair.probability_of_loss_year,
        "expected_annual_loss_by_form": fair.expected_annual_loss_by_form,
        "reduction_vs_inherent_pct": reduction,
    }


def _pack_run(summary: dict, collapsed: dict, samples, applied: dict, fair=None):
    return {"summary": summary, "collapsed": collapsed, "samples": samples, "applied": applied, "fair": fair}


def run_control_set(context: dict, control_set: str, iterations: int, seed: int, control_ids: list[str] | None = None, return_samples: bool = False):
    applied = apply_controls(context, control_set, control_ids)
    factors = effective_factors(context, applied)
    collapsed = collapse(factors)
    if applied["eliminated"]:
        samples = np.zeros(iterations) if return_samples else None
        summary = _zero_summary(applied)
        summary["reduction_vs_inherent_pct"] = None
        return _pack_run(summary, collapsed, samples, applied)
    fair = run_fair_simulation(
        lef=collapsed["frequency"],
        frequency_lambda=collapsed["frequency_lambda"],
        primary=collapsed["primary"],
        secondary=collapsed["secondary"],
        secondary_probability=collapsed["slp"],
        magnitude_lambda=collapsed["magnitude_lambda"],
        iterations=iterations,
        seed=seed,
        magnitude_reference=collapsed["magnitude"],
        return_samples=return_samples,
    )
    return _pack_run(_summary(fair, applied, None), collapsed, fair.annual_samples, applied, fair)


def portfolio_from_samples(samples: list[np.ndarray], iterations: int) -> tuple[dict, np.ndarray]:
    total = np.zeros(iterations) if not samples else np.sum(np.vstack(samples), axis=0)
    aggregate = _summarize_aggregate_loss(total)
    summary = {
        "mean": aggregate.mean,
        "median": aggregate.median,
        "var_95": aggregate.var_95,
        "var_99": aggregate.var_99,
        "tvar_95": aggregate.tvar_95,
        "tvar_99": aggregate.tvar_99,
        "probability_of_loss_year": float(np.mean(total > 0)),
    }
    return summary, total, aggregate


def in_appetite_test(status: str) -> bool:
    return status != "Draft"


def appetite_status(value: float | None, limit: float | None) -> dict:
    if limit is None or value is None:
        return {"value": value, "limit": limit, "headroom": None, "status": "Not defined"}
    return {
        "value": value,
        "limit": limit,
        "headroom": limit - value,
        "status": "Within" if value <= limit else "Breached",
    }


def card(context: dict) -> dict:
    scenario = context["scenario"]
    return {
        "scenario_id": scenario["scenario_id"],
        "scenario": scenario["scenario"],
        "threat_actor_id": scenario["threat_actor_id"],
        "threat_actor": context["threat_actor"],
        "attack_vector_id": scenario["attack_vector_id"],
        "attack_vector": context["attack_vector"],
        "technique_chain": context["vector"]["technique_chain"],
        "loss_event_type": context["vector"]["loss_event_type"],
        "target_type": scenario["target_type"],
        "target_id": scenario["target_id"],
        "target_name": context["target_name"],
        "risk_owner_ou_id": scenario["risk_owner_ou_id"],
        "risk_owner_ou": context["risk_owner_ou"],
        "status": scenario["status"],
    }


def build_register(iterations: int, seed: int, include_samples: bool = True) -> dict:
    contexts = _contexts()
    appetite = get_appetite()
    items = []
    samples = {name: [] for name in ("inherent", "current", "target")}
    analytics = {name: [] for name in ("inherent", "current", "target")}
    for ordinal, context in enumerate(contexts):
        scenario_seed = seed + ordinal
        runs = {}
        analytic = {}
        tested = in_appetite_test(context["scenario"]["status"])
        for name in ("inherent", "current", "target"):
            run = run_control_set(context, name, iterations, scenario_seed, return_samples=include_samples)
            analytic[name] = run["collapsed"]["analytic_ale"]
            runs[name] = run
            if include_samples and tested:
                samples[name].append(run["samples"])
        inherent_mean = runs["inherent"]["summary"]["mean"]
        for name in ("current", "target"):
            mean = runs[name]["summary"]["mean"]
            runs[name]["summary"]["reduction_vs_inherent_pct"] = None if inherent_mean == 0 else 100 * (1 - mean / inherent_mean)
        runs["inherent"]["summary"]["reduction_vs_inherent_pct"] = 0.0 if inherent_mean else None
        quality = data_quality(context)
        tolerance = appetite["scenario_ale_tolerance"]
        items.append(
            {
                **card(context),
                "inherent": runs["inherent"]["summary"],
                "current": runs["current"]["summary"],
                "target": runs["target"]["summary"],
                "analytic_ale": analytic,
                "in_appetite_test": tested,
                "above_tolerance": None if not tested or tolerance is None else runs["current"]["summary"]["mean"] > tolerance,
                "data_quality": quality,
                "context": context,
                "runs": runs,
            }
        )
        if tested:
            for name in analytics:
                analytics[name].append(analytic[name])
    portfolio = {}
    curves = {}
    totals = {}
    for name in ("inherent", "current", "target"):
        if include_samples:
            summary, total, aggregate = portfolio_from_samples(samples[name], iterations)
            portfolio[name] = summary
            totals[name] = total
            curves[name] = [
                {"loss": point.loss, "exceedance_probability": point.exceedance_probability}
                for point in aggregate.exceedance_curve.points
            ]
        else:
            portfolio[name] = {
                "mean": float(sum(item[name]["mean"] for item in items if item["in_appetite_test"])),
                "median": None,
                "var_95": None,
                "var_99": None,
                "tvar_95": None,
                "tvar_99": None,
                "probability_of_loss_year": None,
            }
    evaluation = {
        "portfolio_ale": appetite_status(portfolio["current"]["mean"], appetite["portfolio_ale_limit"]),
        "portfolio_var_95": appetite_status(portfolio["current"]["var_95"], appetite["portfolio_var95_limit"]),
    }
    return {
        "iterations": iterations,
        "seed": seed,
        "items": items,
        "portfolio": portfolio,
        "curves": curves,
        "totals": totals,
        "appetite": appetite,
        "evaluation": evaluation,
        "analytics": analytics,
    }
