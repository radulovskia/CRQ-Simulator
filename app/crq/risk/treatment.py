"""Treatment economics. BCR and ROSI are null (shown as N/A) when annualised cost is zero."""

from itertools import combinations

from crq.risk.portfolio import appetite_status, build_register, in_appetite_test, portfolio_from_samples, run_control_set
from crq.risk.risk_engine import (
    analytic_ale,
    apply_controls,
    collapse,
    data_gap_bullet,
    effective_factors,
    gap_names,
    organisational_unit_names,
)
from crq.version import INDEPENDENCE_NOTE


def _annualised(control: dict, years: int) -> float | None:
    if control["implementation_cost"] is None or control["annual_cost"] is None:
        return None
    return control["annual_cost"] + control["implementation_cost"] / years


def _ratios(reduction: float, annualised: float, cost_known: bool) -> tuple[float | None, float | None, float | None]:
    if not cost_known or annualised is None:
        return None, None, None
    net_benefit = reduction - annualised
    # A zero-cost control has no defined benefit-cost ratio or ROSI.
    if annualised == 0:
        return None, None, net_benefit
    return reduction / annualised, net_benefit / annualised, net_benefit


def _ids_for(context: dict, extra: set[str]) -> list[str]:
    current = {mapping["control_id"] for mapping in context["mappings"] if mapping["status"] == "Implemented"}
    mapped = {mapping["control_id"] for mapping in context["mappings"]}
    return sorted(current | (extra & mapped))


def _ale(context: dict, extra: set[str], cache: dict) -> float:
    ids = tuple(_ids_for(context, extra))
    key = (context["scenario"]["scenario_id"], ids)
    if key not in cache:
        cache[key] = analytic_ale(context, list(ids))
    return cache[key]


def _combined_reduction(contexts, baseline: dict[str, float], extra: set[str], cache: dict) -> float:
    return sum(baseline[context["scenario"]["scenario_id"]] - _ale(context, extra, cache) for context in contexts)


def _optimise(candidates: list[dict], contexts, baseline, budget: float | None, cache: dict) -> dict:
    if budget is None:
        return {"method": "none", "reason": "Annual treatment budget is not defined", "selected": []}
    if not candidates:
        return {"method": "none", "reason": "No costed candidate controls", "selected": []}

    def cost_of(selected: list[dict]) -> float:
        return sum(candidate["annualised_cost"] for candidate in selected)

    if len(candidates) <= 16:
        best_key = None
        best = []
        for size in range(len(candidates) + 1):
            for combo in combinations(candidates, size):
                chosen = list(combo)
                cost = cost_of(chosen)
                if cost > budget:
                    continue
                reduction = _combined_reduction(contexts, baseline, {item["control_id"] for item in chosen}, cache)
                key = (-reduction, cost, tuple(sorted(item["control_id"] for item in chosen)))
                if best_key is None or key < best_key:
                    best_key = key
                    best = chosen
        return {"method": "exhaustive", "reason": None, "selected": best}

    selected = []
    remaining = list(candidates)
    while True:
        best = None
        best_rank = None
        for candidate in remaining:
            trial = selected + [candidate]
            if cost_of(trial) > budget:
                continue
            before = _combined_reduction(contexts, baseline, {item["control_id"] for item in selected}, cache)
            after = _combined_reduction(contexts, baseline, {item["control_id"] for item in trial}, cache)
            marginal = after - before
            if marginal <= 0:
                continue
            rank_cost = candidate["annualised_cost"]
            ratio = float("inf") if rank_cost == 0 else marginal / rank_cost
            rank = (-ratio, rank_cost, candidate["control_id"])
            if best_rank is None or rank < best_rank:
                best_rank = rank
                best = candidate
        if best is None:
            break
        selected.append(best)
        remaining.remove(best)
    return {"method": "greedy", "reason": None, "selected": selected}


