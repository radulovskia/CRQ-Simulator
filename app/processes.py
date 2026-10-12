from catalog_io import connect, duplicate_ids, read_tabular, split_ids, wait_for_database

COLUMNS = (
    "BP ID",
    "OU ID",
    "Business Process",
    "Activity/Scope",
    "Primary System IDs",
    "Criticality",
    "Key Information",
)

DB_FIELDS = {
    "BP ID": "bp_id",
    "OU ID": "ou_id",
    "Business Process": "business_process",
    "Activity/Scope": "activity_scope",
    "Primary System IDs": "primary_system_ids",
    "Criticality": "criticality",
    "Key Information": "key_information",
}

CRITICALITY = {"Low", "Medium", "High"}

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS business_processes (
    bp_id TEXT PRIMARY KEY,
    ou_id TEXT NOT NULL,
    business_process TEXT NOT NULL,
    activity_scope TEXT NOT NULL,
    primary_system_ids TEXT NOT NULL,
    criticality TEXT NOT NULL,
    key_information TEXT NOT NULL
)
"""

CREATE_META = """
CREATE TABLE IF NOT EXISTS business_process_meta (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    extracted_at TIMESTAMPTZ NOT NULL
)
"""

TOUCH_META = """
INSERT INTO business_process_meta (id, extracted_at)
VALUES (1, NOW())
ON CONFLICT (id) DO UPDATE SET extracted_at = EXCLUDED.extracted_at
"""


def init_processes() -> None:
    def apply(connection) -> None:
        columns = {
            row["column_name"]
            for row in connection.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'business_processes'
                """
            ).fetchall()
        }
        if columns and "bp_id" not in columns:
            connection.execute("DROP TABLE business_processes")
            connection.execute("DROP TABLE IF EXISTS business_process_meta")
        connection.execute(CREATE_TABLE)
        connection.execute(CREATE_META)

    wait_for_database(apply)


