"""FAIR factor suggestions, control application, and collapse to simulator inputs.

Suggestions read the benchmark row from Settings. Until that row is saved, the
code defaults apply. Stored scenario values are the analyst's estimates.
"""

from math import floor, log10

from crq.catalog.catalog_io import connect
from crq.risk.benchmarks import active_benchmarks
from crq.intelligence.vulnerabilities import connect as connect_findings

CLASS_ORDER = ("Public", "Internal", "Confidential")
CRIT_ORDER = ("Low", "Medium", "High")
PRIMARY = ("response", "replacement", "productivity")
SECONDARY = ("fines", "reputation", "competitive")
FORM_PREFIX = {
    "response": "response",
    "replacement": "replacement",
    "productivity": "productivity",
    "fines": "fines",
    "reputation": "reputation",
    "competitive": "competitive",
}


def significant(value: float, digits: int = 3) -> float:
    if value == 0:
        return 0.0
    power = digits - 1 - floor(log10(abs(value)))
    return float(round(value, power))


def round_money(triple: tuple[float, float, float]) -> tuple[float, float, float]:
    lowest, mode, highest = (significant(value) for value in triple)
    mode = min(max(mode, lowest), highest)
    if highest < mode:
        highest = mode
    if lowest == highest and triple[0] != triple[2]:
        highest = significant(triple[2])
        if highest <= lowest:
            highest = lowest + abs(lowest) * 0.01 or 1
    return (lowest, mode, highest)


def round_rate(value: float) -> float:
    return round(float(value), 3)


def round_rate_triple(triple: tuple[float, float, float]) -> tuple[float, float, float]:
    lowest, mode, highest = (min(1.0, round_rate(value)) for value in triple)
    mode = min(max(mode, lowest), highest)
    return (lowest, mode, highest)


def pert_mean(triple: tuple[float, float, float], lambda_param: float) -> float:
    return (triple[0] + lambda_param * triple[1] + triple[2]) / (lambda_param + 2)


def _highest(records: list[dict], key: str, order: tuple[str, ...]) -> str | None:
    if not records:
        return None
    rank = {name: index for index, name in enumerate(order)}
    return max(records, key=lambda record: rank.get(record.get(key), -1)).get(key)


def _triple(row: dict, prefix: str) -> tuple[float, float, float]:
    return (float(row[f"{prefix}_min"]), float(row[f"{prefix}_mode"]), float(row[f"{prefix}_max"]))


def _scale(triple: tuple[float, float, float], factor: float) -> tuple[float, float, float]:
    return tuple(value * factor for value in triple)


def load_scenario_context(scenario_id: str) -> dict | None:
    with connect() as connection:
        scenario = connection.execute(
            "SELECT * FROM risk_scenarios WHERE scenario_id = %s", (scenario_id,)
        ).fetchone()
        if not scenario:
            return None
        return _context_from(connection, dict(scenario))


def build_target_context(actor_id: str, vector_id: str, target_type: str, target_id: str) -> dict | None:
    with connect() as connection:
        actor = connection.execute("SELECT * FROM threat_actors WHERE actor_id = %s", (actor_id,)).fetchone()
        vector = connection.execute("SELECT * FROM attack_vectors WHERE vector_id = %s", (vector_id,)).fetchone()
        if not actor or not vector:
            return None
        systems, processes = _affected(connection, target_type, target_id)
        if target_type == "Software System" and not systems:
            return None
        if target_type == "Business Process" and not processes:
            return None
        shell = {
            "scenario_id": None,
            "threat_actor_id": actor_id,
            "attack_vector_id": vector_id,
            "target_type": target_type,
            "target_id": target_id,
        }
        context = _context_from(connection, shell, actor=dict(actor), vector=dict(vector), systems=systems, processes=processes)
        return context


