from crq.catalog.catalog_io import (
    GROUP_ID,
    attack_id_error,
    connect,
    duplicate_ids,
    enum_error,
    normalise_id_list,
    read_tabular,
    wait_for_database,
)
from crq.intelligence.mitre import loaded_attack_ids, unknown_attack_ids

COLUMNS = (
    "Actor ID",
    "Threat Actor",
    "Actor Type",
    "Motivation",
    "Capability",
    "Sector Targeting",
    "ATT&CK Group IDs",
    "Description",
    "Reference",
)

DB_FIELDS = {
    "Actor ID": "actor_id",
    "Threat Actor": "threat_actor",
    "Actor Type": "actor_type",
    "Motivation": "motivation",
    "Capability": "capability",
    "Sector Targeting": "sector_targeting",
    "ATT&CK Group IDs": "attack_group_ids",
    "Description": "description",
    "Reference": "reference",
}

ACTOR_TYPES = ("Cybercrime", "Nation-State", "Hacktivist", "Insider", "Supply Chain", "Opportunistic")
MOTIVATIONS = ("Financial", "Espionage", "Disruption", "Ideological", "Grievance")
LEVELS = ("Low", "Medium", "High")

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS threat_actors (
    actor_id TEXT PRIMARY KEY,
    threat_actor TEXT NOT NULL,
    actor_type TEXT NOT NULL,
    motivation TEXT NOT NULL,
    capability TEXT NOT NULL,
    sector_targeting TEXT NOT NULL,
    attack_group_ids TEXT NOT NULL,
    description TEXT NOT NULL,
    reference TEXT NOT NULL
)
"""

CREATE_META = """
CREATE TABLE IF NOT EXISTS threat_actor_meta (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    extracted_at TIMESTAMPTZ NOT NULL
)
"""

TOUCH_META = """
INSERT INTO threat_actor_meta (id, extracted_at)
VALUES (1, NOW())
ON CONFLICT (id) DO UPDATE SET extracted_at = EXCLUDED.extracted_at
"""


def init_actors() -> None:
    def apply(connection) -> None:
        connection.execute(CREATE_TABLE)
        connection.execute(CREATE_META)

    wait_for_database(apply)


def list_actors() -> dict:
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT actor_id, threat_actor, actor_type, motivation, capability, sector_targeting,
                   attack_group_ids, description, reference
            FROM threat_actors
            ORDER BY actor_id
            """
        ).fetchall()
        meta = connection.execute("SELECT extracted_at FROM threat_actor_meta WHERE id = 1").fetchone()
    extracted_at = meta["extracted_at"].isoformat() if meta else None
    return {"items": [dict(row) for row in rows], "extracted_at": extracted_at}


def upload_actors(filename: str, content: bytes) -> tuple[int, dict]:
    parsed, error = read_tabular(filename, content, COLUMNS)
    if error:
        return 422, {"ok": False, "error": error}
    duplicate_error = duplicate_ids([values["Actor ID"] for _row, values in parsed], "Actor IDs")
    if duplicate_error:
        return 422, {"ok": False, "error": duplicate_error}
    review, stored, any_invalid = _review(parsed, loaded_attack_ids())
    if any_invalid:
        return 422, {"ok": False, "rows": review}
    with connect() as connection:
        missing = sorted(_referenced(connection) - {row["actor_id"] for row in stored})
    if missing:
        return 422, {
            "ok": False,
            "error": "These Actor IDs are still in use and are missing from the file: " + ", ".join(missing),
        }
    _replace(stored)
    listed = list_actors()
    return 200, {"ok": True, "count": len(listed["items"]), **listed}


def add_actor(fields: dict) -> tuple[int, dict]:
    errors = _validate_fields(fields, loaded_attack_ids())
    if errors:
        return 422, {"ok": False, "errors": errors}
    cleaned = _clean(fields)
    with connect() as connection:
        if _exists(connection, cleaned["actor_id"]):
            return 422, {"ok": False, "errors": {"Actor ID": "already exists"}}
        with connection.transaction():
            _insert(connection, cleaned)
            connection.execute(TOUCH_META)
    return 200, {"ok": True, **list_actors()}


