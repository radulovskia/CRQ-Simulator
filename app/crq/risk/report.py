import hashlib
from datetime import datetime, timezone

from crq.catalog.catalog_io import connect
from crq.risk.benchmarks import benchmarks_version
from crq.risk.decisions import canonical
from crq.risk.treatment import build_treatments
from crq.version import INDEPENDENCE_NOTE, MODEL_VERSION
from crq.intelligence.vulnerabilities import connect as connect_findings

def assumptions_for(version: str) -> list[str]:
    return [
        INDEPENDENCE_NOTE,
        "Controls combine multiplicatively; frequency reductions act on susceptibility, magnitude reductions on all loss forms.",
        "Treatment selection maximises expected (analytic) annual loss reduction; tail metrics are simulated.",
        f"Benchmark constants version {version} drive suggestions only; stored scenario values are analyst estimates.",
        "Beta-PERT inputs with per-scenario lambdas; compound Poisson loss events; secondary loss conditional on SLP.",
    ]


ASSUMPTIONS = assumptions_for("2026.10")

TABLES = {
    "units": "SELECT * FROM organisational_units ORDER BY ou_id",
    "systems": "SELECT * FROM software_systems ORDER BY system_id",
    "processes": "SELECT * FROM business_processes ORDER BY bp_id",
    "process_systems": "SELECT bp_id, system_id FROM process_systems ORDER BY bp_id, system_id",
    "components": "SELECT * FROM software_components ORDER BY component_id",
    "actors": "SELECT * FROM threat_actors ORDER BY actor_id",
    "vectors": "SELECT * FROM attack_vectors ORDER BY vector_id",
    "controls": "SELECT * FROM controls ORDER BY control_id",
    "scenarios": "SELECT * FROM risk_scenarios ORDER BY scenario_id",
    "scenario_controls": "SELECT * FROM scenario_controls ORDER BY scenario_id, control_id",
}


def _amount(value: float | None) -> str:
    if value is None:
        return "n/a"
    sign = "-" if value < 0 else ""
    amount = abs(value)
    if amount >= 1_000_000:
        return f"{sign}{amount / 1_000_000:.2f}M"
    if amount >= 1_000:
        return f"{sign}{amount / 1_000:.1f}k"
    return f"{sign}{amount:.0f}"


def _rows(connection, sql: str) -> list[dict]:
    rows = []
    for row in connection.execute(sql).fetchall():
        item = {}
        for key, value in dict(row).items():
            item[key] = value.isoformat() if hasattr(value, "isoformat") else value
        rows.append(item)
    return rows


def _digest(rows: list[dict]) -> dict:
    return {"rows": len(rows), "sha256": hashlib.sha256(canonical(rows).encode()).hexdigest()}


def snapshot_inputs() -> tuple[dict, dict, str | None]:
    inputs = {}
    with connect() as connection:
        for name, sql in TABLES.items():
            inputs[name] = _rows(connection, sql)
        appetite = connection.execute("SELECT * FROM risk_appetite WHERE id = 1").fetchone()
        inputs["risk_appetite"] = []
        if appetite:
            item = {key: value.isoformat() if hasattr(value, "isoformat") else value for key, value in dict(appetite).items()}
            inputs["risk_appetite"] = [item]
    with connect_findings() as connection:
        inputs["findings"] = _rows(connection, "SELECT * FROM findings ORDER BY system_id, purl, vuln_id")
        meta = connection.execute("SELECT extracted_at, kev_checked_at FROM vulnerability_meta WHERE id = 1").fetchone()
    kev_checked_at = meta["kev_checked_at"].isoformat() if meta and meta["kev_checked_at"] else None
    inputs["kev_checked_at"] = kev_checked_at
    digest = {name: _digest(rows if isinstance(rows, list) else []) for name, rows in inputs.items() if name != "kev_checked_at"}
    return inputs, digest, kev_checked_at


def _public_item(item: dict, collapsed_current: dict | None = None) -> dict:
    payload = {key: value for key, value in item.items() if key not in ("context", "runs")}
    return payload


