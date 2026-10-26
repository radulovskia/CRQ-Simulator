from crq.catalog.catalog_io import connect, duplicate_ids, number_error, parse_int, parse_number, read_tabular, rename_column, wait_for_database

COLUMNS = (
    "OU ID",
    "Organisational Unit",
    "Primary Responsibilities",
    "Oversight",
    "Headcount",
    "Loaded Hourly Cost",
)

DB_FIELDS = {
    "OU ID": "ou_id",
    "Organisational Unit": "organisational_unit",
    "Primary Responsibilities": "primary_responsibilities",
    "Oversight": "oversight",
    "Headcount": "headcount",
    "Loaded Hourly Cost": "loaded_hourly_cost",
}

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS organisational_units (
    ou_id TEXT PRIMARY KEY,
    organisational_unit TEXT NOT NULL,
    primary_responsibilities TEXT NOT NULL,
    oversight TEXT NOT NULL,
    headcount INTEGER,
    loaded_hourly_cost DOUBLE PRECISION
)
"""

CREATE_META = """
CREATE TABLE IF NOT EXISTS organisational_unit_meta (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    extracted_at TIMESTAMPTZ NOT NULL
)
"""

TOUCH_META = """
INSERT INTO organisational_unit_meta (id, extracted_at)
VALUES (1, NOW())
ON CONFLICT (id) DO UPDATE SET extracted_at = EXCLUDED.extracted_at
"""


def init_units() -> None:
    def apply(connection) -> None:
        connection.execute(CREATE_TABLE)
        connection.execute(CREATE_META)
        connection.execute("ALTER TABLE organisational_units ADD COLUMN IF NOT EXISTS headcount INTEGER")
        rename_column(connection, "organisational_units", "loaded_hourly_cost_eur", "loaded_hourly_cost")
        connection.execute(
            "ALTER TABLE organisational_units ADD COLUMN IF NOT EXISTS loaded_hourly_cost DOUBLE PRECISION"
        )

    wait_for_database(apply)


def list_units() -> dict:
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT ou_id, organisational_unit, primary_responsibilities, oversight,
                   headcount, loaded_hourly_cost
            FROM organisational_units
            ORDER BY ou_id
            """
        ).fetchall()
        meta = connection.execute(
            "SELECT extracted_at FROM organisational_unit_meta WHERE id = 1"
        ).fetchone()
    extracted_at = meta["extracted_at"].isoformat() if meta else None
    return {"items": [dict(row) for row in rows], "extracted_at": extracted_at}


def upload_units(filename: str, content: bytes) -> tuple[int, dict]:
    parsed, error = read_tabular(filename, content, COLUMNS)
    if error:
        return 422, {"ok": False, "error": error}

    duplicate_error = duplicate_ids([values["OU ID"] for _row, values in parsed], "organisational unit IDs")
    if duplicate_error:
        return 422, {"ok": False, "error": duplicate_error}

    review, stored, any_invalid = _review(parsed)
    if any_invalid:
        return 422, {"ok": False, "rows": review}

    with connect() as connection:
        missing = sorted(_referenced_ou_ids(connection) - {row["ou_id"] for row in stored})
    if missing:
        return 422, {
            "ok": False,
            "error": "These organisational unit IDs are still in use and are missing from the file: " + ", ".join(missing),
        }

    _replace(stored)
    listed = list_units()
    return 200, {"ok": True, "count": len(listed["items"]), **listed}


def add_unit(fields: dict) -> tuple[int, dict]:
    errors = _validate_fields(fields)
    if errors:
        return 422, {"ok": False, "errors": errors}
    cleaned = _clean(fields)
    with connect() as connection:
        if _exists(connection, cleaned["ou_id"]):
            return 422, {"ok": False, "errors": {"OU ID": "already exists"}}
        with connection.transaction():
            connection.execute(
                """
                INSERT INTO organisational_units (
                    ou_id, organisational_unit, primary_responsibilities, oversight,
                    headcount, loaded_hourly_cost
                )
                VALUES (
                    %(ou_id)s, %(organisational_unit)s, %(primary_responsibilities)s, %(oversight)s,
                    %(headcount)s, %(loaded_hourly_cost)s
                )
                """,
                cleaned,
            )
            connection.execute(TOUCH_META)
    return 200, {"ok": True, **list_units()}


def update_unit(previous_ou_id: str, fields: dict) -> tuple[int, dict]:
    errors = _validate_fields(fields)
    if errors:
        return 422, {"ok": False, "errors": errors}
    cleaned = _clean(fields)
    previous = previous_ou_id.strip()
    with connect() as connection:
        if not _exists(connection, previous):
            return 404, {"ok": False, "error": "That organisational unit was not found."}
        if cleaned["ou_id"] != previous:
            if previous in _referenced_ou_ids(connection):
                return 422, {
                    "ok": False,
                    "errors": {"OU ID": "is still used by a business process or software system"},
                }
            if _exists(connection, cleaned["ou_id"]):
                return 422, {"ok": False, "errors": {"OU ID": "already exists"}}
        with connection.transaction():
            connection.execute(
                """
                UPDATE organisational_units
                SET ou_id = %(ou_id)s,
                    organisational_unit = %(organisational_unit)s,
                    primary_responsibilities = %(primary_responsibilities)s,
                    oversight = %(oversight)s,
                    headcount = %(headcount)s,
                    loaded_hourly_cost = %(loaded_hourly_cost)s
                WHERE ou_id = %(previous)s
                """,
                {**cleaned, "previous": previous},
            )
            connection.execute(TOUCH_META)
    return 200, {"ok": True, **list_units()}