def update_actor(previous_actor_id: str, fields: dict) -> tuple[int, dict]:
    errors = _validate_fields(fields, loaded_attack_ids())
    if errors:
        return 422, {"ok": False, "errors": errors}
    cleaned = _clean(fields)
    previous = previous_actor_id.strip()
    with connect() as connection:
        if not _exists(connection, previous):
            return 404, {"ok": False, "error": "That threat actor was not found."}
        if cleaned["actor_id"] != previous:
            if previous in _referenced(connection):
                return 422, {"ok": False, "errors": {"Actor ID": "is still used by a risk scenario"}}
            if _exists(connection, cleaned["actor_id"]):
                return 422, {"ok": False, "errors": {"Actor ID": "already exists"}}
        with connection.transaction():
            connection.execute(
                """
                UPDATE threat_actors
                SET actor_id = %(actor_id)s, threat_actor = %(threat_actor)s, actor_type = %(actor_type)s,
                    motivation = %(motivation)s, capability = %(capability)s, sector_targeting = %(sector_targeting)s,
                    attack_group_ids = %(attack_group_ids)s, description = %(description)s, reference = %(reference)s
                WHERE actor_id = %(previous)s
                """,
                {**cleaned, "previous": previous},
            )
            connection.execute(TOUCH_META)
    return 200, {"ok": True, **list_actors()}


def delete_actor(actor_id: str) -> tuple[int, dict]:
    previous = actor_id.strip()
    with connect() as connection:
        if not _exists(connection, previous):
            return 404, {"ok": False, "error": "That threat actor was not found."}
        if previous in _referenced(connection):
            return 422, {"ok": False, "error": "That threat actor is still used by a risk scenario."}
        with connection.transaction():
            connection.execute("DELETE FROM threat_actors WHERE actor_id = %s", (previous,))
            connection.execute(TOUCH_META)
    return 200, {"ok": True, **list_actors()}


def _referenced(connection) -> set[str]:
    return {row["threat_actor_id"] for row in connection.execute("SELECT threat_actor_id FROM risk_scenarios")}


def _exists(connection, actor_id: str) -> bool:
    return connection.execute("SELECT actor_id FROM threat_actors WHERE actor_id = %s", (actor_id,)).fetchone() is not None


def _insert(connection, row: dict) -> None:
    connection.execute(
        """
        INSERT INTO threat_actors (
            actor_id, threat_actor, actor_type, motivation, capability, sector_targeting,
            attack_group_ids, description, reference
        )
        VALUES (
            %(actor_id)s, %(threat_actor)s, %(actor_type)s, %(motivation)s, %(capability)s, %(sector_targeting)s,
            %(attack_group_ids)s, %(description)s, %(reference)s
        )
        """,
        row,
    )


def _replace(rows: list[dict]) -> None:
    with connect() as connection:
        with connection.transaction():
            connection.execute("DELETE FROM threat_actors")
            for row in rows:
                _insert(connection, row)
            connection.execute(TOUCH_META)


def _review(parsed: list[tuple[int, dict]], catalog: dict[str, set[str]] | None) -> tuple[list[dict], list[dict], bool]:
    review, stored, any_invalid = [], [], False
    for row_number, values in parsed:
        errors = _validate_values(values, catalog)
        any_invalid = any_invalid or bool(errors)
        review.append({"row": row_number, "values": values, "errors": errors})
        stored.append(_clean({DB_FIELDS[column]: values[column] for column in COLUMNS}))
    return review, stored, any_invalid


def _validate_fields(fields: dict, catalog: dict[str, set[str]] | None) -> dict:
    return _validate_values({column: fields.get(DB_FIELDS[column], "") for column in COLUMNS}, catalog)


def _validate_values(values: dict, catalog: dict[str, set[str]] | None) -> dict:
    errors = {}
    for column in ("Actor ID", "Threat Actor", "Description"):
        if not str(values.get(column) or "").strip():
            errors[column] = "must not be empty"
    for column, options in (
        ("Actor Type", ACTOR_TYPES),
        ("Motivation", MOTIVATIONS),
        ("Capability", LEVELS),
        ("Sector Targeting", LEVELS),
    ):
        error = enum_error(str(values.get(column) or "").strip(), options)
        if error:
            errors[column] = error
    groups = str(values.get("ATT&CK Group IDs") or "")
    group_error = attack_id_error(groups, GROUP_ID, "ATT&CK group IDs")
    if group_error:
        errors["ATT&CK Group IDs"] = group_error
    else:
        known = None if catalog is None else catalog["groups"]
        catalog_error = unknown_attack_ids(
            [part for part in normalise_id_list(groups).split(", ") if part],
            known,
            "ATT&CK group IDs",
        )
        if catalog_error:
            errors["ATT&CK Group IDs"] = catalog_error
    return errors


def _clean(fields: dict) -> dict:
    return {
        "actor_id": str(fields.get("actor_id") or "").strip(),
        "threat_actor": str(fields.get("threat_actor") or "").strip(),
        "actor_type": str(fields.get("actor_type") or "").strip(),
        "motivation": str(fields.get("motivation") or "").strip(),
        "capability": str(fields.get("capability") or "").strip(),
        "sector_targeting": str(fields.get("sector_targeting") or "").strip(),
        "attack_group_ids": normalise_id_list(fields.get("attack_group_ids") or ""),
        "description": str(fields.get("description") or "").strip(),
        "reference": str(fields.get("reference") or "").strip(),
    }
