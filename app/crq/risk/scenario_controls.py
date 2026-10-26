from crq.catalog.catalog_io import connect, enum_error, number_error, parse_number, read_tabular, wait_for_database

COLUMNS = (
    "Scenario ID",
    "Control ID",
    "Frequency Reduction Override (%)",
    "Magnitude Reduction Override (%)",
    "Eliminates Risk",
    "Rationale",
)

DB_FIELDS = {
    "Scenario ID": "scenario_id",
    "Control ID": "control_id",
    "Frequency Reduction Override (%)": "frequency_reduction_override_pct",
    "Magnitude Reduction Override (%)": "magnitude_reduction_override_pct",
    "Eliminates Risk": "eliminates_risk",
    "Rationale": "rationale",
}

YES_NO = ("Yes", "No")

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS scenario_controls (
    scenario_id TEXT NOT NULL,
    control_id TEXT NOT NULL,
    frequency_reduction_override_pct DOUBLE PRECISION,
    magnitude_reduction_override_pct DOUBLE PRECISION,
    eliminates_risk TEXT NOT NULL,
    rationale TEXT NOT NULL,
    PRIMARY KEY (scenario_id, control_id)
)
"""

CREATE_META = """
CREATE TABLE IF NOT EXISTS scenario_control_meta (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    extracted_at TIMESTAMPTZ NOT NULL
)
"""

TOUCH_META = """
INSERT INTO scenario_control_meta (id, extracted_at)
VALUES (1, NOW())
ON CONFLICT (id) DO UPDATE SET extracted_at = EXCLUDED.extracted_at
"""


def init_scenario_controls() -> None:
    def apply(connection) -> None:
        connection.execute(CREATE_TABLE)
        connection.execute(CREATE_META)

    wait_for_database(apply)


def list_scenario_controls() -> dict:
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT scenario_id, control_id, frequency_reduction_override_pct,
                   magnitude_reduction_override_pct, eliminates_risk, rationale
            FROM scenario_controls
            ORDER BY scenario_id, control_id
            """
        ).fetchall()
        scenarios = {
            row["scenario_id"]: row["scenario"]
            for row in connection.execute("SELECT scenario_id, scenario FROM risk_scenarios")
        }
        controls = {
            row["control_id"]: row
            for row in connection.execute(
                "SELECT control_id, control, status, reduces, frequency_reduction_pct, magnitude_reduction_pct FROM controls"
            )
        }
        meta = connection.execute("SELECT extracted_at FROM scenario_control_meta WHERE id = 1").fetchone()
    extracted_at = meta["extracted_at"].isoformat() if meta else None
    items = []
    for row in rows:
        control = controls.get(row["control_id"], {})
        reduces = control.get("reduces", "")
        frequency = row["frequency_reduction_override_pct"]
        if frequency is None:
            frequency = control.get("frequency_reduction_pct")
        magnitude = row["magnitude_reduction_override_pct"]
        if magnitude is None:
            magnitude = control.get("magnitude_reduction_pct")
        if reduces == "Magnitude":
            frequency = 0
        elif reduces == "Frequency":
            magnitude = 0
        item = dict(row)
        item["scenario"] = scenarios.get(row["scenario_id"], "")
        item["control"] = control.get("control", "")
        item["control_status"] = control.get("status", "")
        item["effective_frequency_reduction_pct"] = frequency
        item["effective_magnitude_reduction_pct"] = magnitude
        items.append(item)
    return {"items": items, "extracted_at": extracted_at}


def upload_scenario_controls(filename: str, content: bytes) -> tuple[int, dict]:
    parsed, error = read_tabular(filename, content, COLUMNS)
    if error:
        return 422, {"ok": False, "error": error}
    seen = set()
    duplicates = []
    for _row, values in parsed:
        pair = (str(values["Scenario ID"]).strip(), str(values["Control ID"]).strip())
        if pair in seen and pair not in duplicates:
            duplicates.append(pair)
        seen.add(pair)
    if duplicates:
        rendered = ", ".join(f"{scenario} + {control}" for scenario, control in duplicates)
        return 422, {"ok": False, "error": "The file contains duplicate Scenario ID + Control ID pairs: " + rendered}
    with connect() as connection:
        refs = _refs(connection)
    review, stored, any_invalid = _review(parsed, refs)
    if any_invalid:
        return 422, {"ok": False, "rows": review}
    _replace(stored)
    listed = list_scenario_controls()
    return 200, {"ok": True, "count": len(listed["items"]), **listed}


def add_scenario_control(fields: dict) -> tuple[int, dict]:
    with connect() as connection:
        errors = _validate_fields(fields, _refs(connection))
        if errors:
            return 422, {"ok": False, "errors": errors}
        cleaned = _clean(fields)
        if _exists(connection, cleaned["scenario_id"], cleaned["control_id"]):
            return 422, {"ok": False, "errors": {"Scenario ID": "is already mapped to this Control ID"}}
        with connection.transaction():
            _insert(connection, cleaned)
            connection.execute(TOUCH_META)
    return 200, {"ok": True, **list_scenario_controls()}


