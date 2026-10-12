from catalog_io import connect, duplicate_ids, read_tabular, split_ids, wait_for_database

COLUMNS = (
    "System ID",
    "Software System",
    "Primary Function",
    "Business Owner OU ID",
    "Technical Custodian OU ID",
    "Criticality",
    "Data Classification",
    "Deployment",
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
}

CRITICALITY = {"Low", "Medium", "High"}
CLASSIFICATION = {"Public", "Internal", "Confidential"}

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS software_systems (
    system_id TEXT PRIMARY KEY,
    software_system TEXT NOT NULL,
    primary_function TEXT NOT NULL,
    business_owner_ou_id TEXT NOT NULL,
    technical_custodian_ou_id TEXT NOT NULL,
    criticality TEXT NOT NULL,
    data_classification TEXT NOT NULL,
    deployment TEXT NOT NULL
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

    wait_for_database(apply)


def list_systems() -> dict:
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT system_id, software_system, primary_function, business_owner_ou_id,
                   technical_custodian_ou_id, criticality, data_classification, deployment
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
            if previous in _referenced_system_ids(connection):
                return 422, {
                    "ok": False,
                    "errors": {"System ID": "is still used by a business process"},
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
                    deployment = %(deployment)s
                WHERE system_id = %(previous)s
                """,
                {**cleaned, "previous": previous},
            )
            connection.execute(TOUCH_META)
    return 200, {"ok": True, **list_systems()}


def _referenced_system_ids(connection) -> set[str]:
    referenced = set()
    for row in connection.execute("SELECT primary_system_ids FROM business_processes").fetchall():
        referenced.update(split_ids(row["primary_system_ids"]))
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
            technical_custodian_ou_id, criticality, data_classification, deployment
        )
        VALUES (
            %(system_id)s, %(software_system)s, %(primary_function)s, %(business_owner_ou_id)s,
            %(technical_custodian_ou_id)s, %(criticality)s, %(data_classification)s, %(deployment)s
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
        stored.append(_clean({DB_FIELDS[column]: values[column] for column in COLUMNS}))
    return review, stored, any_invalid


def _validate_fields(fields: dict, ou_ids: set[str]) -> dict:
    cleaned = _clean(fields)
    return _validate_values(
        {
            "System ID": cleaned["system_id"],
            "Software System": cleaned["software_system"],
            "Primary Function": cleaned["primary_function"],
            "Business Owner OU ID": cleaned["business_owner_ou_id"],
            "Technical Custodian OU ID": cleaned["technical_custodian_ou_id"],
            "Criticality": cleaned["criticality"],
            "Data Classification": cleaned["data_classification"],
            "Deployment": cleaned["deployment"],
        },
        ou_ids,
    )


def _validate_values(values: dict, ou_ids: set[str]) -> dict:
    errors = {}
    for column in ("System ID", "Software System", "Primary Function", "Deployment"):
        if not values[column]:
            errors[column] = "must not be empty"
    for column in ("Business Owner OU ID", "Technical Custodian OU ID"):
        if not values[column]:
            errors[column] = "must not be empty"
        elif values[column] not in ou_ids:
            errors[column] = "must be an existing OU ID"
    if values["Criticality"] not in CRITICALITY:
        errors["Criticality"] = 'must be "Low", "Medium", or "High"'
    if values["Data Classification"] not in CLASSIFICATION:
        errors["Data Classification"] = 'must be "Public", "Internal", or "Confidential"'
    return errors


def _clean(fields: dict) -> dict:
    return {
        "system_id": str(fields.get("system_id") or "").strip(),
        "software_system": str(fields.get("software_system") or "").strip(),
        "primary_function": str(fields.get("primary_function") or "").strip(),
        "business_owner_ou_id": str(fields.get("business_owner_ou_id") or "").strip(),
        "technical_custodian_ou_id": str(fields.get("technical_custodian_ou_id") or "").strip(),
        "criticality": str(fields.get("criticality") or "").strip(),
        "data_classification": str(fields.get("data_classification") or "").strip(),
        "deployment": str(fields.get("deployment") or "").strip(),
    }
