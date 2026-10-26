from crq.catalog.catalog_io import (
    MITIGATION_ID,
    attack_id_error,
    connect,
    duplicate_ids,
    enum_error,
    normalise_id_list,
    normalise_technique_chain,
    number_error,
    parse_number,
    read_tabular,
    technique_chain_error,
    triple_error,
    wait_for_database,
)
from crq.intelligence.mitre import loaded_attack_ids, unknown_attack_ids

COLUMNS = (
    "Vector ID",
    "Attack Vector",
    "ATT&CK Technique Chain",
    "Terminal Tactic",
    "Loss Event Type",
    "Requires Exploitable Vulnerability",
    "Requires Internet Facing",
    "ATT&CK Mitigations",
    "Base TEF Min",
    "Base TEF Mode",
    "Base TEF Max",
    "Base Susceptibility Min",
    "Base Susceptibility Mode",
    "Base Susceptibility Max",
    "Typical Outage Hours Min",
    "Typical Outage Hours Mode",
    "Typical Outage Hours Max",
    "Reference",
)

DB_FIELDS = {
    "Vector ID": "vector_id",
    "Attack Vector": "attack_vector",
    "ATT&CK Technique Chain": "technique_chain",
    "Terminal Tactic": "terminal_tactic",
    "Loss Event Type": "loss_event_type",
    "Requires Exploitable Vulnerability": "requires_vulnerability",
    "Requires Internet Facing": "requires_internet_facing",
    "ATT&CK Mitigations": "mitigations",
    "Base TEF Min": "base_tef_min",
    "Base TEF Mode": "base_tef_mode",
    "Base TEF Max": "base_tef_max",
    "Base Susceptibility Min": "base_susceptibility_min",
    "Base Susceptibility Mode": "base_susceptibility_mode",
    "Base Susceptibility Max": "base_susceptibility_max",
    "Typical Outage Hours Min": "outage_hours_min",
    "Typical Outage Hours Mode": "outage_hours_mode",
    "Typical Outage Hours Max": "outage_hours_max",
    "Reference": "reference",
}

TACTICS = ("Impact", "Exfiltration", "Collection")
LOSS_TYPES = ("Availability", "Confidentiality", "Integrity", "Fraud")
YES_NO = ("Yes", "No")
NUMBER_FIELDS = (
    "base_tef_min",
    "base_tef_mode",
    "base_tef_max",
    "base_susceptibility_min",
    "base_susceptibility_mode",
    "base_susceptibility_max",
    "outage_hours_min",
    "outage_hours_mode",
    "outage_hours_max",
)

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS attack_vectors (
    vector_id TEXT PRIMARY KEY,
    attack_vector TEXT NOT NULL,
    technique_chain TEXT NOT NULL,
    terminal_tactic TEXT NOT NULL,
    loss_event_type TEXT NOT NULL,
    requires_vulnerability TEXT NOT NULL,
    requires_internet_facing TEXT NOT NULL,
    mitigations TEXT NOT NULL,
    base_tef_min DOUBLE PRECISION NOT NULL,
    base_tef_mode DOUBLE PRECISION NOT NULL,
    base_tef_max DOUBLE PRECISION NOT NULL,
    base_susceptibility_min DOUBLE PRECISION NOT NULL,
    base_susceptibility_mode DOUBLE PRECISION NOT NULL,
    base_susceptibility_max DOUBLE PRECISION NOT NULL,
    outage_hours_min DOUBLE PRECISION NOT NULL,
    outage_hours_mode DOUBLE PRECISION NOT NULL,
    outage_hours_max DOUBLE PRECISION NOT NULL,
    reference TEXT NOT NULL
)
"""

CREATE_META = """
CREATE TABLE IF NOT EXISTS attack_vector_meta (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    extracted_at TIMESTAMPTZ NOT NULL
)
"""

TOUCH_META = """
INSERT INTO attack_vector_meta (id, extracted_at)
VALUES (1, NOW())
ON CONFLICT (id) DO UPDATE SET extracted_at = EXCLUDED.extracted_at
"""

SELECT = """
SELECT vector_id, attack_vector, technique_chain, terminal_tactic, loss_event_type,
       requires_vulnerability, requires_internet_facing, mitigations,
       base_tef_min, base_tef_mode, base_tef_max,
       base_susceptibility_min, base_susceptibility_mode, base_susceptibility_max,
       outage_hours_min, outage_hours_mode, outage_hours_max, reference