def _affected(connection, target_type: str, target_id: str) -> tuple[list[dict], list[dict]]:
    systems = {
        row["system_id"]: dict(row)
        for row in connection.execute("SELECT * FROM software_systems").fetchall()
    }
    processes = []
    by_id = {}
    for row in connection.execute(
        """
        SELECT p.*, ps.system_id AS linked_system_id
        FROM business_processes p
        LEFT JOIN process_systems ps ON ps.bp_id = p.bp_id
        ORDER BY p.bp_id, ps.system_id
        """
    ).fetchall():
        item = dict(row)
        system_id = item.pop("linked_system_id")
        current = by_id.get(item["bp_id"])
        if current is None:
            item["system_ids"] = []
            by_id[item["bp_id"]] = item
            processes.append(item)
            current = item
        if system_id:
            current["system_ids"].append(system_id)
    units = {
        row["ou_id"]: row["loaded_hourly_cost"]
        for row in connection.execute("SELECT ou_id, loaded_hourly_cost, headcount FROM organisational_units")
    }
    headcounts = {
        row["ou_id"]: row["headcount"]
        for row in connection.execute("SELECT ou_id, headcount FROM organisational_units")
    }
    if target_type == "Software System":
        if target_id not in systems:
            return [], []
        chosen_systems = [systems[target_id]]
        chosen_processes = [process for process in processes if target_id in process["system_ids"]]
    elif target_type == "Business Process":
        match = next((process for process in processes if process["bp_id"] == target_id), None)
        if not match:
            return [], []
        chosen_processes = [match]
        chosen_systems = [systems[system_id] for system_id in match["system_ids"] if system_id in systems]
    else:
        return [], []
    for process in chosen_processes:
        process["ou_hourly_cost"] = units.get(process["ou_id"])
        process["ou_headcount"] = headcounts.get(process["ou_id"])
    return chosen_systems, chosen_processes


def _context_from(connection, scenario: dict, actor=None, vector=None, systems=None, processes=None) -> dict:
    if actor is None:
        actor = dict(connection.execute(
            "SELECT * FROM threat_actors WHERE actor_id = %s", (scenario["threat_actor_id"],)
        ).fetchone())
    if vector is None:
        vector = dict(connection.execute(
            "SELECT * FROM attack_vectors WHERE vector_id = %s", (scenario["attack_vector_id"],)
        ).fetchone())
    if systems is None or processes is None:
        systems, processes = _affected(connection, scenario["target_type"], scenario["target_id"])
    system_ids = [system["system_id"] for system in systems]
    component_counts = {system_id: 0 for system_id in system_ids}
    if system_ids:
        for row in connection.execute(
            "SELECT system_id, COUNT(*) AS count FROM software_components WHERE system_id = ANY(%s) GROUP BY system_id",
            (system_ids,),
        ):
            component_counts[row["system_id"]] = row["count"]
    mappings = []
    if scenario.get("scenario_id"):
        mappings = [
            dict(row)
            for row in connection.execute(
                """
                SELECT m.scenario_id, m.control_id, m.frequency_reduction_override_pct,
                       m.magnitude_reduction_override_pct, m.eliminates_risk, m.rationale,
                       c.control, c.status, c.reduces, c.frequency_reduction_pct, c.magnitude_reduction_pct,
                       c.annual_cost, c.implementation_cost, c.control_type
                FROM scenario_controls m
                JOIN controls c ON c.control_id = m.control_id
                WHERE m.scenario_id = %s
                ORDER BY m.control_id
                """,
                (scenario["scenario_id"],),
            )
        ]
    names = {}
    if scenario["target_type"] == "Software System":
        names["target_name"] = systems[0]["software_system"] if systems else ""
    else:
        names["target_name"] = processes[0]["business_process"] if processes else ""
    owner = connection.execute(
        "SELECT organisational_unit FROM organisational_units WHERE ou_id = %s",
        (scenario.get("risk_owner_ou_id"),),
    ).fetchone()
    findings_by_system, extracted_at, kev_checked_at = _findings(system_ids)
    return {
        "scenario": scenario,
        "actor": actor,
        "vector": vector,
        "systems": systems,
        "processes": processes,
        "mappings": mappings,
        "component_counts": component_counts,
        "findings_by_system": findings_by_system,
        "findings_extracted_at": extracted_at,
        "kev_checked_at": kev_checked_at,
        "target_name": names["target_name"],
        "risk_owner_ou": owner["organisational_unit"] if owner else "",
        "threat_actor": actor.get("threat_actor", ""),
        "attack_vector": vector.get("attack_vector", ""),
    }


