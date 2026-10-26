from crq.catalog.catalog_io import (
    connect,
    duplicate_ids,
    enum_error,
    number_error,
    parse_int,
    parse_number,
    read_tabular,
    rename_column,
    wait_for_database,
)

COLUMNS = (
    "System ID",
    "Software System",
    "Primary Function",
    "Business Owner OU ID",
    "Technical Custodian OU ID",
    "Criticality",
    "Data Classification",
    "Deployment",
    "Internet Facing",
    "Replacement Cost",
    "Records Held",
)

DB_FIELDS = {
    "System ID": "system_id",
    "Software System": "software_system",
    "Primary Function": "primary_function",
    "Business Owner OU ID": "business_owner_ou_id",
    "Technical Custodian OU ID": "technical_custodian_ou_id",
    "Criticality": "criticality",
    "Data Classification": "data_classification",
    "Deployment": "deployment",
    "Internet Facing": "internet_facing",
    "Replacement Cost": "replacement_cost",
    "Records Held": "records_held",
}

CRITICALITY = ("Low", "Medium", "High")
CLASSIFICATION = ("Public", "Internal", "Confidential")
DEPLOYMENT = ("Local", "Cloud", "Hybrid")
FACING = ("Yes", "No", "Unknown")

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS software_systems (
    system_id TEXT PRIMARY KEY,
    software_system TEXT NOT NULL,
    primary_function TEXT NOT NULL,
    business_owner_ou_id TEXT NOT NULL,
    technical_custodian_ou_id TEXT NOT NULL,
    criticality TEXT NOT NULL,
    data_classification TEXT NOT NULL,
    deployment TEXT NOT NULL,
    internet_facing TEXT NOT NULL DEFAULT 'Unknown',
    replacement_cost DOUBLE PRECISION,
    records_held INTEGER
)
"""

CREATE_META = """
CREATE TABLE IF NOT EXISTS software_system_meta (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    extracted_at TIMESTAMPTZ NOT NULL
)
"""

TOUCH_META = """
INSERT INTO software_system_meta (id, extracted_at)
VALUES (1, NOW())
ON CONFLICT (id) DO UPDATE SET extracted_at = EXCLUDED.extracted_at
"""


def init_systems() -> None:
    def apply(connection) -> None:
        connection.execute(CREATE_TABLE)
        connection.execute(CREATE_META)
        connection.execute(
            "ALTER TABLE software_systems ADD COLUMN IF NOT EXISTS internet_facing TEXT DEFAULT 'Unknown'"
        )
        connection.execute(
            "UPDATE software_systems SET internet_facing = 'Unknown' WHERE internet_facing IS NULL"
        )
        connection.execute("ALTER TABLE software_systems ALTER COLUMN internet_facing SET NOT NULL")
        rename_column(connection, "software_systems", "replacement_cost_eur", "replacement_cost")
        connection.execute(
            "ALTER TABLE software_systems ADD COLUMN IF NOT EXISTS replacement_cost DOUBLE PRECISION"
        )
        connection.execute("ALTER TABLE software_systems ADD COLUMN IF NOT EXISTS records_held INTEGER")

    wait_for_database(apply)


def list_systems() -> dict:
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT system_id, software_system, primary_function, business_owner_ou_id,
                   technical_custodian_ou_id, criticality, data_classification, deployment,
                   internet_facing, replacement_cost, records_held
            FROM software_systems
            ORDER BY system_id
            """
        ).fetchall()
        units = {
            row["ou_id"]: row["organisational_unit"]
            for row in connection.execute(
                "SELECT ou_id, organisational_unit FROM organisational_units"
            ).fetchall()
        }
        meta = connection.execute(
            "SELECT extracted_at FROM software_system_meta WHERE id = 1"
        ).fetchone()
    extracted_at = meta["extracted_at"].isoformat() if meta else None
    items = []
    for row in rows:
        item = dict(row)
        item["business_owner_ou"] = units.get(row["business_owner_ou_id"], "")
        item["technical_custodian_ou"] = units.get(row["technical_custodian_ou_id"], "")
        items.append(item)
    return {"items": items, "extracted_at": extracted_at}


