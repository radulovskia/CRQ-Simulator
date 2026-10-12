from packageurl import PackageURL

from catalog_io import connect, duplicate_ids, read_tabular, wait_for_database

COLUMNS = ("Component ID", "System ID", "PURL")

DB_FIELDS = {
    "Component ID": "component_id",
    "System ID": "system_id",
    "PURL": "purl",
}

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS software_components (
    component_id TEXT PRIMARY KEY,
    system_id TEXT NOT NULL,
    purl TEXT NOT NULL
)
"""

CREATE_META = """
CREATE TABLE IF NOT EXISTS software_component_meta (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    extracted_at TIMESTAMPTZ NOT NULL
)
"""


def init_db() -> None:
    def apply(connection) -> None:
        connection.execute("DROP TABLE IF EXISTS assets")
        connection.execute("DROP TABLE IF EXISTS inventory_meta")
        connection.execute(CREATE_TABLE)
        connection.execute(CREATE_META)

    wait_for_database(apply)


def list_inventory() -> dict:
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT component_id, system_id, purl
            FROM software_components
            ORDER BY component_id
            """
        ).fetchall()
        systems = {
            row["system_id"]: row["software_system"]
            for row in connection.execute(
                "SELECT system_id, software_system FROM software_systems"
            ).fetchall()
        }
        meta = connection.execute(
            "SELECT extracted_at FROM software_component_meta WHERE id = 1"
        ).fetchone()
    extracted_at = meta["extracted_at"].isoformat() if meta else None
    items = []
    for row in rows:
        item = dict(row)
        item["software_system"] = systems.get(row["system_id"], "")
        items.append(item)
    return {"items": items, "extracted_at": extracted_at}


def replace_inventory(rows: list[dict]) -> None:
    with connect() as connection:
        with connection.transaction():
            connection.execute("DELETE FROM software_components")
            with connection.cursor() as cursor:
                cursor.executemany(
                    """
                    INSERT INTO software_components (component_id, system_id, purl)
                    VALUES (%(component_id)s, %(system_id)s, %(purl)s)
                    """,
                    rows,
                )
            connection.execute(
                """
                INSERT INTO software_component_meta (id, extracted_at)
                VALUES (1, NOW())
                ON CONFLICT (id) DO UPDATE SET extracted_at = EXCLUDED.extracted_at
                """
            )


def process_upload(filename: str, content: bytes) -> tuple[int, dict]:
    parsed, error = read_tabular(filename, content, COLUMNS)
    if error:
        return 422, {"ok": False, "error": error}

    duplicate_error = duplicate_ids([values["Component ID"] for _row, values in parsed], "Component IDs")
    if duplicate_error:
        return 422, {"ok": False, "error": duplicate_error}

    with connect() as connection:
        known = {
            row["system_id"]
            for row in connection.execute("SELECT system_id FROM software_systems").fetchall()
        }

    review = []
    stored = []
    any_invalid = False
    for row_number, values in parsed:
        errors = _validate_row(values, known)
        if errors:
            any_invalid = True
        review.append({"row": row_number, "values": values, "errors": errors})
        stored.append({DB_FIELDS[column]: values[column] for column in COLUMNS})

    if any_invalid:
        return 422, {"ok": False, "rows": review}

    replace_inventory(stored)
    return 200, {"ok": True, "count": len(stored)}


def _validate_row(values: dict, known_systems: set[str]) -> dict:
    errors = {}
    if not values["Component ID"]:
        errors["Component ID"] = "must not be empty"

    system_id = values["System ID"]
    if not system_id:
        errors["System ID"] = "must not be empty"
    elif system_id not in known_systems:
        errors["System ID"] = "must be an existing System ID"

    purl = values["PURL"]
    if not purl:
        errors["PURL"] = "not a valid PURL"
    else:
        try:
            PackageURL.from_string(purl)
        except ValueError:
            errors["PURL"] = "not a valid PURL"
    return errors