def _findings(system_ids: list[str]) -> tuple[dict, str | None, str | None]:
    grouped = {system_id: [] for system_id in system_ids}
    with connect_findings() as connection:
        meta = connection.execute("SELECT extracted_at, kev_checked_at FROM vulnerability_meta WHERE id = 1").fetchone()
        if system_ids:
            rows = connection.execute(
                """
                SELECT system_id, cvss_score, epss, known_exploited
                FROM findings
                WHERE system_id = ANY(%s)
                """,
                (system_ids,),
            ).fetchall()
            for row in rows:
                if row["system_id"] in grouped:
                    grouped[row["system_id"]].append(dict(row))
    extracted = meta["extracted_at"].isoformat() if meta else None
    kev = meta["kev_checked_at"].isoformat() if meta and meta["kev_checked_at"] else None
    return grouped, extracted, kev


def _stats(rows: list[dict], kev_known: bool) -> dict:
    cvss = [row["cvss_score"] for row in rows if row["cvss_score"] is not None]
    epss = [row["epss"] for row in rows if row["epss"] is not None]
    return {
        "count": len(rows),
        "high": sum(1 for row in rows if row["cvss_score"] is not None and row["cvss_score"] >= 7),
        "critical": sum(1 for row in rows if row["cvss_score"] is not None and row["cvss_score"] >= 9),
        "max_cvss": max(cvss) if cvss else None,
        "max_epss": max(epss) if epss else None,
        "kev": sum(1 for row in rows if row["known_exploited"] is True),
        "kev_known": kev_known,
    }


def exposure_summary(context: dict) -> dict:
    kev_known = context["kev_checked_at"] is not None
    systems = []
    for system in context["systems"]:
        systems.append(
            {
                "system_id": system["system_id"],
                "software_system": system["software_system"],
                "criticality": system["criticality"],
                "data_classification": system["data_classification"],
                "deployment": system["deployment"],
                "internet_facing": system["internet_facing"],
                "replacement_cost": system["replacement_cost"],
                "records_held": system["records_held"],
                "component_count": context["component_counts"].get(system["system_id"], 0),
                "findings": _stats(context["findings_by_system"].get(system["system_id"], []), kev_known),
            }
        )
    processes = [
        {
            "bp_id": process["bp_id"],
            "business_process": process["business_process"],
            "criticality": process["criticality"],
            "downtime_cost_per_hour": process["downtime_cost_per_hour"],
            "downtime_cost_per_hour_post_rto": process.get("downtime_cost_per_hour_post_rto"),
            "rto_hours": process["rto_hours"],
            "fte_count": process["fte_count"],
            "ou_hourly_cost": process.get("ou_hourly_cost"),
        }
        for process in context["processes"]
    ]
    return {"systems": systems, "processes": processes, "data_gaps": data_gaps(context)}


