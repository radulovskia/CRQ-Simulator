from crq.catalog.catalog_io import (
    connect,
    duplicate_ids,
    enum_error,
    number_error,
    parse_int,
    parse_number,
    read_tabular,
    rename_column,
    split_ids,
    wait_for_database,
)

COLUMNS = (
    "BP ID",
    "OU ID",
    "Business Process",
    "Activity/Scope",
    "Primary System IDs",
    "Criticality",
    "Key Information",
    "RTO (hours)",
    "Downtime Cost per Hour before RTO",
    "Downtime Cost per Hour post RTO",
    "FTE Count",
)

DB_FIELDS = {
    "BP ID": "bp_id",
    "OU ID": "ou_id",
    "Business Process": "business_process",
    "Activity/Scope": "activity_scope",
    "Primary System IDs": "primary_system_ids",
    "Criticality": "criticality",
    "Key Information": "key_information",
    "RTO (hours)": "rto_hours",
    "Downtime Cost per Hour before RTO": "downtime_cost_per_hour",
    "Downtime Cost per Hour post RTO": "downtime_cost_per_hour_post_rto",
    "FTE Count": "fte_count",
}

CRITICALITY = ("Low", "Medium", "High")

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS business_processes (
    bp_id TEXT PRIMARY KEY,
    ou_id TEXT NOT NULL,
    business_process TEXT NOT NULL,
    activity_scope TEXT NOT NULL,
    criticality TEXT NOT NULL,
    key_information TEXT NOT NULL,
    downtime_cost_per_hour DOUBLE PRECISION,
    downtime_cost_per_hour_post_rto DOUBLE PRECISION,
    rto_hours DOUBLE PRECISION,
    fte_count INTEGER
)
"""

CREATE_LINKS = """
CREATE TABLE IF NOT EXISTS process_systems (
    bp_id TEXT NOT NULL,
    system_id TEXT NOT NULL,
    PRIMARY KEY (bp_id, system_id)
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
        columns = _process_columns(connection)
        if columns and "bp_id" not in columns:
            connection.execute("DROP TABLE business_processes")
            connection.execute("DROP TABLE IF EXISTS business_process_meta")
            connection.execute("DROP TABLE IF EXISTS process_systems")
        connection.execute(CREATE_TABLE)
        connection.execute(CREATE_LINKS)
        connection.execute(CREATE_META)
        rename_column(connection, "business_processes", "downtime_cost_per_hour_eur", "downtime_cost_per_hour")
        rename_column(
            connection,
            "business_processes",
            "downtime_cost_per_hour_post_rto_eur",
            "downtime_cost_per_hour_post_rto",
        )
        connection.execute(
            "ALTER TABLE business_processes ADD COLUMN IF NOT EXISTS downtime_cost_per_hour DOUBLE PRECISION"
        )
        connection.execute(
            "ALTER TABLE business_processes ADD COLUMN IF NOT EXISTS downtime_cost_per_hour_post_rto DOUBLE PRECISION"
        )
        connection.execute("ALTER TABLE business_processes ADD COLUMN IF NOT EXISTS rto_hours DOUBLE PRECISION")
        connection.execute("ALTER TABLE business_processes ADD COLUMN IF NOT EXISTS fte_count INTEGER")
        if "primary_system_ids" in _process_columns(connection):
            for row in connection.execute("SELECT bp_id, primary_system_ids FROM business_processes").fetchall():
                for system_id in split_ids(row["primary_system_ids"] or ""):
                    connection.execute(
                        """
                        INSERT INTO process_systems (bp_id, system_id)
                        VALUES (%s, %s)
                        ON CONFLICT (bp_id, system_id) DO NOTHING
                        """,
                        (row["bp_id"], system_id),
                    )
            connection.execute("ALTER TABLE business_processes DROP COLUMN primary_system_ids")

    wait_for_database(apply)


def list_processes() -> dict:
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT p.bp_id, p.ou_id, p.business_process, p.activity_scope, p.criticality,
                   p.key_information, p.downtime_cost_per_hour, p.downtime_cost_per_hour_post_rto,
                   p.rto_hours, p.fte_count,
                   COALESCE(links.primary_system_ids, '') AS primary_system_ids,
                   COALESCE(links.software_systems, '') AS software_systems
            FROM business_processes p
            LEFT JOIN (
                SELECT ps.bp_id,
                       string_agg(ps.system_id, ', ' ORDER BY ps.system_id) AS primary_system_ids,
                       string_agg(COALESCE(s.software_system, ''), ', ' ORDER BY ps.system_id) AS software_systems
                FROM process_systems ps
                LEFT JOIN software_systems s ON s.system_id = ps.system_id
                GROUP BY ps.bp_id
            ) links ON links.bp_id = p.bp_id
            ORDER BY p.bp_id
            """
        ).fetchall()
        units = {
            row["ou_id"]: row["organisational_unit"]
            for row in connection.execute(
                "SELECT ou_id, organisational_unit FROM organisational_units"
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
        stored_post = item["downtime_cost_per_hour_post_rto"]
        item["downtime_cost_post_rto_effective"] = (
            item["downtime_cost_per_hour"] if stored_post is None else stored_post
        )
        items.append(item)
    return {"items": items, "extracted_at": extracted_at}


def upload_processes(filename: str, content: bytes) -> tuple[int, dict]:
    parsed, error = read_tabular(filename, content, COLUMNS)
    if error:
        return 422, {"ok": False, "error": error}

    duplicate_error = duplicate_ids([values["BP ID"] for _row, values in parsed], "business process IDs")
    if duplicate_error:
        return 422, {"ok": False, "error": duplicate_error}

    with connect() as connection:
        ou_ids = _ou_ids(connection)
        system_ids = _system_ids(connection)
        headcounts = _ou_headcounts(connection)
    review, stored, any_invalid = _review(parsed, ou_ids, system_ids, headcounts)
    if any_invalid:
        return 422, {"ok": False, "rows": review}

    with connect() as connection:
        missing = sorted(_referenced_bp_ids(connection) - {row["bp_id"] for row in stored})
    if missing:
        return 422, {
            "ok": False,
            "error": "These business process IDs are still in use and are missing from the file: " + ", ".join(missing),
        }

    _replace(stored)
    listed = list_processes()
    return 200, {"ok": True, "count": len(listed["items"]), **listed}


def add_process(fields: dict) -> tuple[int, dict]:
    with connect() as connection:
        errors = _validate_fields(fields, _ou_ids(connection), _system_ids(connection), _ou_headcounts(connection))
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
        errors = _validate_fields(fields, _ou_ids(connection), _system_ids(connection), _ou_headcounts(connection))
        if errors:
            return 422, {"ok": False, "errors": errors}
        cleaned = _clean(fields)
        if not _exists(connection, previous):
            return 404, {"ok": False, "error": "That business process was not found."}
        if cleaned["bp_id"] != previous:
            if previous in _referenced_bp_ids(connection):
                return 422, {"ok": False, "errors": {"BP ID": "is still used by a risk scenario"}}
            if _exists(connection, cleaned["bp_id"]):
                return 422, {"ok": False, "errors": {"BP ID": "already exists"}}
        with connection.transaction():
            connection.execute(
                """
                UPDATE business_processes
                SET bp_id = %(bp_id)s,
                    ou_id = %(ou_id)s,
                    business_process = %(business_process)s,
                    activity_scope = %(activity_scope)s,
                    criticality = %(criticality)s,
                    key_information = %(key_information)s,
                    downtime_cost_per_hour = %(downtime_cost_per_hour)s,
                    downtime_cost_per_hour_post_rto = %(downtime_cost_per_hour_post_rto)s,
                    rto_hours = %(rto_hours)s,
                    fte_count = %(fte_count)s
                WHERE bp_id = %(previous)s
                """,
                {**cleaned, "previous": previous},
            )
            connection.execute("DELETE FROM process_systems WHERE bp_id = %s", (previous,))
            _insert_links(connection, cleaned["bp_id"], cleaned["system_ids"])
            connection.execute(TOUCH_META)
    return 200, {"ok": True, **list_processes()}


def delete_process(bp_id: str) -> tuple[int, dict]:
    previous = bp_id.strip()
    with connect() as connection:
        if not _exists(connection, previous):
            return 404, {"ok": False, "error": "That business process was not found."}
        if previous in _referenced_bp_ids(connection):
            return 422, {"ok": False, "error": "That business process is still used by a risk scenario."}
        with connection.transaction():
            connection.execute("DELETE FROM process_systems WHERE bp_id = %s", (previous,))
            connection.execute("DELETE FROM business_processes WHERE bp_id = %s", (previous,))
            connection.execute(TOUCH_META)
    return 200, {"ok": True, **list_processes()}


def _process_columns(connection) -> set[str]:
    return {
        row["column_name"]
        for row in connection.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'business_processes'
            """
        ).fetchall()
    }


