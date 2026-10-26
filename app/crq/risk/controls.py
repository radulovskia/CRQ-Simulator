from crq.catalog.catalog_io import (
    MITIGATION_ID,
    attack_id_error,
    connect,
    duplicate_ids,
    enum_error,
    normalise_id_list,
    number_error,
    parse_number,
    read_tabular,
    rename_column,
    wait_for_database,
)
from crq.intelligence.mitre import loaded_attack_ids, unknown_attack_ids

COLUMNS = (
    "Control ID",
    "Control",
    "Control Type",
    "ATT&CK Mitigations",
    "Reduces",
    "Frequency Reduction (%)",
    "Magnitude Reduction (%)",
    "Status",
    "Implementation Cost",
    "Annual Cost",
    "Owner OU ID",
    "Framework Reference",
    "Description",
)

DB_FIELDS = {
    "Control ID": "control_id",
    "Control": "control",
    "Control Type": "control_type",
    "ATT&CK Mitigations": "mitigations",
    "Reduces": "reduces",
    "Frequency Reduction (%)": "frequency_reduction_pct",
    "Magnitude Reduction (%)": "magnitude_reduction_pct",
    "Status": "status",
    "Implementation Cost": "implementation_cost",
    "Annual Cost": "annual_cost",
    "Owner OU ID": "owner_ou_id",
    "Framework Reference": "framework_reference",
    "Description": "description",
}

CONTROL_TYPES = ("Preventive", "Detective", "Corrective")
REDUCES = ("Frequency", "Magnitude", "Both")
STATUSES = ("Implemented", "Planned", "Not Implemented")

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS controls (
    control_id TEXT PRIMARY KEY,
    control TEXT NOT NULL,
    control_type TEXT NOT NULL,
    mitigations TEXT NOT NULL,
    reduces TEXT NOT NULL,
    frequency_reduction_pct DOUBLE PRECISION NOT NULL,
    magnitude_reduction_pct DOUBLE PRECISION NOT NULL,
    status TEXT NOT NULL,
    implementation_cost DOUBLE PRECISION,
    annual_cost DOUBLE PRECISION,
    owner_ou_id TEXT NOT NULL,
    framework_reference TEXT NOT NULL,
    description TEXT NOT NULL
)
"""

CREATE_META = """
CREATE TABLE IF NOT EXISTS control_meta (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    extracted_at TIMESTAMPTZ NOT NULL
)
"""

TOUCH_META = """
INSERT INTO control_meta (id, extracted_at)
VALUES (1, NOW())
ON CONFLICT (id) DO UPDATE SET extracted_at = EXCLUDED.extracted_at
"""


def init_controls() -> None:
    def apply(connection) -> None:
        connection.execute(CREATE_TABLE)
        connection.execute(CREATE_META)
        rename_column(connection, "controls", "implementation_cost_eur", "implementation_cost")
        rename_column(connection, "controls", "annual_cost_eur", "annual_cost")

    wait_for_database(apply)


def list_controls() -> dict:
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT control_id, control, control_type, mitigations, reduces, frequency_reduction_pct,
                   magnitude_reduction_pct, status, implementation_cost, annual_cost,
                   owner_ou_id, framework_reference, description
            FROM controls
            ORDER BY control_id
            """
        ).fetchall()
        units = {
            row["ou_id"]: row["organisational_unit"]
            for row in connection.execute("SELECT ou_id, organisational_unit FROM organisational_units")
        }
        meta = connection.execute("SELECT extracted_at FROM control_meta WHERE id = 1").fetchone()
    extracted_at = meta["extracted_at"].isoformat() if meta else None
    items = []
    for row in rows:
        item = dict(row)
        item["owner_ou"] = units.get(row["owner_ou_id"], "")
        items.append(item)
    return {"items": items, "extracted_at": extracted_at}


def upload_controls(filename: str, content: bytes) -> tuple[int, dict]:
    parsed, error = read_tabular(filename, content, COLUMNS)
    if error:
        return 422, {"ok": False, "error": error}
    duplicate_error = duplicate_ids([values["Control ID"] for _row, values in parsed], "Control IDs")
    if duplicate_error:
        return 422, {"ok": False, "error": duplicate_error}
    with connect() as connection:
        ou_ids = _ou_ids(connection)
    review, stored, any_invalid = _review(parsed, ou_ids, loaded_attack_ids())
    if any_invalid:
        return 422, {"ok": False, "rows": review}
    with connect() as connection:
        missing = sorted(_referenced(connection) - {row["control_id"] for row in stored})
    if missing:
        return 422, {
            "ok": False,
            "error": "These Control IDs are still in use and are missing from the file: " + ", ".join(missing),
        }
    _replace(stored)
    listed = list_controls()
    return 200, {"ok": True, "count": len(listed["items"]), **listed}


def add_control(fields: dict) -> tuple[int, dict]:
    catalog = loaded_attack_ids()
    with connect() as connection:
        errors = _validate_fields(fields, _ou_ids(connection), catalog)
        if errors:
            return 422, {"ok": False, "errors": errors}
        cleaned = _clean(fields)
        if _exists(connection, cleaned["control_id"]):
            return 422, {"ok": False, "errors": {"Control ID": "already exists"}}
        with connection.transaction():
            _insert(connection, cleaned)
            connection.execute(TOUCH_META)
    return 200, {"ok": True, **list_controls()}


