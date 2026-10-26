from crq.catalog.catalog_io import (
    connect,
    duplicate_ids,
    enum_error,
    number_error,
    parse_number,
    read_tabular,
    triple_error,
    wait_for_database,
)

CARD_COLUMNS = (
    "Scenario ID",
    "Scenario",
    "Threat Actor ID",
    "Attack Vector ID",
    "Target Type",
    "Target ID",
    "Risk Owner OU ID",
    "Description",
    "Status",
)

FREQUENCY_COLUMNS = (
    "TEF Min",
    "TEF Mode",
    "TEF Max",
    "TEF Basis",
    "Susceptibility Min",
    "Susceptibility Mode",
    "Susceptibility Max",
    "Susceptibility Basis",
    "Max Loss Events per Year",
    "Frequency Lambda",
)

MAGNITUDE_COLUMNS = (
    "Response Min",
    "Response Mode",
    "Response Max",
    "Replacement Min",
    "Replacement Mode",
    "Replacement Max",
    "Productivity Min",
    "Productivity Mode",
    "Productivity Max",
    "Secondary Loss Probability",
    "Fines Min",
    "Fines Mode",
    "Fines Max",
    "Reputation Min",
    "Reputation Mode",
    "Reputation Max",
    "Competitive Min",
    "Competitive Mode",
    "Competitive Max",
    "Magnitude Basis",
    "Magnitude Lambda",
)

LINEAGE_COLUMNS = ("Evidence", "Calibration Notes")

COLUMNS = CARD_COLUMNS + FREQUENCY_COLUMNS + MAGNITUDE_COLUMNS + LINEAGE_COLUMNS

DB_FIELDS = {
    "Scenario ID": "scenario_id",
    "Scenario": "scenario",
    "Threat Actor ID": "threat_actor_id",
    "Attack Vector ID": "attack_vector_id",
    "Target Type": "target_type",
    "Target ID": "target_id",
    "Risk Owner OU ID": "risk_owner_ou_id",
    "Description": "description",
    "Status": "status",
    "TEF Min": "tef_min",
    "TEF Mode": "tef_mode",
    "TEF Max": "tef_max",
    "TEF Basis": "tef_basis",
    "Susceptibility Min": "susceptibility_min",
    "Susceptibility Mode": "susceptibility_mode",
    "Susceptibility Max": "susceptibility_max",
    "Susceptibility Basis": "susceptibility_basis",
    "Max Loss Events per Year": "max_events_per_year",
    "Frequency Lambda": "frequency_lambda",
    "Response Min": "response_min",
    "Response Mode": "response_mode",
    "Response Max": "response_max",
    "Replacement Min": "replacement_min",
    "Replacement Mode": "replacement_mode",
    "Replacement Max": "replacement_max",
    "Productivity Min": "productivity_min",
    "Productivity Mode": "productivity_mode",
    "Productivity Max": "productivity_max",
    "Secondary Loss Probability": "secondary_loss_probability",
    "Fines Min": "fines_min",
    "Fines Mode": "fines_mode",
    "Fines Max": "fines_max",
    "Reputation Min": "reputation_min",
    "Reputation Mode": "reputation_mode",
    "Reputation Max": "reputation_max",
    "Competitive Min": "competitive_min",
    "Competitive Mode": "competitive_mode",
    "Competitive Max": "competitive_max",
    "Magnitude Basis": "magnitude_basis",
    "Magnitude Lambda": "magnitude_lambda",
    "Evidence": "evidence",
    "Calibration Notes": "calibration_notes",
}