def data_gaps(context: dict) -> list[str]:
    gaps = []
    for system in context["systems"]:
        if system["replacement_cost"] is None:
            gaps.append(f"{system['system_id']}: Replacement Cost unknown")
        if system["records_held"] is None:
            gaps.append(f"{system['system_id']}: Records Held unknown")
        if system["internet_facing"] == "Unknown":
            gaps.append(f"{system['system_id']}: Internet Facing unknown")
        if context["component_counts"].get(system["system_id"], 0) == 0:
            gaps.append(f"{system['system_id']}: no software components inventoried")
    seen_ous = set()
    for process in context["processes"]:
        if process["downtime_cost_per_hour"] is None:
            gaps.append(f"{process['bp_id']}: Downtime Cost per Hour before Recovery Time Objective unknown")
        if process["rto_hours"] is None:
            gaps.append(f"{process['bp_id']}: Recovery Time Objective unknown")
        if process["fte_count"] is None:
            gaps.append(f"{process['bp_id']}: Full-Time Equivalent Count unknown")
        ou_id = process["ou_id"]
        if ou_id not in seen_ous:
            seen_ous.add(ou_id)
            if process.get("ou_headcount") is None:
                gaps.append(f"{ou_id}: Headcount unknown")
            if process.get("ou_hourly_cost") is None:
                gaps.append(f"{ou_id}: Loaded Hourly Cost unknown")
    if context["scenario"]["target_type"] == "Software System" and not context["processes"]:
        gaps.append(f"No business process lists {context['scenario']['target_id']} as a primary system")
    if context["scenario"]["target_type"] == "Business Process" and not context["systems"]:
        gaps.append(f"{context['scenario']['target_id']}: no primary systems")
    finding_rows = [row for rows in context["findings_by_system"].values() for row in rows]
    if finding_rows and context["kev_checked_at"] is None:
        gaps.append("Known Exploited Vulnerability status unknown (feed unavailable at last scan)")
    return gaps


_GAP_DETAILS = {
    "Replacement Cost unknown": "Replacement Cost",
    "Records Held unknown": "Records Held",
    "Internet Facing unknown": "Internet Facing",
    "no software components inventoried": "Software Components",
    "Downtime Cost per Hour before Recovery Time Objective unknown": "Downtime Cost per Hour before RTO",
    "Recovery Time Objective unknown": "Recovery Time Objective",
    "Full-Time Equivalent Count unknown": "Full-Time Equivalent Count",
    "Headcount unknown": "Headcount",
    "Loaded Hourly Cost unknown": "Loaded Hourly Cost",
    "no primary systems": "primary systems",
}


def organisational_unit_names() -> dict[str, str]:
    with connect() as connection:
        return {
            row["ou_id"]: row["organisational_unit"]
            for row in connection.execute("SELECT ou_id, organisational_unit FROM organisational_units")
        }


def gap_names(context: dict, units: dict[str, str] | None = None) -> dict[str, str]:
    names = dict(units or {})
    for system in context.get("systems") or []:
        names[system["system_id"]] = system.get("software_system") or ""
    for process in context.get("processes") or []:
        names[process["bp_id"]] = process.get("business_process") or ""
    return names


def data_gap_bullet(scenario_id: str, gap: str, names: dict[str, str]) -> str:
    if gap.startswith("No business process lists ") and gap.endswith(" as a primary system"):
        entity = gap[len("No business process lists "):-len(" as a primary system")]
        return (
            f"* {scenario_id}: Data Gap identified in {_named(entity, names)}, "
            "missing a business process that lists it as a primary system."
        )
    if gap.startswith("Known Exploited Vulnerability status unknown"):
        return f"* {scenario_id}: Data Gap identified in the vulnerability findings, missing Known Exploited Vulnerability status."
    if ": " in gap:
        entity, detail = gap.split(": ", 1)
        missing = _GAP_DETAILS.get(detail, detail.removesuffix(" unknown"))
        return f"* {scenario_id}: Data Gap identified in {_named(entity, names)}, missing {missing}."
    return f"* {scenario_id}: Data Gap identified: {gap}."


def _named(entity: str, names: dict[str, str]) -> str:
    name = str(names.get(entity) or "").strip()
    if name:
        return f"{entity} - {name}"
    return entity


def data_quality(context: dict) -> dict:
    scenario = context["scenario"]
    gaps = data_gaps(context)
    basis = {
        "tef": scenario.get("tef_basis"),
        "susceptibility": scenario.get("susceptibility_basis"),
        "magnitude": scenario.get("magnitude_basis"),
    }
    return {
        "gaps": gaps,
        "complete": not gaps,
        "basis": basis,
        "expert_only": all(value == "Expert" for value in basis.values()),
        "findings_extracted_at": context["findings_extracted_at"],
        "kev_known": context["kev_checked_at"] is not None,
    }


def _missing(*gaps: str) -> dict:
    present = [gap for gap in gaps if gap]
    return {"available": False, "missing": present, "rationale": "Insufficient data: " + "; ".join(present)}