def _reach(candidates, contexts, baseline, appetite, cache) -> dict:
    ale_limit = appetite["portfolio_ale_limit"]
    tolerance = appetite["scenario_ale_tolerance"]
    if ale_limit is None and tolerance is None:
        return {"computed": False, "achievable": False, "selected_control_ids": [], "total_annualised_cost": None, "within_budget": None}

    def satisfies(extra: set[str]) -> bool:
        ales = [_ale(context, extra, cache) for context in contexts]
        if ale_limit is not None and sum(ales) > ale_limit:
            return False
        if tolerance is not None and any(value > tolerance for value in ales):
            return False
        return True

    best = None
    best_key = None
    if len(candidates) <= 16:
        for size in range(len(candidates) + 1):
            for combo in combinations(candidates, size):
                chosen = list(combo)
                extra = {item["control_id"] for item in chosen}
                if not satisfies(extra):
                    continue
                cost = sum(item["annualised_cost"] for item in chosen)
                key = (cost, tuple(sorted(extra)))
                if best_key is None or key < best_key:
                    best_key = key
                    best = chosen
    achievable = best is not None
    selected = best or []
    cost = sum(item["annualised_cost"] for item in selected) if achievable else None
    budget = appetite["annual_treatment_budget"]
    return {
        "computed": True,
        "achievable": achievable,
        "selected_control_ids": [item["control_id"] for item in selected],
        "total_annualised_cost": cost,
        "within_budget": None if budget is None or cost is None else cost <= budget,
    }