def build_report(iterations: int, seed: int, treatments: dict | None = None) -> dict:
    treatments = treatments or build_treatments(iterations, seed)
    register = treatments["register"]
    _inputs, digest, kev_checked_at = snapshot_inputs()
    portfolio = {}
    for name in ("inherent", "current", "target"):
        portfolio[name] = register["portfolio"][name]
    portfolio["recommended"] = {
        "mean": treatments["recommendation"]["simulated"]["mean"],
        "median": None,
        "var_95": treatments["recommendation"]["simulated"]["var_95"],
        "var_99": None,
        "tvar_95": treatments["recommendation"]["simulated"]["tvar_95"],
        "tvar_99": None,
        "probability_of_loss_year": treatments["recommendation"]["simulated"]["probability_of_loss_year"],
    }
    curves = {
        "current": register["curves"].get("current", []),
        "recommended": _recommended_curve(treatments, iterations),
    }
    scenarios = []
    for item in register["items"]:
        current_run = item["runs"]["current"]
        scenarios.append(
            {
                **_public_item(item),
                "above_tolerance": item["above_tolerance"],
                "data_quality": item["data_quality"],
                "worksheet": {
                    "lef": {
                        "minimum": current_run["collapsed"]["frequency"][0],
                        "mode": current_run["collapsed"]["frequency"][1],
                        "maximum": current_run["collapsed"]["frequency"][2],
                    },
                    "magnitude": {
                        "minimum": current_run["collapsed"]["magnitude"][0],
                        "mode": current_run["collapsed"]["magnitude"][1],
                        "maximum": current_run["collapsed"]["magnitude"][2],
                    },
                    "applied_control_ids": current_run["summary"]["applied_control_ids"],
                },
            }
        )
    current = register["portfolio"]["current"]
    inherent = register["portfolio"]["inherent"]
    reduction = 0 if not inherent["mean"] else 100 * (1 - current["mean"] / inherent["mean"])
    appetite_status = register["evaluation"]["portfolio_ale"]["status"]
    selected = ", ".join(treatments["recommendation"]["selected_control_ids"]) or "none"
    narrative = {
        "headline": (
            f"Current expected annual cyber loss is {_amount(current['mean'])} "
            f"(1-in-20-year loss {_amount(current['var_95'])}), {reduction:.0f}% below inherent exposure."
        ),
        "exposure": f"Inherent expected loss is {_amount(inherent['mean'])}. Target-state expected loss is {_amount(register['portfolio']['target']['mean'])}.",
        "appetite": f"Portfolio appetite status is {appetite_status}.",
        "treatment": (
            f"Recommended controls: {selected}.\n"
            f"Expected reduction {_amount(treatments['recommendation']['expected_reduction'])} "
            f"at annualised cost {_amount(treatments['recommendation']['total_annualised_cost'])}."
        ),
        "decisions": f"{sum(1 for item in treatments['decisions'] if item['approval_level'] == 'Committee')} decisions require committee approval.",
    }
    catalog_times = _catalog_times()
    version = benchmarks_version()
    return {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "model_version": MODEL_VERSION,
            "benchmarks_version": version,
            "seed": seed,
            "iterations": iterations,
            "record_id": None,
            "content_hash": None,
            "status": "Draft",
        },
        "narrative": narrative,
        "appetite": treatments["appetite"],
        "portfolio": {
            "independence_note": INDEPENDENCE_NOTE,
            **portfolio,
            "exceedance_curves": curves,
        },
        "scenarios": scenarios,
        "treatments": _public_treatments(treatments),
        "decisions": treatments["decisions"],
        "assumptions": assumptions_for(version),
        "data_quality": {
            "scenarios_with_gaps": [
                {"scenario_id": item["scenario_id"], "gaps": item["data_quality"]["gaps"]}
                for item in register["items"]
                if not item["data_quality"]["complete"]
            ],
            "catalog_extracted_at": catalog_times,
            "kev_checked_at": kev_checked_at,
        },
        "inputs_digest": digest,
    }


def _recommended_curve(treatments: dict, iterations: int) -> list[dict]:
    from crq.risk.monte_carlo import _build_exceedance_curve
    import numpy as np

    samples = treatments["recommendation"].get("samples") or []
    total = np.zeros(iterations) if not samples else np.sum(np.vstack(samples), axis=0)
    curve = _build_exceedance_curve(total)
    return [{"loss": point.loss, "exceedance_probability": point.exceedance_probability} for point in curve.points]


def _catalog_times() -> dict:
    queries = {
        "units": "organisational_unit_meta",
        "systems": "software_system_meta",
        "processes": "business_process_meta",
        "components": "software_component_meta",
        "actors": "threat_actor_meta",
        "vectors": "attack_vector_meta",
        "controls": "control_meta",
        "scenarios": "risk_scenario_meta",
        "scenario_controls": "scenario_control_meta",
    }
    times = {}
    with connect() as connection:
        for name, table in queries.items():
            row = connection.execute(f"SELECT extracted_at FROM {table} WHERE id = 1").fetchone()
            times[name] = row["extracted_at"].isoformat() if row else None
    with connect_findings() as connection:
        row = connection.execute("SELECT extracted_at FROM vulnerability_meta WHERE id = 1").fetchone()
        times["findings"] = row["extracted_at"].isoformat() if row else None
    return times


def _public_treatments(treatments: dict) -> dict:
    recommendation = {key: value for key, value in treatments["recommendation"].items() if key != "samples"}
    return {
        "baseline": treatments["baseline"],
        "candidates": treatments["candidates"],
        "unranked": treatments["unranked"],
        "recommendation": recommendation,
        "reach_appetite": treatments["reach_appetite"],
        "by_scenario": treatments["by_scenario"],
    }


def public_treatments(treatments: dict) -> dict:
    body = _public_treatments(treatments)
    body.update(
        {
            "iterations": treatments["iterations"],
            "seed": treatments["seed"],
            "independence_note": treatments["independence_note"],
            "appetite": treatments["appetite"],
            "decisions": treatments["decisions"],
        }
    )
    return body