def _triple_ok(values: tuple[float, float, float], rationale: str, *, money: bool = True) -> dict:
    lowest, mode, highest = round_money(values) if money else round_rate_triple(values)
    return {"available": True, "minimum": lowest, "mode": mode, "maximum": highest, "rationale": rationale}


def _value_ok(value, rationale: str) -> dict:
    return {"available": True, "value": value, "rationale": rationale}


def _productivity_loss(processes: list[dict], hours: tuple[float, float, float]) -> tuple[float, float, float]:
    totals = [0.0, 0.0, 0.0]
    for process in processes:
        pre = process["downtime_cost_per_hour"]
        post = process["downtime_cost_per_hour_post_rto"]
        if post is None:
            post = pre
        rto = process["rto_hours"]
        labour = process["fte_count"] * process["ou_hourly_cost"]
        for index, duration in enumerate(hours):
            before = min(duration, rto)
            after = max(duration - rto, 0.0)
            totals[index] += before * pre + after * post + duration * labour
    return tuple(totals)


def suggest_factors(context: dict) -> dict:
    benchmarks = active_benchmarks()
    actor = context["actor"]
    vector = context["vector"]
    systems = context["systems"]
    processes = context["processes"]
    loss = vector["loss_event_type"]
    gaps = set(data_gaps(context))

    facing_gaps = [f"{system['system_id']}: Internet Facing unknown" for system in systems if system["internet_facing"] == "Unknown"]
    if vector["requires_internet_facing"] == "Yes" and facing_gaps:
        tef = _missing(*facing_gaps)
    else:
        exposed = any(system["internet_facing"] == "Yes" for system in systems)
        reach = benchmarks["reachability_unexposed"] if vector["requires_internet_facing"] == "Yes" and not exposed else 1.0
        multiplier = benchmarks["targeting_multiplier"][actor["sector_targeting"]]
        base = _triple(vector, "base_tef")
        tef = _triple_ok(
            tuple(value * multiplier * reach for value in base),
            f"Base threat event frequency scaled by sector targeting {actor['sector_targeting']} ({multiplier}) and reachability {reach}.",
        )

    component_gaps = [
        f"{system['system_id']}: no software components inventoried"
        for system in systems
        if context["component_counts"].get(system["system_id"], 0) == 0
    ]
    if vector["requires_vulnerability"] == "Yes" and component_gaps:
        susceptibility = _missing(*component_gaps)
    else:
        factor, detail = _evidence_factor(context, vector, benchmarks["evidence_factor"])
        base_s = _triple(vector, "base_susceptibility")
        scaled = (base_s[0] * factor, min(1, base_s[1] * factor), min(1, base_s[2] * factor))
        if scaled[1] > scaled[2]:
            scaled = (scaled[0], scaled[2], scaled[2])
        susceptibility = _triple_ok(scaled, detail, money=False)

    if loss in ("Fraud", "Confidentiality"):
        cap_value = benchmarks["cap"][loss]
        cap = _value_ok(cap_value, f"Default annual cap for {loss} loss events.")
    elif not processes:
        cap = _missing(f"No business process lists {context['scenario']['target_id']} as a primary system")
    else:
        criticality = _highest(processes, "criticality", CRIT_ORDER)
        cap_value = benchmarks["cap"][loss][criticality]
        cap = _value_ok(cap_value, f"Cap for {loss} against {criticality} process criticality.")

    productivity_gaps = []
    if not processes:
        productivity_gaps.append(f"No business process lists {context['scenario']['target_id']} as a primary system")
    for process in processes:
        if process["downtime_cost_per_hour"] is None:
            productivity_gaps.append(f"{process['bp_id']}: Downtime Cost per Hour before Recovery Time Objective unknown")
        if process["rto_hours"] is None:
            productivity_gaps.append(f"{process['bp_id']}: Recovery Time Objective unknown")
        if process["fte_count"] is None:
            productivity_gaps.append(f"{process['bp_id']}: Full-Time Equivalent Count unknown")
        if process.get("ou_hourly_cost") is None:
            productivity_gaps.append(f"{process['ou_id']}: Loaded Hourly Cost unknown")
    if productivity_gaps:
        productivity = _missing(*productivity_gaps)
    else:
        hours = _triple(vector, "outage_hours")
        productivity = _triple_ok(
            _productivity_loss(processes, hours),
            "Outage hours up to each process recovery time objective use the before-objective downtime cost; later hours use the post-objective cost. Staff cost applies for the whole outage.",
        )

    replacement_gaps = [f"{system['system_id']}: Replacement Cost unknown" for system in systems if system["replacement_cost"] is None]
    if not systems:
        replacement = _missing(f"{context['scenario']['target_id']}: no primary systems")
    elif replacement_gaps:
        replacement = _missing(*replacement_gaps)
    else:
        total = sum(system["replacement_cost"] for system in systems)
        fraction = benchmarks["replacement_fraction"][loss]
        replacement = _triple_ok(
            tuple(total * part for part in fraction),
            f"Replacement cost ¤ {significant(total)} times the {loss} fraction.",
        )

    classification = _highest(systems, "data_classification", CLASS_ORDER)
    if loss == "Confidentiality" and classification is None:
        response = _missing(f"{context['scenario']['target_id']}: no primary systems")
    elif loss == "Confidentiality":
        response = _triple_ok(benchmarks["response"]["Confidentiality"][classification], f"Response benchmark for {classification} data.")
    else:
        response = _triple_ok(benchmarks["response"][loss], f"Response benchmark for {loss}.")

    if loss == "Confidentiality" and classification is None:
        slp = _missing(f"{context['scenario']['target_id']}: no primary systems")
    elif loss == "Confidentiality":
        slp = _value_ok(benchmarks["secondary_loss_probability"]["Confidentiality"][classification], f"Secondary-loss probability for {classification} data.")
    elif loss == "Availability":
        unknown_facing = [gap for gap in facing_gaps if gap in gaps or True]
        any_yes = any(system["internet_facing"] == "Yes" for system in systems)
        if unknown_facing and not any_yes:
            slp = _missing(*unknown_facing)
        else:
            high = any(process["criticality"] == "High" for process in processes) and any_yes
            value = benchmarks["secondary_loss_probability"]["Availability"]["exposed_high" if high else "other"]
            slp = _value_ok(value, "Secondary-loss probability for an availability event.")
    else:
        slp = _value_ok(benchmarks["secondary_loss_probability"][loss], f"Secondary-loss probability for {loss}.")

    record_gaps = [f"{system['system_id']}: Records Held unknown" for system in systems if system["records_held"] is None]
    if classification == "Confidential" and loss != "Fraud":
        if record_gaps:
            fines = _missing(*record_gaps)
        elif not systems:
            fines = _missing(f"{context['scenario']['target_id']}: no primary systems")
        else:
            records = sum(system["records_held"] for system in systems)
            rates = benchmarks["fine_per_record"][loss]
            fines = _triple_ok(
                tuple(min(records * rate, benchmarks["fine_cap"]) for rate in rates),
                f"¤ per record times {records} records, capped at ¤ {benchmarks['fine_cap']}.",
            )
    else:
        fines = _triple_ok((0, 0, 0), "Regulatory fines are not applicable for this classification or loss type.")

    if not processes:
        reputation = _missing(f"No business process lists {context['scenario']['target_id']} as a primary system")
    else:
        criticality = _highest(processes, "criticality", CRIT_ORDER)
        reputation_triple = benchmarks["reputation"][criticality]
        if loss in ("Integrity", "Fraud"):
            reputation_triple = tuple(value / 2 for value in reputation_triple)
        reputation = _triple_ok(reputation_triple, f"Reputation benchmark for {criticality} criticality.")

    if loss == "Confidentiality" and (actor["motivation"] == "Espionage" or actor["actor_type"] == "Insider"):
        competitive = _triple_ok(benchmarks["competitive"], "Competitive-advantage loss is in scope for this actor and confidentiality event.")
    else:
        competitive = _triple_ok((0, 0, 0), "Competitive-advantage loss is not in scope.")

    return {
        "tef": tef,
        "susceptibility": susceptibility,
        "max_events_per_year": cap,
        "frequency_lambda": _value_ok(benchmarks["frequency_lambda"], "Lower lambda because threat frequency rests on external rates."),
        "response": response,
        "replacement": replacement,
        "productivity": productivity,
        "secondary_loss_probability": slp,
        "fines": fines,
        "reputation": reputation,
        "competitive": competitive,
        "magnitude_lambda": _value_ok(benchmarks["magnitude_lambda"], "Standard expert-calibration lambda."),
    }