def upload_systems(filename: str, content: bytes) -> tuple[int, dict]:
    parsed, error = read_tabular(filename, content, COLUMNS)
    if error:
        return 422, {"ok": False, "error": error}

    duplicate_error = duplicate_ids([values["System ID"] for _row, values in parsed], "System IDs")
    if duplicate_error:
        return 422, {"ok": False, "error": duplicate_error}

    with connect() as connection:
        ou_ids = _ou_ids(connection)
    review, stored, any_invalid = _review(parsed, ou_ids)
    if any_invalid:
        return 422, {"ok": False, "rows": review}

    with connect() as connection:
        missing = sorted(_referenced_system_ids(connection) - {row["system_id"] for row in stored})
    if missing:
        return 422, {
            "ok": False,
            "error": "These System IDs are still in use and are missing from the file: " + ", ".join(missing),
        }

    _replace(stored)
    listed = list_systems()
    return 200, {"ok": True, "count": len(listed["items"]), **listed}


def add_system(fields: dict) -> tuple[int, dict]:
    with connect() as connection:
        errors = _validate_fields(fields, _ou_ids(connection))
        if errors:
            return 422, {"ok": False, "errors": errors}
        cleaned = _clean(fields)
        if _exists(connection, cleaned["system_id"]):
            return 422, {"ok": False, "errors": {"System ID": "already exists"}}
        with connection.transaction():
            _insert(connection, cleaned)
            connection.execute(TOUCH_META)
    return 200, {"ok": True, **list_systems()}


def update_system(previous_system_id: str, fields: dict) -> tuple[int, dict]:
    previous = previous_system_id.strip()
    with connect() as connection:
        errors = _validate_fields(fields, _ou_ids(connection))
        if errors:
            return 422, {"ok": False, "errors": errors}
        cleaned = _clean(fields)
        if not _exists(connection, previous):
            return 404, {"ok": False, "error": "That software system was not found."}
        if cleaned["system_id"] != previous:
            if previous in _rename_blocked_system_ids(connection):
                return 422, {
                    "ok": False,
                    "errors": {"System ID": "is still used by a software component or risk scenario"},
                }
            if _exists(connection, cleaned["system_id"]):
                return 422, {"ok": False, "errors": {"System ID": "already exists"}}
        with connection.transaction():
            connection.execute(
                """
                UPDATE software_systems
                SET system_id = %(system_id)s,
                    software_system = %(software_system)s,
                    primary_function = %(primary_function)s,
                    business_owner_ou_id = %(business_owner_ou_id)s,
                    technical_custodian_ou_id = %(technical_custodian_ou_id)s,
                    criticality = %(criticality)s,
                    data_classification = %(data_classification)s,
                    deployment = %(deployment)s,
                    internet_facing = %(internet_facing)s,
                    replacement_cost = %(replacement_cost)s,
                    records_held = %(records_held)s
                WHERE system_id = %(previous)s
                """,
                {**cleaned, "previous": previous},
            )
            if cleaned["system_id"] != previous:
                connection.execute(
                    "UPDATE process_systems SET system_id = %s WHERE system_id = %s",
                    (cleaned["system_id"], previous),
                )
            connection.execute(TOUCH_META)
    return 200, {"ok": True, **list_systems()}


def delete_system(system_id: str) -> tuple[int, dict]:
    previous = system_id.strip()
    with connect() as connection:
        if not _exists(connection, previous):
            return 404, {"ok": False, "error": "That software system was not found."}
        if previous in _referenced_system_ids(connection):
            return 422, {
                "ok": False,
                "error": "That software system is still used by a business process, software component, or risk scenario.",
            }
        with connection.transaction():
            connection.execute("DELETE FROM software_systems WHERE system_id = %s", (previous,))
            connection.execute(TOUCH_META)
    return 200, {"ok": True, **list_systems()}


def _referenced_system_ids(connection) -> set[str]:
    referenced = _rename_blocked_system_ids(connection)
    for row in connection.execute("SELECT system_id FROM process_systems").fetchall():
        referenced.add(row["system_id"])
    return referenced


def _rename_blocked_system_ids(connection) -> set[str]:
    referenced = set()
    for row in connection.execute("SELECT system_id FROM software_components").fetchall():
        referenced.add(row["system_id"])
    for row in connection.execute(
        "SELECT target_id FROM risk_scenarios WHERE target_type = 'Software System'"
    ).fetchall():
        referenced.add(row["target_id"])
    return referenced


def _ou_ids(connection) -> set[str]:
    return {
        row["ou_id"]
        for row in connection.execute("SELECT ou_id FROM organisational_units").fetchall()
    }


def _exists(connection, system_id: str) -> bool:
    return connection.execute(
        "SELECT system_id FROM software_systems WHERE system_id = %s",
        (system_id,),
    ).fetchone() is not None