def update_control(previous_control_id: str, fields: dict) -> tuple[int, dict]:
    previous = previous_control_id.strip()
    catalog = loaded_attack_ids()
    with connect() as connection:
        errors = _validate_fields(fields, _ou_ids(connection), catalog)
        if errors:
            return 422, {"ok": False, "errors": errors}
        cleaned = _clean(fields)
        if not _exists(connection, previous):
            return 404, {"ok": False, "error": "That control was not found."}
        if cleaned["control_id"] != previous:
            if previous in _referenced(connection):
                return 422, {"ok": False, "errors": {"Control ID": "is still used by a scenario control mapping"}}
            if _exists(connection, cleaned["control_id"]):
                return 422, {"ok": False, "errors": {"Control ID": "already exists"}}
        with connection.transaction():
            assignments = ", ".join(f"{field} = %({field})s" for field in cleaned)
            connection.execute(
                f"UPDATE controls SET {assignments} WHERE control_id = %(previous)s",
                {**cleaned, "previous": previous},
            )
            connection.execute(TOUCH_META)
    return 200, {"ok": True, **list_controls()}


def delete_control(control_id: str) -> tuple[int, dict]:
    previous = control_id.strip()
    with connect() as connection:
        if not _exists(connection, previous):
            return 404, {"ok": False, "error": "That control was not found."}
        if previous in _referenced(connection):
            return 422, {"ok": False, "error": "That control is still used by a scenario control mapping."}
        with connection.transaction():
            connection.execute("DELETE FROM controls WHERE control_id = %s", (previous,))
            connection.execute(TOUCH_META)
    return 200, {"ok": True, **list_controls()}


def _ou_ids(connection) -> set[str]:
    return {row["ou_id"] for row in connection.execute("SELECT ou_id FROM organisational_units")}


def _referenced(connection) -> set[str]:
    return {row["control_id"] for row in connection.execute("SELECT control_id FROM scenario_controls")}


def _exists(connection, control_id: str) -> bool:
    return connection.execute("SELECT control_id FROM controls WHERE control_id = %s", (control_id,)).fetchone() is not None


def _insert(connection, row: dict) -> None:
    columns = ", ".join(row)
    placeholders = ", ".join(f"%({column})s" for column in row)
    connection.execute(f"INSERT INTO controls ({columns}) VALUES ({placeholders})", row)


def _replace(rows: list[dict]) -> None:
    with connect() as connection:
        with connection.transaction():
            connection.execute("DELETE FROM controls")
            for row in rows:
                _insert(connection, row)
            connection.execute(TOUCH_META)


def _review(parsed, ou_ids: set[str], catalog: dict[str, set[str]] | None):
    review, stored, any_invalid = [], [], False
    for row_number, values in parsed:
        errors = _validate_values(values, ou_ids, catalog)
        any_invalid = any_invalid or bool(errors)
        review.append({"row": row_number, "values": values, "errors": errors})
        stored.append(_clean({DB_FIELDS[column]: values[column] for column in COLUMNS}))
    return review, stored, any_invalid


def _validate_fields(fields: dict, ou_ids: set[str], catalog: dict[str, set[str]] | None) -> dict:
    return _validate_values({column: fields.get(DB_FIELDS[column], "") for column in COLUMNS}, ou_ids, catalog)


def _validate_values(values: dict, ou_ids: set[str], catalog: dict[str, set[str]] | None) -> dict:
    errors = {}
    for column in ("Control ID", "Control", "Description"):
        if not str(values.get(column) or "").strip():
            errors[column] = "must not be empty"
    for column, options in (("Control Type", CONTROL_TYPES), ("Reduces", REDUCES), ("Status", STATUSES)):
        error = enum_error(str(values.get(column) or "").strip(), options)
        if error:
            errors[column] = error
    mitigations = str(values.get("ATT&CK Mitigations") or "")
    mitigation_error = attack_id_error(mitigations, MITIGATION_ID, "ATT&CK mitigation IDs")
    if mitigation_error:
        errors["ATT&CK Mitigations"] = mitigation_error
    else:
        known = None if catalog is None else catalog["mitigations"]
        catalog_error = unknown_attack_ids(
            [part for part in normalise_id_list(mitigations).split(", ") if part],
            known,
            "ATT&CK mitigation IDs",
        )
        if catalog_error:
            errors["ATT&CK Mitigations"] = catalog_error
    for column in ("Frequency Reduction (%)", "Magnitude Reduction (%)"):
        error = number_error(values.get(column, ""), allow_blank=False, minimum=0, maximum=100, exclusive_max=True)
        if error:
            errors[column] = error
    for column in ("Implementation Cost", "Annual Cost"):
        error = number_error(values.get(column, ""), allow_blank=True, minimum=0)
        if error:
            errors[column] = error
    owner = str(values.get("Owner OU ID") or "").strip()
    if not owner:
        errors["Owner OU ID"] = "must not be empty"
    elif owner not in ou_ids:
        errors["Owner OU ID"] = "must be an existing organisational unit"
    return errors


def _clean(fields: dict) -> dict:
    return {
        "control_id": str(fields.get("control_id") or "").strip(),
        "control": str(fields.get("control") or "").strip(),
        "control_type": str(fields.get("control_type") or "").strip(),
        "mitigations": normalise_id_list(fields.get("mitigations") or ""),
        "reduces": str(fields.get("reduces") or "").strip(),
        "frequency_reduction_pct": parse_number(fields.get("frequency_reduction_pct")),
        "magnitude_reduction_pct": parse_number(fields.get("magnitude_reduction_pct")),
        "status": str(fields.get("status") or "").strip(),
        "implementation_cost": parse_number(fields.get("implementation_cost")),
        "annual_cost": parse_number(fields.get("annual_cost")),
        "owner_ou_id": str(fields.get("owner_ou_id") or "").strip(),
        "framework_reference": str(fields.get("framework_reference") or "").strip(),
        "description": str(fields.get("description") or "").strip(),
    }