def _evidence_factor(context: dict, vector: dict, factors: dict) -> tuple[float, str]:
    if vector["requires_vulnerability"] != "Yes":
        return 1.0, "This vector does not depend on an exploitable vulnerability; base susceptibility is unchanged."
    rows = [row for grouped in context["findings_by_system"].values() for row in grouped]
    kev_note = "" if context["kev_checked_at"] else " Known Exploited Vulnerability catalog was not assessed."
    if not rows:
        return factors["none"], "No vulnerability findings on the affected systems, so susceptibility is reduced." + kev_note
    cvss = [row["cvss_score"] for row in rows if row["cvss_score"] is not None]
    epss = [row["epss"] for row in rows if row["epss"] is not None]
    kev = sum(1 for row in rows if row["known_exploited"] is True)
    max_epss = max(epss) if epss else None
    if (max_epss is not None and max_epss >= 0.1) or kev:
        return factors["exploited"], "Active exploitation evidence (Exploit Prediction Scoring System or Known Exploited Vulnerability) raises susceptibility." + kev_note
    if not cvss:
        return factors["unknown_cvss"], "Findings exist but the Common Vulnerability Scoring System score is unknown, so the base susceptibility is kept." + kev_note
    if max(cvss) < 7:
        return factors["low_cvss"], "Findings are below Common Vulnerability Scoring System 7, so susceptibility is reduced slightly." + kev_note
    return factors["high_cvss"], "High-severity findings keep susceptibility at the base rate." + kev_note