def _ou_ids(connection) -> set[str]:
    return {
        row["ou_id"]
        for row in connection.execute("SELECT ou_id FROM organisational_units").fetchall()
    }


def _referenced_bp_ids(connection) -> set[str]:
    return {
        row["target_id"]
        for row in connection.execute(
            "SELECT target_id FROM risk_scenarios WHERE target_type = 'Business Process'"
        ).fetchall()
    }


def _ou_headcounts(connection) -> dict[str, int | None]:
    return {
        row["ou_id"]: row["headcount"]
        for row in connection.execute("SELECT ou_id, headcount FROM organisational_units").fetchall()
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
            bp_id, ou_id, business_process, activity_scope, criticality, key_information,
            downtime_cost_per_hour, downtime_cost_per_hour_post_rto, rto_hours, fte_count
        )
        VALUES (
            %(bp_id)s, %(ou_id)s, %(business_process)s, %(activity_scope)s, %(criticality)s, %(key_information)s,
            %(downtime_cost_per_hour)s, %(downtime_cost_per_hour_post_rto)s, %(rto_hours)s, %(fte_count)s
        )
        """,
        row,
    )
    _insert_links(connection, row["bp_id"], row["system_ids"])


def _insert_links(connection, bp_id: str, system_ids: list[str]) -> None:
    for system_id in system_ids:
        connection.execute(
            "INSERT INTO process_systems (bp_id, system_id) VALUES (%s, %s)",
            (bp_id, system_id),
        )


def _replace(rows: list[dict]) -> None:
    with connect() as connection:
        with connection.transaction():
            connection.execute("DELETE FROM process_systems")
            connection.execute("DELETE FROM business_processes")
            for row in rows:
                _insert(connection, row)
            connection.execute(TOUCH_META)


def _review(
    parsed: list[tuple[int, dict]],
    ou_ids: set[str],
    system_ids: set[str],
    headcounts: dict[str, int | None],
) -> tuple[list[dict], list[dict], bool]:
    review = []
    stored = []
    any_invalid = False
    for row_number, values in parsed:
        errors = _validate_values(values, ou_ids, system_ids, headcounts)
        if errors:
            any_invalid = True
        review.append({"row": row_number, "values": values, "errors": errors})
        stored.append(_clean({DB_FIELDS[column]: values[column] for column in COLUMNS}))
    return review, stored, any_invalid


def _blank_number(fields: dict, key: str):
    return fields.get(key) if fields.get(key) is not None else ""


def _validate_fields(fields: dict, ou_ids: set[str], system_ids: set[str], headcounts: dict) -> dict:
    return _validate_values(
        {
            "BP ID": str(fields.get("bp_id") or "").strip(),
            "OU ID": str(fields.get("ou_id") or "").strip(),
            "Business Process": str(fields.get("business_process") or "").strip(),
            "Activity/Scope": str(fields.get("activity_scope") or "").strip(),
            "Primary System IDs": str(fields.get("primary_system_ids") or "").strip(),
            "Criticality": str(fields.get("criticality") or "").strip(),
            "Key Information": str(fields.get("key_information") or "").strip(),
            "RTO (hours)": _blank_number(fields, "rto_hours"),
            "Downtime Cost per Hour before RTO": _blank_number(fields, "downtime_cost_per_hour"),
            "Downtime Cost per Hour post RTO": _blank_number(fields, "downtime_cost_per_hour_post_rto"),
            "FTE Count": _blank_number(fields, "fte_count"),
        },
        ou_ids,
        system_ids,
        headcounts,
    )


def _validate_values(values: dict, ou_ids: set[str], system_ids: set[str], headcounts: dict) -> dict:
    errors = {}
    for column in ("BP ID", "Business Process", "Activity/Scope", "Key Information"):
        if not str(values[column] or "").strip():
            errors[column] = "must not be empty"
    ou_id = str(values["OU ID"] or "").strip()
    if not ou_id:
        errors["OU ID"] = "must not be empty"
    elif ou_id not in ou_ids:
        errors["OU ID"] = "must be an existing organisational unit"
    criticality = enum_error(str(values["Criticality"] or "").strip(), CRITICALITY)
    if criticality:
        errors["Criticality"] = criticality
    system_error = _system_list_error(values["Primary System IDs"], system_ids)
    if system_error:
        errors["Primary System IDs"] = system_error
    downtime_error = number_error(values["Downtime Cost per Hour before RTO"], allow_blank=True, minimum=0)
    if downtime_error:
        errors["Downtime Cost per Hour before RTO"] = downtime_error
    post_error = number_error(values["Downtime Cost per Hour post RTO"], allow_blank=True, minimum=0)
    if post_error:
        errors["Downtime Cost per Hour post RTO"] = post_error
    rto_error = number_error(values["RTO (hours)"], allow_blank=True, minimum=0)
    if rto_error:
        errors["RTO (hours)"] = rto_error
    fte_error = number_error(values["FTE Count"], allow_blank=True, minimum=0, integer=True)
    if fte_error:
        errors["FTE Count"] = fte_error
    elif ou_id in headcounts:
        headcount = headcounts[ou_id]
        fte = parse_int(values["FTE Count"])
        if fte is not None and headcount is not None and headcount > 0 and fte > headcount:
            errors["FTE Count"] = "must not exceed the organisational unit headcount"
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
    return {
        "bp_id": str(fields.get("bp_id") or "").strip(),
        "ou_id": str(fields.get("ou_id") or "").strip(),
        "business_process": str(fields.get("business_process") or "").strip(),
        "activity_scope": str(fields.get("activity_scope") or "").strip(),
        "system_ids": split_ids(fields.get("primary_system_ids") or ""),
        "criticality": str(fields.get("criticality") or "").strip(),
        "key_information": str(fields.get("key_information") or "").strip(),
        "downtime_cost_per_hour": parse_number(fields.get("downtime_cost_per_hour")),
        "downtime_cost_per_hour_post_rto": parse_number(fields.get("downtime_cost_per_hour_post_rto")),
        "rto_hours": parse_number(fields.get("rto_hours")),
        "fte_count": parse_int(fields.get("fte_count")),
    }