FROM attack_vectors
ORDER BY vector_id
"""


def init_vectors() -> None:
    def apply(connection) -> None:
        connection.execute(CREATE_TABLE)
        connection.execute(CREATE_META)

    wait_for_database(apply)


def list_vectors() -> dict:
    with connect() as connection:
        rows = connection.execute(SELECT).fetchall()
        meta = connection.execute("SELECT extracted_at FROM attack_vector_meta WHERE id = 1").fetchone()
    extracted_at = meta["extracted_at"].isoformat() if meta else None
    return {"items": [dict(row) for row in rows], "extracted_at": extracted_at}


def upload_vectors(filename: str, content: bytes) -> tuple[int, dict]:
    parsed, error = read_tabular(filename, content, COLUMNS)
    if error:
        return 422, {"ok": False, "error": error}
    duplicate_error = duplicate_ids([values["Vector ID"] for _row, values in parsed], "Vector IDs")
    if duplicate_error:
        return 422, {"ok": False, "error": duplicate_error}
    review, stored, any_invalid = _review(parsed, loaded_attack_ids())
    if any_invalid:
        return 422, {"ok": False, "rows": review}
    with connect() as connection:
        missing = sorted(_referenced(connection) - {row["vector_id"] for row in stored})
    if missing:
        return 422, {
            "ok": False,
            "error": "These Vector IDs are still in use and are missing from the file: " + ", ".join(missing),
        }
    _replace(stored)
    listed = list_vectors()
    return 200, {"ok": True, "count": len(listed["items"]), **listed}


def add_vector(fields: dict) -> tuple[int, dict]:
    errors = _validate_fields(fields, loaded_attack_ids())
    if errors:
        return 422, {"ok": False, "errors": errors}
    cleaned = _clean(fields)
    with connect() as connection:
        if _exists(connection, cleaned["vector_id"]):
            return 422, {"ok": False, "errors": {"Vector ID": "already exists"}}
        with connection.transaction():
            _insert(connection, cleaned)
            connection.execute(TOUCH_META)
    return 200, {"ok": True, **list_vectors()}


def update_vector(previous_vector_id: str, fields: dict) -> tuple[int, dict]:
    errors = _validate_fields(fields, loaded_attack_ids())
    if errors:
        return 422, {"ok": False, "errors": errors}
    cleaned = _clean(fields)
    previous = previous_vector_id.strip()
    with connect() as connection:
        if not _exists(connection, previous):
            return 404, {"ok": False, "error": "That attack vector was not found."}
        if cleaned["vector_id"] != previous:
            if previous in _referenced(connection):
                return 422, {"ok": False, "errors": {"Vector ID": "is still used by a risk scenario"}}
            if _exists(connection, cleaned["vector_id"]):
                return 422, {"ok": False, "errors": {"Vector ID": "already exists"}}
        with connection.transaction():
            assignments = ", ".join(f"{field} = %({field})s" for field in cleaned)
            connection.execute(
                f"UPDATE attack_vectors SET {assignments} WHERE vector_id = %(previous)s",
                {**cleaned, "previous": previous},
            )
            connection.execute(TOUCH_META)
    return 200, {"ok": True, **list_vectors()}


def delete_vector(vector_id: str) -> tuple[int, dict]:
    previous = vector_id.strip()
    with connect() as connection:
        if not _exists(connection, previous):
            return 404, {"ok": False, "error": "That attack vector was not found."}
        if previous in _referenced(connection):
            return 422, {"ok": False, "error": "That attack vector is still used by a risk scenario."}
        with connection.transaction():
            connection.execute("DELETE FROM attack_vectors WHERE vector_id = %s", (previous,))
            connection.execute(TOUCH_META)
    return 200, {"ok": True, **list_vectors()}


def _referenced(connection) -> set[str]:
    return {row["attack_vector_id"] for row in connection.execute("SELECT attack_vector_id FROM risk_scenarios")}


def _exists(connection, vector_id: str) -> bool:
    return connection.execute(
        "SELECT vector_id FROM attack_vectors WHERE vector_id = %s", (vector_id,)
    ).fetchone() is not None


def _insert(connection, row: dict) -> None:
    columns = ", ".join(row)
    placeholders = ", ".join(f"%({column})s" for column in row)
    connection.execute(f"INSERT INTO attack_vectors ({columns}) VALUES ({placeholders})", row)


def _replace(rows: list[dict]) -> None:
    with connect() as connection:
        with connection.transaction():
            connection.execute("DELETE FROM attack_vectors")
            for row in rows:
                _insert(connection, row)
            connection.execute(TOUCH_META)


def _review(parsed, catalog: dict[str, set[str]] | None):
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
    for column in ("Vector ID", "Attack Vector"):
        if not str(values.get(column) or "").strip():
            errors[column] = "must not be empty"
    chain = str(values.get("ATT&CK Technique Chain") or "")
    chain_error = technique_chain_error(chain)
    if chain_error:
        errors["ATT&CK Technique Chain"] = chain_error
    else:
        known = None if catalog is None else catalog["techniques"]
        catalog_error = unknown_attack_ids(
            [part for part in normalise_technique_chain(chain).split(" -> ") if part],
            known,
            "ATT&CK technique IDs",
        )
        if catalog_error:
            errors["ATT&CK Technique Chain"] = catalog_error
    for column, options in (
        ("Terminal Tactic", TACTICS),
        ("Loss Event Type", LOSS_TYPES),
        ("Requires Exploitable Vulnerability", YES_NO),
        ("Requires Internet Facing", YES_NO),
    ):
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
    errors.update(triple_error(values, "Base TEF"))
    if "Base TEF Min" not in errors and "Base TEF Max" not in errors:
        minimum = parse_number(values.get("Base TEF Min"))
        maximum = parse_number(values.get("Base TEF Max"))
        if minimum is not None and maximum is not None and not maximum > minimum:
            errors["Base TEF Max"] = "must be greater than Min"
    errors.update(triple_error(values, "Base Susceptibility"))
    for column in ("Base Susceptibility Min", "Base Susceptibility Mode", "Base Susceptibility Max"):
        if column in errors:
            continue
        bound = number_error(values.get(column, ""), allow_blank=False, minimum=0, maximum=1)
        if bound:
            errors[column] = bound
    if "Base Susceptibility Max" not in errors:
        maximum = parse_number(values.get("Base Susceptibility Max"))
        if maximum is not None and not maximum > 0:
            errors["Base Susceptibility Max"] = "must be > 0"
    errors.update(triple_error(values, "Typical Outage Hours"))
    return errors


def _clean(fields: dict) -> dict:
    cleaned = {
        "vector_id": str(fields.get("vector_id") or "").strip(),
        "attack_vector": str(fields.get("attack_vector") or "").strip(),
        "technique_chain": normalise_technique_chain(fields.get("technique_chain") or ""),
        "terminal_tactic": str(fields.get("terminal_tactic") or "").strip(),
        "loss_event_type": str(fields.get("loss_event_type") or "").strip(),
        "requires_vulnerability": str(fields.get("requires_vulnerability") or "").strip(),
        "requires_internet_facing": str(fields.get("requires_internet_facing") or "").strip(),
        "mitigations": normalise_id_list(fields.get("mitigations") or ""),
        "reference": str(fields.get("reference") or "").strip(),
    }
    for field in NUMBER_FIELDS:
        cleaned[field] = parse_number(fields.get(field))
    return cleaned