def apply_controls(context: dict, control_set: str, control_ids: list[str] | None = None) -> dict:
    mappings = {mapping["control_id"]: mapping for mapping in context["mappings"]}
    if control_set == "inherent":
        chosen = []
    elif control_set == "current":
        chosen = [mapping for mapping in mappings.values() if mapping["status"] == "Implemented"]
    elif control_set == "target":
        chosen = [mapping for mapping in mappings.values() if mapping["status"] in ("Implemented", "Planned")]
    elif control_set == "custom":
        requested = control_ids or []
        unknown = [control_id for control_id in requested if control_id not in mappings]
        if unknown:
            raise ValueError("Controls are not mapped to this scenario: " + ", ".join(unknown))
        chosen = [mappings[control_id] for control_id in requested]
    else:
        raise ValueError("control_set must be inherent, current, target, or custom")

    frequency_factor = 1.0
    magnitude_factor = 1.0
    applied = []
    eliminated_by = []
    known_costs = []
    all_known = True
    for mapping in chosen:
        frequency, magnitude = _effects(mapping)
        frequency_factor *= 1 - frequency / 100
        magnitude_factor *= 1 - magnitude / 100
        if mapping["eliminates_risk"] == "Yes":
            eliminated_by.append(mapping["control_id"])
        if mapping["annual_cost"] is None:
            all_known = False
        else:
            known_costs.append(mapping["annual_cost"])
        applied.append(
            {
                "control_id": mapping["control_id"],
                "control": mapping["control"],
                "status": mapping["status"],
                "frequency_reduction_pct": frequency,
                "magnitude_reduction_pct": magnitude,
                "eliminates_risk": mapping["eliminates_risk"] == "Yes",
            }
        )
    return {
        "frequency_factor": frequency_factor,
        "magnitude_factor": magnitude_factor,
        "applied_controls": applied,
        "eliminated": bool(eliminated_by),
        "eliminated_by": eliminated_by,
        "annual_control_cost": float(sum(known_costs)),
        "annual_control_cost_known": all_known,
    }