def update_scenario_control(previous_scenario_id: str, previous_control_id: str, fields: dict) -> tuple[int, dict]:
    previous_scenario = previous_scenario_id.strip()
    previous_control = previous_control_id.strip()
    with connect() as connection:
        errors = _validate_fields(fields, _refs(connection))
        if errors:
            return 422, {"ok": False, "errors": errors}
        cleaned = _clean(fields)
        if not _exists(connection, previous_scenario, previous_control):
            return 404, {"ok": False, "error": "That scenario control mapping was not found."}
        moved = (cleaned["scenario_id"], cleaned["control_id"]) != (previous_scenario, previous_control)
        if moved and _exists(connection, cleaned["scenario_id"], cleaned["control_id"]):
            return 422, {"ok": False, "errors": {"Scenario ID": "is already mapped to this Control ID"}}
        with connection.transaction():
            connection.execute(
                """
                UPDATE scenario_controls
                SET scenario_id = %(scenario_id)s,
                    control_id = %(control_id)s,
                    frequency_reduction_override_pct = %(frequency_reduction_override_pct)s,
                    magnitude_reduction_override_pct = %(magnitude_reduction_override_pct)s,
                    eliminates_risk = %(eliminates_risk)s,
                    rationale = %(rationale)s
                WHERE scenario_id = %(previous_scenario)s AND control_id = %(previous_control)s
                """,
                {**cleaned, "previous_scenario": previous_scenario, "previous_control": previous_control},
            )
            connection.execute(TOUCH_META)
    return 200, {"ok": True, **list_scenario_controls()}


def delete_scenario_control(scenario_id: str, control_id: str) -> tuple[int, dict]:
    scenario = scenario_id.strip()
    control = control_id.strip()
    with connect() as connection:
        if not _exists(connection, scenario, control):
            return 404, {"ok": False, "error": "That scenario control mapping was not found."}
        with connection.transaction():
            connection.execute(
                "DELETE FROM scenario_controls WHERE scenario_id = %s AND control_id = %s",
                (scenario, control),
            )
            connection.execute(TOUCH_META)
    return 200, {"ok": True, **list_scenario_controls()}


def _refs(connection) -> dict:
    return {
        "scenarios": {row["scenario_id"] for row in connection.execute("SELECT scenario_id FROM risk_scenarios")},
        "controls": {row["control_id"] for row in connection.execute("SELECT control_id FROM controls")},
    }


def _exists(connection, scenario_id: str, control_id: str) -> bool:
    return connection.execute(
        "SELECT scenario_id FROM scenario_controls WHERE scenario_id = %s AND control_id = %s",
        (scenario_id, control_id),
    ).fetchone() is not None


def _insert(connection, row: dict) -> None:
    connection.execute(
        """
        INSERT INTO scenario_controls (
            scenario_id, control_id, frequency_reduction_override_pct, magnitude_reduction_override_pct,
            eliminates_risk, rationale
        )
        VALUES (
            %(scenario_id)s, %(control_id)s, %(frequency_reduction_override_pct)s, %(magnitude_reduction_override_pct)s,
            %(eliminates_risk)s, %(rationale)s
        )
        """,
        row,
    )


def _replace(rows: list[dict]) -> None:
    with connect() as connection:
        with connection.transaction():
            connection.execute("DELETE FROM scenario_controls")
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
    scenario_id = str(values.get("Scenario ID") or "").strip()
    control_id = str(values.get("Control ID") or "").strip()
    if not scenario_id:
        errors["Scenario ID"] = "must not be empty"
    elif scenario_id not in refs["scenarios"]:
        errors["Scenario ID"] = "must be an existing Scenario ID"
    if not control_id:
        errors["Control ID"] = "must not be empty"
    elif control_id not in refs["controls"]:
        errors["Control ID"] = "must be an existing Control ID"
    for column in ("Frequency Reduction Override (%)", "Magnitude Reduction Override (%)"):
        error = number_error(values.get(column, ""), allow_blank=True, minimum=0, maximum=100, exclusive_max=True)
        if error:
            errors[column] = error
    eliminates = enum_error(str(values.get("Eliminates Risk") or "").strip(), YES_NO)
    if eliminates:
        errors["Eliminates Risk"] = eliminates
    return errors


def _clean(fields: dict) -> dict:
    return {
        "scenario_id": str(fields.get("scenario_id") or "").strip(),
        "control_id": str(fields.get("control_id") or "").strip(),
        "frequency_reduction_override_pct": parse_number(fields.get("frequency_reduction_override_pct")),
        "magnitude_reduction_override_pct": parse_number(fields.get("magnitude_reduction_override_pct")),
        "eliminates_risk": str(fields.get("eliminates_risk") or "").strip(),
        "rationale": str(fields.get("rationale") or "").strip(),
    }