def list_processes() -> dict:
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT bp_id, ou_id, business_process, activity_scope, primary_system_ids,
                   criticality, key_information
            FROM business_processes
            ORDER BY bp_id
            """
        ).fetchall()
        units = {
            row["ou_id"]: row["organisational_unit"]
            for row in connection.execute(
                "SELECT ou_id, organisational_unit FROM organisational_units"
            ).fetchall()
        }
        systems = {
            row["system_id"]: row["software_system"]
            for row in connection.execute(
                "SELECT system_id, software_system FROM software_systems"
            ).fetchall()
        }
        meta = connection.execute(
            "SELECT extracted_at FROM business_process_meta WHERE id = 1"
        ).fetchone()
    extracted_at = meta["extracted_at"].isoformat() if meta else None
    items = []
    for row in rows:
        item = dict(row)
        item["organisational_unit"] = units.get(row["ou_id"], "")
        item["software_systems"] = ", ".join(
            systems.get(system_id, "") for system_id in split_ids(row["primary_system_ids"])
        )
        items.append(item)
    return {"items": items, "extracted_at": extracted_at}


def upload_processes(filename: str, content: bytes) -> tuple[int, dict]:
    parsed, error = read_tabular(filename, content, COLUMNS)
    if error:
        return 422, {"ok": False, "error": error}

    duplicate_error = duplicate_ids([values["BP ID"] for _row, values in parsed], "BP IDs")
    if duplicate_error:
        return 422, {"ok": False, "error": duplicate_error}

    with connect() as connection:
        ou_ids = _ou_ids(connection)
        system_ids = _system_ids(connection)
    review, stored, any_invalid = _review(parsed, ou_ids, system_ids)
    if any_invalid:
        return 422, {"ok": False, "rows": review}

    _replace(stored)
    listed = list_processes()
    return 200, {"ok": True, "count": len(listed["items"]), **listed}


def add_process(fields: dict) -> tuple[int, dict]:
    with connect() as connection:
        errors = _validate_fields(fields, _ou_ids(connection), _system_ids(connection))
        if errors:
            return 422, {"ok": False, "errors": errors}
        cleaned = _clean(fields)
        if _exists(connection, cleaned["bp_id"]):
            return 422, {"ok": False, "errors": {"BP ID": "already exists"}}
        with connection.transaction():
            _insert(connection, cleaned)
            connection.execute(TOUCH_META)
    return 200, {"ok": True, **list_processes()}


def update_process(previous_bp_id: str, fields: dict) -> tuple[int, dict]:
    previous = previous_bp_id.strip()
    with connect() as connection:
        errors = _validate_fields(fields, _ou_ids(connection), _system_ids(connection))
        if errors:
            return 422, {"ok": False, "errors": errors}
        cleaned = _clean(fields)
        if not _exists(connection, previous):
            return 404, {"ok": False, "error": "That business process was not found."}
        if cleaned["bp_id"] != previous and _exists(connection, cleaned["bp_id"]):
            return 422, {"ok": False, "errors": {"BP ID": "already exists"}}
        with connection.transaction():
            connection.execute(
                """
                UPDATE business_processes
                SET bp_id = %(bp_id)s,
                    ou_id = %(ou_id)s,
                    business_process = %(business_process)s,
                    activity_scope = %(activity_scope)s,
                    primary_system_ids = %(primary_system_ids)s,
                    criticality = %(criticality)s,
                    key_information = %(key_information)s
                WHERE bp_id = %(previous)s
                """,
                {**cleaned, "previous": previous},
            )
            connection.execute(TOUCH_META)
    return 200, {"ok": True, **list_processes()}


def _ou_ids(connection) -> set[str]:
    return {
        row["ou_id"]
        for row in connection.execute("SELECT ou_id FROM organisational_units").fetchall()
    }


def _system_ids(connection) -> set[str]:
    return {
        row["system_id"]
        for row in connection.execute("SELECT system_id FROM software_systems").fetchall()
    }


def _exists(connection, bp_id: str) -> bool:
    return connection.execute(
        "SELECT bp_id FROM business_processes WHERE bp_id = %s",
        (bp_id,),
    ).fetchone() is not None


def _insert(connection, row: dict) -> None:
    connection.execute(
        """
        INSERT INTO business_processes (
            bp_id, ou_id, business_process, activity_scope, primary_system_ids,
            criticality, key_information
        )
        VALUES (
            %(bp_id)s, %(ou_id)s, %(business_process)s, %(activity_scope)s, %(primary_system_ids)s,
            %(criticality)s, %(key_information)s
        )
        """,
        row,
    )


def _replace(rows: list[dict]) -> None:
    with connect() as connection:
        with connection.transaction():
            connection.execute("DELETE FROM business_processes")
            for row in rows:
                _insert(connection, row)
            connection.execute(TOUCH_META)


def _review(
    parsed: list[tuple[int, dict]],
    ou_ids: set[str],
    system_ids: set[str],
) -> tuple[list[dict], list[dict], bool]:
    review = []
    stored = []
    any_invalid = False
    for row_number, values in parsed:
        errors = _validate_values(values, ou_ids, system_ids)
        if errors:
            any_invalid = True
        review.append({"row": row_number, "values": values, "errors": errors})
        stored.append(_clean({DB_FIELDS[column]: values[column] for column in COLUMNS}))
    return review, stored, any_invalid


def _validate_fields(fields: dict, ou_ids: set[str], system_ids: set[str]) -> dict:
    cleaned = _clean(fields)
    return _validate_values(
        {
            "BP ID": cleaned["bp_id"],
            "OU ID": cleaned["ou_id"],
            "Business Process": cleaned["business_process"],
            "Activity/Scope": cleaned["activity_scope"],
            "Primary System IDs": cleaned["primary_system_ids"],
            "Criticality": cleaned["criticality"],
            "Key Information": cleaned["key_information"],
        },
        ou_ids,
        system_ids,
    )


def _validate_values(values: dict, ou_ids: set[str], system_ids: set[str]) -> dict:
    errors = {}
    for column in ("BP ID", "Business Process", "Activity/Scope", "Key Information"):
        if not values[column]:
            errors[column] = "must not be empty"
    if not values["OU ID"]:
        errors["OU ID"] = "must not be empty"
    elif values["OU ID"] not in ou_ids:
        errors["OU ID"] = "must be an existing OU ID"
    if values["Criticality"] not in CRITICALITY:
        errors["Criticality"] = 'must be "Low", "Medium", or "High"'
    system_error = _system_list_error(values["Primary System IDs"], system_ids)
    if system_error:
        errors["Primary System IDs"] = system_error
    return errors


def _system_list_error(value: str, system_ids: set[str]) -> str | None:
    if not str(value or "").strip():
        return "must not be empty"
    raw = [part.strip() for part in str(value).split(",")]
    if any(not part for part in raw):
        return "must contain only existing System IDs"
    if len(raw) != len(set(raw)):
        return "contains duplicate System IDs"
    unknown = [part for part in raw if part not in system_ids]
    if unknown:
        return "unknown System IDs: " + ", ".join(unknown)
    return None


def _clean(fields: dict) -> dict:
    system_ids = split_ids(fields.get("primary_system_ids") or "")
    return {
        "bp_id": str(fields.get("bp_id") or "").strip(),
        "ou_id": str(fields.get("ou_id") or "").strip(),
        "business_process": str(fields.get("business_process") or "").strip(),
        "activity_scope": str(fields.get("activity_scope") or "").strip(),
        "primary_system_ids": ", ".join(system_ids),
        "criticality": str(fields.get("criticality") or "").strip(),
        "key_information": str(fields.get("key_information") or "").strip(),
    }