def _effects(mapping: dict) -> tuple[float, float]:
    frequency = mapping["frequency_reduction_override_pct"]
    if frequency is None:
        frequency = mapping["frequency_reduction_pct"]
    magnitude = mapping["magnitude_reduction_override_pct"]
    if magnitude is None:
        magnitude = mapping["magnitude_reduction_pct"]
    if mapping["reduces"] not in ("Frequency", "Both"):
        frequency = 0
    if mapping["reduces"] not in ("Magnitude", "Both"):
        magnitude = 0
    return float(frequency), float(magnitude)


def effective_factors(context: dict, applied: dict) -> dict:
    scenario = context["scenario"]
    frequency_factor = applied["frequency_factor"]
    magnitude_factor = applied["magnitude_factor"]
    primary = {name: _scale(_triple(scenario, name), magnitude_factor) for name in PRIMARY}
    secondary = {name: _scale(_triple(scenario, name), magnitude_factor) for name in SECONDARY}
    return {
        "tef": _triple(scenario, "tef"),
        "tef_basis": scenario.get("tef_basis"),
        "susceptibility": _scale(_triple(scenario, "susceptibility"), frequency_factor),
        "susceptibility_basis": scenario.get("susceptibility_basis"),
        "susceptibility_inherent": _triple(scenario, "susceptibility"),
        "cap": float(scenario["max_events_per_year"]),
        "frequency_lambda": float(scenario["frequency_lambda"]),
        "primary": primary,
        "secondary": secondary,
        "slp": float(scenario["secondary_loss_probability"]),
        "magnitude_lambda": float(scenario["magnitude_lambda"]),
        "magnitude_basis": scenario.get("magnitude_basis"),
        "eliminated": applied["eliminated"],
        "frequency_factor": frequency_factor,
        "magnitude_factor": magnitude_factor,
    }


def collapse(factors: dict) -> dict:
    tef = factors["tef"]
    susceptibility = factors["susceptibility"]
    lef_min = tef[0] * susceptibility[0]
    lef_max = min(tef[2] * susceptibility[2], factors["cap"])
    lef_mode = min(tef[1] * susceptibility[1], lef_max)
    slp = factors["slp"]
    mag_min = sum(triple[0] for triple in factors["primary"].values()) + slp * sum(triple[0] for triple in factors["secondary"].values())
    mag_mode = sum(triple[1] for triple in factors["primary"].values()) + slp * sum(triple[1] for triple in factors["secondary"].values())
    mag_max = sum(triple[2] for triple in factors["primary"].values()) + slp * sum(triple[2] for triple in factors["secondary"].values())
    if not lef_min < lef_max:
        raise ValueError("Collapsed loss-event frequency is degenerate")
    if not mag_min < mag_max:
        raise ValueError("Collapsed loss magnitude is degenerate")
    frequency = (lef_min, lef_mode, lef_max)
    magnitude = (mag_min, mag_mode, mag_max)
    frequency_mean = pert_mean(frequency, factors["frequency_lambda"])
    magnitude_mean = pert_mean(magnitude, factors["magnitude_lambda"])
    ale = 0.0 if factors["eliminated"] else frequency_mean * magnitude_mean
    return {
        "frequency": frequency,
        "magnitude": magnitude,
        "frequency_lambda": factors["frequency_lambda"],
        "magnitude_lambda": factors["magnitude_lambda"],
        "frequency_pert_mean": frequency_mean,
        "magnitude_pert_mean": magnitude_mean,
        "analytic_ale": ale,
        "primary": factors["primary"],
        "secondary": factors["secondary"],
        "slp": slp,
        "eliminated": factors["eliminated"],
    }


def analytic_ale(context: dict, control_ids: list[str]) -> float:
    applied = apply_controls(context, "custom", control_ids)
    return collapse(effective_factors(context, applied))["analytic_ale"]