def delete_unit(ou_id: str) -> tuple[int, dict]:
    previous = ou_id.strip()
    with connect() as connection:
        if not _exists(connection, previous):
            return 404, {"ok": False, "error": "That organisational unit was not found."}
        if previous in _referenced_ou_ids(connection):
            return 422, {
                "ok": False,
                "error": "That organisational unit is still used by a business process, software system, control, or risk scenario.",
            }
        with connection.transaction():
            connection.execute("DELETE FROM organisational_units WHERE ou_id = %s", (previous,))
            connection.execute(TOUCH_META)
    return 200, {"ok": True, **list_units()}


def _referenced_ou_ids(connection) -> set[str]:
    referenced = {
        row["ou_id"]
        for row in connection.execute("SELECT ou_id FROM business_processes").fetchall()
    }
    for row in connection.execute(
        "SELECT business_owner_ou_id, technical_custodian_ou_id FROM software_systems"
    ).fetchall():
        referenced.add(row["business_owner_ou_id"])
        referenced.add(row["technical_custodian_ou_id"])
    for row in connection.execute("SELECT owner_ou_id FROM controls").fetchall():
        referenced.add(row["owner_ou_id"])
    for row in connection.execute("SELECT risk_owner_ou_id FROM risk_scenarios").fetchall():
        referenced.add(row["risk_owner_ou_id"])
    return referenced


def _exists(connection, ou_id: str) -> bool:
    return connection.execute(
        "SELECT ou_id FROM organisational_units WHERE ou_id = %s",
        (ou_id,),
    ).fetchone() is not None


def _replace(rows: list[dict]) -> None:
    with connect() as connection:
        with connection.transaction():
            connection.execute("DELETE FROM organisational_units")
            if rows:
                with connection.cursor() as cursor:
                    cursor.executemany(
                        """
                        INSERT INTO organisational_units (
                            ou_id, organisational_unit, primary_responsibilities, oversight,
                            headcount, loaded_hourly_cost
                        )
                        VALUES (
                            %(ou_id)s, %(organisational_unit)s, %(primary_responsibilities)s, %(oversight)s,
                            %(headcount)s, %(loaded_hourly_cost)s
                        )
                        """,
                        rows,
                    )
            connection.execute(TOUCH_META)


def _review(parsed: list[tuple[int, dict]]) -> tuple[list[dict], list[dict], bool]:
    review = []
    stored = []
    any_invalid = False
    for row_number, values in parsed:
        errors = _validate_values(values)
        if errors:
            any_invalid = True
        review.append({"row": row_number, "values": values, "errors": errors})
        stored.append(_clean({DB_FIELDS[column]: values[column] for column in COLUMNS}))
    return review, stored, any_invalid


def _validate_fields(fields: dict) -> dict:
    return _validate_values(
        {
            "OU ID": str(fields.get("ou_id") or "").strip(),
            "Organisational Unit": str(fields.get("organisational_unit") or "").strip(),
            "Primary Responsibilities": str(fields.get("primary_responsibilities") or "").strip(),
            "Oversight": str(fields.get("oversight") or "").strip(),
            "Headcount": fields.get("headcount") if fields.get("headcount") is not None else "",
            "Loaded Hourly Cost": fields.get("loaded_hourly_cost")
            if fields.get("loaded_hourly_cost") is not None
            else "",
        }
    )


def _validate_values(values: dict) -> dict:
    errors = {column: "must not be empty" for column in COLUMNS[:4] if not str(values[column] or "").strip()}
    headcount_error = number_error(values["Headcount"], allow_blank=True, minimum=0, integer=True)
    if headcount_error:
        errors["Headcount"] = headcount_error
    cost_error = number_error(values["Loaded Hourly Cost"], allow_blank=True, minimum=0)
    if cost_error:
        errors["Loaded Hourly Cost"] = cost_error
    return errors


def _clean(fields: dict) -> dict:
    headcount = fields.get("headcount")
    cost = fields.get("loaded_hourly_cost")
    return {
        "ou_id": str(fields.get("ou_id") or "").strip(),
        "organisational_unit": str(fields.get("organisational_unit") or "").strip(),
        "primary_responsibilities": str(fields.get("primary_responsibilities") or "").strip(),
        "oversight": str(fields.get("oversight") or "").strip(),
        "headcount": parse_int(headcount),
        "loaded_hourly_cost": parse_number(cost),
    }