TARGET_TYPES = ("Software System", "Business Process")
STATUSES = ("Draft", "Reviewed", "Approved")
BASIS = ("External", "Internal", "Expert", "Mixed")
LOSS_PREFIXES = ("Response", "Replacement", "Productivity", "Fines", "Reputation", "Competitive")
PRIMARY = ("response", "replacement", "productivity")
SECONDARY = ("fines", "reputation", "competitive")

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS risk_scenarios (
    scenario_id TEXT PRIMARY KEY,
    scenario TEXT NOT NULL,
    threat_actor_id TEXT NOT NULL,
    attack_vector_id TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    risk_owner_ou_id TEXT NOT NULL,
    description TEXT NOT NULL,
    status TEXT NOT NULL,
    tef_min DOUBLE PRECISION NOT NULL,
    tef_mode DOUBLE PRECISION NOT NULL,
    tef_max DOUBLE PRECISION NOT NULL,
    tef_basis TEXT NOT NULL,
    susceptibility_min DOUBLE PRECISION NOT NULL,
    susceptibility_mode DOUBLE PRECISION NOT NULL,
    susceptibility_max DOUBLE PRECISION NOT NULL,
    susceptibility_basis TEXT NOT NULL,
    max_events_per_year DOUBLE PRECISION NOT NULL,
    frequency_lambda DOUBLE PRECISION NOT NULL,
    response_min DOUBLE PRECISION NOT NULL,
    response_mode DOUBLE PRECISION NOT NULL,
    response_max DOUBLE PRECISION NOT NULL,
    replacement_min DOUBLE PRECISION NOT NULL,
    replacement_mode DOUBLE PRECISION NOT NULL,
    replacement_max DOUBLE PRECISION NOT NULL,
    productivity_min DOUBLE PRECISION NOT NULL,
    productivity_mode DOUBLE PRECISION NOT NULL,
    productivity_max DOUBLE PRECISION NOT NULL,
    secondary_loss_probability DOUBLE PRECISION NOT NULL,
    fines_min DOUBLE PRECISION NOT NULL,
    fines_mode DOUBLE PRECISION NOT NULL,
    fines_max DOUBLE PRECISION NOT NULL,
    reputation_min DOUBLE PRECISION NOT NULL,
    reputation_mode DOUBLE PRECISION NOT NULL,
    reputation_max DOUBLE PRECISION NOT NULL,
    competitive_min DOUBLE PRECISION NOT NULL,
    competitive_mode DOUBLE PRECISION NOT NULL,
    competitive_max DOUBLE PRECISION NOT NULL,
    magnitude_basis TEXT NOT NULL,
    magnitude_lambda DOUBLE PRECISION NOT NULL,
    evidence TEXT NOT NULL,
    calibration_notes TEXT NOT NULL
)
"""

CREATE_META = """
CREATE TABLE IF NOT EXISTS risk_scenario_meta (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    extracted_at TIMESTAMPTZ NOT NULL
)
"""

TOUCH_META = """
INSERT INTO risk_scenario_meta (id, extracted_at)
VALUES (1, NOW())
ON CONFLICT (id) DO UPDATE SET extracted_at = EXCLUDED.extracted_at
"""


def init_scenarios() -> None:
    def apply(connection) -> None:
        connection.execute(CREATE_TABLE)
        connection.execute(CREATE_META)

    wait_for_database(apply)


def list_scenarios() -> dict:
    with connect() as connection:
        rows = connection.execute("SELECT * FROM risk_scenarios ORDER BY scenario_id").fetchall()
        actors = {row["actor_id"]: row["threat_actor"] for row in connection.execute("SELECT actor_id, threat_actor FROM threat_actors")}
        vectors = {
            row["vector_id"]: row
            for row in connection.execute("SELECT vector_id, attack_vector, loss_event_type, technique_chain FROM attack_vectors")
        }
        systems = {row["system_id"]: row["software_system"] for row in connection.execute("SELECT system_id, software_system FROM software_systems")}
        processes = {row["bp_id"]: row["business_process"] for row in connection.execute("SELECT bp_id, business_process FROM business_processes")}
        units = {row["ou_id"]: row["organisational_unit"] for row in connection.execute("SELECT ou_id, organisational_unit FROM organisational_units")}
        meta = connection.execute("SELECT extracted_at FROM risk_scenario_meta WHERE id = 1").fetchone()
    extracted_at = meta["extracted_at"].isoformat() if meta else None
    items = []
    for row in rows:
        item = dict(row)
        vector = vectors.get(row["attack_vector_id"], {})
        item["threat_actor"] = actors.get(row["threat_actor_id"], "")
        item["attack_vector"] = vector.get("attack_vector", "")
        item["loss_event_type"] = vector.get("loss_event_type", "")
        item["technique_chain"] = vector.get("technique_chain", "")
        names = systems if row["target_type"] == "Software System" else processes
        item["target_name"] = names.get(row["target_id"], "")
        item["risk_owner_ou"] = units.get(row["risk_owner_ou_id"], "")
        items.append(item)
    return {"items": items, "extracted_at": extracted_at}


def upload_scenarios(filename: str, content: bytes) -> tuple[int, dict]:
    parsed, error = read_tabular(filename, content, COLUMNS)
    if error:
        return 422, {"ok": False, "error": error}
    duplicate_error = duplicate_ids([values["Scenario ID"] for _row, values in parsed], "Scenario IDs")
    if duplicate_error:
        return 422, {"ok": False, "error": duplicate_error}
    with connect() as connection:
        refs = _refs(connection)
    review, stored, any_invalid = _review(parsed, refs)
    if any_invalid:
        return 422, {"ok": False, "rows": review}
    with connect() as connection:
        missing = sorted(_referenced(connection) - {row["scenario_id"] for row in stored})
    if missing:
        return 422, {
            "ok": False,
            "error": "These Scenario IDs are still in use and are missing from the file: " + ", ".join(missing),
        }
    _replace(stored)
    listed = list_scenarios()
    return 200, {"ok": True, "count": len(listed["items"]), **listed}


def add_scenario(fields: dict) -> tuple[int, dict]:
    with connect() as connection:
        errors = _validate_fields(fields, _refs(connection))
        if errors:
            return 422, {"ok": False, "errors": errors}
        cleaned = _clean(fields)
        if _exists(connection, cleaned["scenario_id"]):
            return 422, {"ok": False, "errors": {"Scenario ID": "already exists"}}
        with connection.transaction():
            _insert(connection, cleaned)
            connection.execute(TOUCH_META)
    return 200, {"ok": True, **list_scenarios()}


def update_scenario(previous_scenario_id: str, fields: dict) -> tuple[int, dict]:
    previous = previous_scenario_id.strip()
    with connect() as connection:
        errors = _validate_fields(fields, _refs(connection))
        if errors:
            return 422, {"ok": False, "errors": errors}
        cleaned = _clean(fields)
        if not _exists(connection, previous):
            return 404, {"ok": False, "error": "That risk scenario was not found."}
        if cleaned["scenario_id"] != previous:
            if previous in _referenced(connection):
                return 422, {"ok": False, "errors": {"Scenario ID": "is still used by a scenario control mapping"}}
            if _exists(connection, cleaned["scenario_id"]):
                return 422, {"ok": False, "errors": {"Scenario ID": "already exists"}}
        with connection.transaction():
            assignments = ", ".join(f"{field} = %({field})s" for field in cleaned)
            connection.execute(
                f"UPDATE risk_scenarios SET {assignments} WHERE scenario_id = %(previous)s",
                {**cleaned, "previous": previous},
            )
            connection.execute(TOUCH_META)
    return 200, {"ok": True, **list_scenarios()}


def delete_scenario(scenario_id: str) -> tuple[int, dict]:
    previous = scenario_id.strip()
    with connect() as connection:
        if not _exists(connection, previous):
            return 404, {"ok": False, "error": "That risk scenario was not found."}
        if previous in _referenced(connection):
            return 422, {"ok": False, "error": "That risk scenario is still used by a scenario control mapping."}
        with connection.transaction():
            connection.execute("DELETE FROM risk_scenarios WHERE scenario_id = %s", (previous,))
            connection.execute(TOUCH_META)
    return 200, {"ok": True, **list_scenarios()}


def _refs(connection) -> dict:
    return {
        "actors": {row["actor_id"] for row in connection.execute("SELECT actor_id FROM threat_actors")},
        "vectors": {row["vector_id"] for row in connection.execute("SELECT vector_id FROM attack_vectors")},
        "systems": {row["system_id"] for row in connection.execute("SELECT system_id FROM software_systems")},
        "processes": {row["bp_id"] for row in connection.execute("SELECT bp_id FROM business_processes")},
        "units": {row["ou_id"] for row in connection.execute("SELECT ou_id FROM organisational_units")},
    }


def _referenced(connection) -> set[str]:
    return {row["scenario_id"] for row in connection.execute("SELECT scenario_id FROM scenario_controls")}


def _exists(connection, scenario_id: str) -> bool:
    return connection.execute(
        "SELECT scenario_id FROM risk_scenarios WHERE scenario_id = %s", (scenario_id,)
    ).fetchone() is not None


def _insert(connection, row: dict) -> None:
    columns = ", ".join(row)
    placeholders = ", ".join(f"%({column})s" for column in row)
    connection.execute(f"INSERT INTO risk_scenarios ({columns}) VALUES ({placeholders})", row)


def _replace(rows: list[dict]) -> None:
    with connect() as connection:
        with connection.transaction():
            connection.execute("DELETE FROM risk_scenarios")
            for row in rows:
                _insert(connection, row)
            connection.execute(TOUCH_META)


def _review(parsed, refs: dict):
    review, stored, any_invalid = [], [], False
    for row_number, values in parsed:
        errors = _validate_values(values, refs)
        any_invalid = any_invalid or bool(errors)
        review.append({"row": row_number, "values": values, "errors": errors})
        stored.append(_clean({DB_FIELDS[column]: values[column] for column in COLUMNS}))
    return review, stored, any_invalid


def _validate_fields(fields: dict, refs: dict) -> dict:
    return _validate_values({column: fields.get(DB_FIELDS[column], "") for column in COLUMNS}, refs)


def _validate_values(values: dict, refs: dict) -> dict:
    errors = {}
    for column in ("Scenario ID", "Scenario", "Description"):
        if not str(values.get(column) or "").strip():
            errors[column] = "must not be empty"
    actor = str(values.get("Threat Actor ID") or "").strip()
    if not actor:
        errors["Threat Actor ID"] = "must not be empty"
    elif actor not in refs["actors"]:
        errors["Threat Actor ID"] = "must be an existing Actor ID"
    vector = str(values.get("Attack Vector ID") or "").strip()
    if not vector:
        errors["Attack Vector ID"] = "must not be empty"
    elif vector not in refs["vectors"]:
        errors["Attack Vector ID"] = "must be an existing Vector ID"
    target_type = str(values.get("Target Type") or "").strip()
    type_error = enum_error(target_type, TARGET_TYPES)
    if type_error:
        errors["Target Type"] = type_error
    target = str(values.get("Target ID") or "").strip()
    if not target:
        errors["Target ID"] = "must not be empty"
    elif target_type == "Software System" and target not in refs["systems"]:
        errors["Target ID"] = "must be an existing System ID"
    elif target_type == "Business Process" and target not in refs["processes"]:
        errors["Target ID"] = "must be an existing business process"
    owner = str(values.get("Risk Owner OU ID") or "").strip()
    if not owner:
        errors["Risk Owner OU ID"] = "must not be empty"
    elif owner not in refs["units"]:
        errors["Risk Owner OU ID"] = "must be an existing organisational unit"
    status_error = enum_error(str(values.get("Status") or "").strip(), STATUSES)
    if status_error:
        errors["Status"] = status_error
    errors.update(triple_error(values, "TEF"))
    if "TEF Min" not in errors and "TEF Max" not in errors:
        tef_min = parse_number(values.get("TEF Min"))
        tef_max = parse_number(values.get("TEF Max"))
        if tef_min is not None and tef_max is not None and not tef_max > tef_min:
            errors["TEF Max"] = "must be greater than Min"
    basis_error = enum_error(str(values.get("TEF Basis") or "").strip(), BASIS)
    if basis_error:
        errors["TEF Basis"] = basis_error
    errors.update(triple_error(values, "Susceptibility"))
    for column in ("Susceptibility Min", "Susceptibility Mode", "Susceptibility Max"):
        if column in errors:
            continue
        bound = number_error(values.get(column, ""), allow_blank=False, minimum=0, maximum=1)
        if bound:
            errors[column] = bound
    if "Susceptibility Max" not in errors:
        susceptibility_max = parse_number(values.get("Susceptibility Max"))
        if susceptibility_max is not None and not susceptibility_max > 0:
            errors["Susceptibility Max"] = "must be > 0"
    susceptibility_basis = enum_error(str(values.get("Susceptibility Basis") or "").strip(), BASIS)
    if susceptibility_basis:
        errors["Susceptibility Basis"] = susceptibility_basis
    cap_error = number_error(values.get("Max Loss Events per Year", ""), allow_blank=False, minimum=0)
    if cap_error:
        errors["Max Loss Events per Year"] = cap_error
    elif (
        "TEF Min" not in errors
        and "Susceptibility Min" not in errors
        and parse_number(values.get("Max Loss Events per Year")) is not None
    ):
        floor = parse_number(values.get("TEF Min")) * parse_number(values.get("Susceptibility Min"))
        cap = parse_number(values.get("Max Loss Events per Year"))
        if not cap > 0 or not cap > floor:
            errors["Max Loss Events per Year"] = "must exceed TEF Min x Susceptibility Min"
    lambda_error = number_error(values.get("Frequency Lambda", ""), allow_blank=False, minimum=1, maximum=10)
    if lambda_error:
        errors["Frequency Lambda"] = lambda_error
    for prefix in LOSS_PREFIXES:
        errors.update(triple_error(values, prefix))
    slp_error = number_error(values.get("Secondary Loss Probability", ""), allow_blank=False, minimum=0, maximum=1)
    if slp_error:
        errors["Secondary Loss Probability"] = slp_error
    magnitude_basis = enum_error(str(values.get("Magnitude Basis") or "").strip(), BASIS)
    if magnitude_basis:
        errors["Magnitude Basis"] = magnitude_basis
    magnitude_lambda = number_error(values.get("Magnitude Lambda", ""), allow_blank=False, minimum=1, maximum=10)
    if magnitude_lambda:
        errors["Magnitude Lambda"] = magnitude_lambda
    if not any(column.startswith(tuple(prefix + " " for prefix in LOSS_PREFIXES)) for column in errors) and "Secondary Loss Probability" not in errors:
        slp = parse_number(values.get("Secondary Loss Probability"))
        primary_min = sum(parse_number(values.get(f"{prefix} Min")) for prefix in ("Response", "Replacement", "Productivity"))
        primary_max = sum(parse_number(values.get(f"{prefix} Max")) for prefix in ("Response", "Replacement", "Productivity"))
        secondary_min = sum(parse_number(values.get(f"{prefix} Min")) for prefix in ("Fines", "Reputation", "Competitive"))
        secondary_max = sum(parse_number(values.get(f"{prefix} Max")) for prefix in ("Fines", "Reputation", "Competitive"))
        if not (primary_max + slp * secondary_max) > (primary_min + slp * secondary_min):
            errors["Response Min"] = "magnitude is degenerate: at least one loss form must have Max > Min"
    return errors


def _clean(fields: dict) -> dict:
    text_fields = (
        "scenario_id",
        "scenario",
        "threat_actor_id",
        "attack_vector_id",
        "target_type",
        "target_id",
        "risk_owner_ou_id",
        "description",
        "status",
        "tef_basis",
        "susceptibility_basis",
        "magnitude_basis",
        "evidence",
        "calibration_notes",
    )
    cleaned = {field: str(fields.get(field) or "").strip() for field in text_fields}
    for column, field in DB_FIELDS.items():
        if field in cleaned:
            continue
        cleaned[field] = parse_number(fields.get(field))
    return cleaned