def build_treatments(iterations: int, seed: int, register: dict | None = None) -> dict:
    register = register or build_register(iterations, seed, include_samples=True)
    appetite = register["appetite"]
    years = appetite["amortisation_years"] or 3
    contexts = [item["context"] for item in register["items"]]
    baseline = {item["scenario_id"]: item["analytic_ale"]["current"] for item in register["items"]}
    cache = {}
    for context in contexts:
        cache[(context["scenario"]["scenario_id"], tuple(_ids_for(context, set())))] = baseline[context["scenario"]["scenario_id"]]

    catalog = {}
    scenario_map = {}
    for context in contexts:
        for mapping in context["mappings"]:
            if mapping["status"] not in ("Planned", "Not Implemented"):
                continue
            catalog.setdefault(mapping["control_id"], mapping)
            scenario_map.setdefault(mapping["control_id"], []).append(context["scenario"]["scenario_id"])

    candidates = []
    unranked = []
    for control_id, mapping in sorted(catalog.items()):
        annualised = _annualised(mapping, years)
        per_scenario = []
        reduction = 0.0
        for context in contexts:
            if context["scenario"]["scenario_id"] not in scenario_map[control_id]:
                continue
            before = baseline[context["scenario"]["scenario_id"]]
            after = _ale(context, {control_id}, cache)
            per_scenario.append(
                {
                    "scenario_id": context["scenario"]["scenario_id"],
                    "ale_before": before,
                    "ale_after": after,
                    "reduction": before - after,
                }
            )
            reduction += before - after
        record = {
            "control_id": control_id,
            "control": mapping["control"],
            "status": mapping["status"],
            "control_type": mapping["control_type"],
            "scenario_ids": scenario_map[control_id],
            "implementation_cost": mapping["implementation_cost"],
            "annual_cost": mapping["annual_cost"],
            "annualised_cost": annualised,
            "cost_known": annualised is not None,
            "standalone_reduction": reduction,
            "per_scenario": per_scenario,
        }
        benefit, rosi, net = _ratios(reduction, annualised if annualised is not None else 0, annualised is not None)
        record["benefit_cost_ratio"] = benefit
        record["rosi"] = rosi
        record["net_benefit"] = net
        if annualised is None:
            unranked.append({"control_id": control_id, "control": mapping["control"], "reason": "cost unknown"})
        else:
            candidates.append(record)

    plan = _optimise(candidates, contexts, baseline, appetite["annual_treatment_budget"], cache)
    selected_ids = [item["control_id"] for item in plan["selected"]]
    selected_set = set(selected_ids)
    total_annualised = sum(item["annualised_cost"] for item in plan["selected"])
    total_first_year = sum((item["implementation_cost"] or 0) + (item["annual_cost"] or 0) for item in plan["selected"])
    expected_reduction = _combined_reduction(contexts, baseline, selected_set, cache) if contexts else 0.0
    residual = sum(baseline.values()) - expected_reduction

    recommended_samples = []
    for ordinal, context in enumerate(contexts):
        if not in_appetite_test(context["scenario"]["status"]):
            continue
        run = run_control_set(
            context,
            "custom",
            iterations,
            seed + ordinal,
            _ids_for(context, selected_set),
            return_samples=True,
        )
        recommended_samples.append(run["samples"])
    recommended_summary, _total, _aggregate = portfolio_from_samples(recommended_samples, iterations) if contexts else (
        {"mean": 0.0, "median": 0.0, "var_95": 0.0, "var_99": 0.0, "tvar_95": 0.0, "tvar_99": 0.0, "probability_of_loss_year": 0.0},
        None,
        None,
    )
    appetite_after = {
        "portfolio_ale": appetite_status(recommended_summary["mean"], appetite["portfolio_ale_limit"]),
        "portfolio_var_95": appetite_status(recommended_summary["var_95"], appetite["portfolio_var95_limit"]),
    }
    appetite_contexts = [context for context in contexts if in_appetite_test(context["scenario"]["status"])]
    reach = _reach(candidates, appetite_contexts, baseline, appetite, cache)
    if appetite["annual_treatment_budget"] is None and reach["computed"]:
        reach["within_budget"] = None

    by_scenario = []
    for item in register["items"]:
        options = []
        for candidate in candidates:
            match = next((row for row in candidate["per_scenario"] if row["scenario_id"] == item["scenario_id"]), None)
            if not match:
                continue
            options.append(
                {
                    "control_id": candidate["control_id"],
                    "control": candidate["control"],
                    "reduction": match["reduction"],
                    "annualised_cost": candidate["annualised_cost"],
                    "benefit_cost_ratio": None
                    if not candidate["annualised_cost"]
                    else match["reduction"] / candidate["annualised_cost"],
                }
            )
        options.sort(key=lambda option: (option["benefit_cost_ratio"] is None, -(option["benefit_cost_ratio"] or 0), option["control_id"]))
        by_scenario.append(
            {
                "scenario_id": item["scenario_id"],
                "scenario": item["scenario"],
                "current_ale": item["analytic_ale"]["current"],
                "tolerance": appetite["scenario_ale_tolerance"],
                "above_tolerance": item["above_tolerance"],
                "options": options,
            }
        )

    candidates.sort(key=lambda candidate: (candidate["benefit_cost_ratio"] is None, -(candidate["benefit_cost_ratio"] or 0), candidate["control_id"]))
    threshold = appetite["approval_threshold"]
    decisions = []
    for candidate in sorted((item for item in candidates if item["control_id"] in selected_set), key=lambda item: item["control_id"]):
        amount = (candidate["implementation_cost"] or 0) + (candidate["annual_cost"] or 0)
        decisions.append(_decision(
            f"INVEST-{candidate['control_id']}",
            "Invest",
            candidate["control"],
            amount,
            threshold,
            f"Expected annual loss reduction {candidate['standalone_reduction']:.0f}; "
            f"benefit-cost ratio {_ratio_text(candidate['benefit_cost_ratio'])}; scenarios {', '.join(candidate['scenario_ids'])}.",
            [candidate["control_id"], *candidate["scenario_ids"]],
        ))
    for row in by_scenario:
        source = next(item for item in register["items"] if item["scenario_id"] == row["scenario_id"])
        if not source["in_appetite_test"]:
            continue
        residual_ale = _ale(next(context for context in contexts if context["scenario"]["scenario_id"] == row["scenario_id"]), selected_set, cache) if contexts else 0
        above = appetite["scenario_ale_tolerance"] is not None and residual_ale > appetite["scenario_ale_tolerance"]
        if above or (appetite["scenario_ale_tolerance"] is not None and not selected_ids and row["above_tolerance"]):
            decisions.append(_decision(
                f"ACCEPT-{row['scenario_id']}",
                "Accept",
                row["scenario"],
                residual_ale,
                threshold,
                "Residual expected annual loss remains above the scenario tolerance after the recommended plan.",
                [row["scenario_id"]],
            ))
    if appetite_after["portfolio_ale"]["status"] == "Breached" or appetite_after["portfolio_var_95"]["status"] == "Breached":
        excesses = []
        for metric in (appetite_after["portfolio_ale"], appetite_after["portfolio_var_95"]):
            if metric["status"] == "Breached":
                excesses.append(metric["value"] - metric["limit"])
        decisions.append(_decision(
            "ESCALATE-PORTFOLIO",
            "Escalate",
            "Portfolio risk appetite",
            max(excesses) if excesses else 0,
            threshold,
            "Portfolio exposure remains above appetite after the recommended plan.",
            [],
        ))
    incomplete = [item for item in register["items"] if not item["data_quality"]["complete"]]
    if incomplete:
        units = organisational_unit_names()
        gap_lines = []
        for item in incomplete:
            names = gap_names(item["context"], units)
            for gap in item["data_quality"]["gaps"]:
                gap_lines.append(data_gap_bullet(item["scenario_id"], gap, names))
        decisions.append({
            "decision_id": "DATA-GAPS",
            "type": "Data Gap",
            "subject": "Incomplete quantitative anchors",
            "amount": None,
            "approval_level": "Management",
            "rationale": "\n".join(gap_lines),
            "related_ids": [item["scenario_id"] for item in incomplete],
        })
    for candidate in sorted(candidates, key=lambda item: item["control_id"]):
        if candidate["control_id"] in selected_set:
            continue
        decisions.append({
            "decision_id": f"DEFER-{candidate['control_id']}",
            "type": "Defer",
            "subject": candidate["control"],
            "amount": (candidate["implementation_cost"] or 0) + (candidate["annual_cost"] or 0),
            "approval_level": None,
            "rationale": "Not selected under the current treatment budget.",
            "related_ids": [candidate["control_id"]],
        })

    current_portfolio = register["portfolio"]["current"]
    return {
        "iterations": iterations,
        "seed": seed,
        "independence_note": INDEPENDENCE_NOTE,
        "appetite": {
            "defined": appetite["defined"],
            "statement": appetite["statement"],
            "limits": {key: appetite[key] for key in (
                "portfolio_ale_limit", "portfolio_var95_limit", "scenario_ale_tolerance",
                "annual_treatment_budget", "approval_threshold", "amortisation_years",
            )},
            "evaluation": register["evaluation"],
        },
        "baseline": {
            "control_set": "current",
            "analytic_ale": sum(baseline.values()) if baseline else 0.0,
            "simulated": {
                "mean": current_portfolio["mean"],
                "var_95": current_portfolio["var_95"],
                "tvar_95": current_portfolio["tvar_95"],
                "probability_of_loss_year": current_portfolio["probability_of_loss_year"],
            },
        },
        "candidates": candidates,
        "unranked": unranked,
        "recommendation": {
            "method": plan["method"],
            "budget": appetite["annual_treatment_budget"],
            "reason": plan["reason"],
            "selected_control_ids": selected_ids,
            "total_annualised_cost": total_annualised,
            "total_first_year_cost": total_first_year,
            "expected_reduction": expected_reduction,
            "residual_analytic_ale": residual,
            "simulated": {
                "mean": recommended_summary["mean"],
                "var_95": recommended_summary["var_95"],
                "tvar_95": recommended_summary["tvar_95"],
                "probability_of_loss_year": recommended_summary["probability_of_loss_year"],
            },
            "appetite_after": appetite_after,
            "samples": recommended_samples,
        },
        "reach_appetite": reach,
        "by_scenario": by_scenario,
        "decisions": decisions,
        "register": register,
    }


def _ratio_text(value) -> str:
    return "N/A" if value is None else f"{value:.2f}"


def _decision(decision_id, kind, subject, amount, threshold, rationale, related) -> dict:
    if threshold is None or (amount is not None and amount >= threshold):
        level = "Committee"
    else:
        level = "Management"
    return {
        "decision_id": decision_id,
        "type": kind,
        "subject": subject,
        "amount": amount,
        "approval_level": level,
        "rationale": rationale,
        "related_ids": related,
    }