def _insert(connection, row: dict) -> None:
    connection.execute(
        """
        INSERT INTO software_systems (
            system_id, software_system, primary_function, business_owner_ou_id,
            technical_custodian_ou_id, criticality, data_classification, deployment,
            internet_facing, replacement_cost, records_held
        )
        VALUES (
            %(system_id)s, %(software_system)s, %(primary_function)s, %(business_owner_ou_id)s,
            %(technical_custodian_ou_id)s, %(criticality)s, %(data_classification)s, %(deployment)s,
            %(internet_facing)s, %(replacement_cost)s, %(records_held)s
        )
        """,
        row,
    )


def _replace(rows: list[dict]) -> None:
    with connect() as connection:
        with connection.transaction():
            connection.execute("DELETE FROM software_systems")
            for row in rows:
                _insert(connection, row)
            connection.execute(TOUCH_META)


def _review(parsed: list[tuple[int, dict]], ou_ids: set[str]) -> tuple[list[dict], list[dict], bool]:
    review = []
    stored = []
    any_invalid = False
    for row_number, values in parsed:
        errors = _validate_values(values, ou_ids)
        if errors:
            any_invalid = True
        review.append({"row": row_number, "values": values, "errors": errors})
        stored.append(_clean(_fields_from_row(values)))
    return review, stored, any_invalid


def _fields_from_row(values: dict) -> dict:
    return {DB_FIELDS[column]: values[column] for column in COLUMNS}


def _validate_fields(fields: dict, ou_ids: set[str]) -> dict:
    facing = str(fields.get("internet_facing") or "").strip() or "Unknown"
    return _validate_values(
        {
            "System ID": str(fields.get("system_id") or "").strip(),
            "Software System": str(fields.get("software_system") or "").strip(),
            "Primary Function": str(fields.get("primary_function") or "").strip(),
            "Business Owner OU ID": str(fields.get("business_owner_ou_id") or "").strip(),
            "Technical Custodian OU ID": str(fields.get("technical_custodian_ou_id") or "").strip(),
            "Criticality": str(fields.get("criticality") or "").strip(),
            "Data Classification": str(fields.get("data_classification") or "").strip(),
            "Deployment": str(fields.get("deployment") or "").strip(),
            "Internet Facing": facing,
            "Replacement Cost": fields.get("replacement_cost")
            if fields.get("replacement_cost") is not None
            else "",
            "Records Held": fields.get("records_held") if fields.get("records_held") is not None else "",
        },
        ou_ids,
    )


def _validate_values(values: dict, ou_ids: set[str]) -> dict:
    errors = {}
    for column in ("System ID", "Software System", "Primary Function"):
        if not str(values[column] or "").strip():
            errors[column] = "must not be empty"
    for column in ("Business Owner OU ID", "Technical Custodian OU ID"):
        if not str(values[column] or "").strip():
            errors[column] = "must not be empty"
        elif str(values[column]).strip() not in ou_ids:
            errors[column] = "must be an existing organisational unit"
    criticality = enum_error(str(values["Criticality"] or "").strip(), CRITICALITY)
    if criticality:
        errors["Criticality"] = criticality
    classification = enum_error(str(values["Data Classification"] or "").strip(), CLASSIFICATION)
    if classification:
        errors["Data Classification"] = classification
    deployment = enum_error(str(values["Deployment"] or "").strip(), DEPLOYMENT)
    if deployment:
        errors["Deployment"] = deployment
    facing = str(values["Internet Facing"] or "").strip() or "Unknown"
    facing_error = enum_error(facing, FACING)
    if facing_error:
        errors["Internet Facing"] = facing_error
    cost_error = number_error(values["Replacement Cost"], allow_blank=True, minimum=0)
    if cost_error:
        errors["Replacement Cost"] = cost_error
    records_error = number_error(values["Records Held"], allow_blank=True, minimum=0, integer=True)
    if records_error:
        errors["Records Held"] = records_error
    return errors


def _clean(fields: dict) -> dict:
    facing = str(fields.get("internet_facing") or "").strip() or "Unknown"
    return {
        "system_id": str(fields.get("system_id") or "").strip(),
        "software_system": str(fields.get("software_system") or "").strip(),
        "primary_function": str(fields.get("primary_function") or "").strip(),
        "business_owner_ou_id": str(fields.get("business_owner_ou_id") or "").strip(),
        "technical_custodian_ou_id": str(fields.get("technical_custodian_ou_id") or "").strip(),
        "criticality": str(fields.get("criticality") or "").strip(),
        "data_classification": str(fields.get("data_classification") or "").strip(),
        "deployment": str(fields.get("deployment") or "").strip(),
        "internet_facing": facing,
        "replacement_cost": parse_number(fields.get("replacement_cost")),
        "records_held": parse_int(fields.get("records_held")),
    }
