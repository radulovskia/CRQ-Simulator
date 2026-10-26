"""MITRE ATT&CK Enterprise dataset, stored separately from the CRQ catalogs."""

import json
import os
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row

GITHUB_RELEASE = "https://api.github.com/repos/mitre-attack/attack-stix-data/releases/latest"
RELATIONSHIP_TYPES = ("uses", "mitigates", "subtechnique-of", "revoked-by", "detects")
TABLE_COLLECTIONS = ("tactics", "techniques", "groups", "software", "mitigations", "campaigns")
COLLECTIONS = TABLE_COLLECTIONS + ("assets", "detection-strategies", "analytics", "data-components")
OBJECT_COLLECTIONS = {
    "assets": "x-mitre-asset",
    "detection-strategies": "x-mitre-detection-strategy",
    "analytics": "x-mitre-analytic",
    "data-components": "x-mitre-data-component",
}
_LOCK = threading.Lock()

CREATE_DATASET = """
CREATE TABLE IF NOT EXISTS dataset (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    domain TEXT NOT NULL,
    attack_version TEXT NOT NULL,
    source_url TEXT NOT NULL,
    downloaded_at TIMESTAMPTZ NOT NULL,
    object_count INTEGER NOT NULL
)
"""

CREATE_OBJECTS = """
CREATE TABLE IF NOT EXISTS objects (
    stix_id TEXT PRIMARY KEY,
    object_type TEXT NOT NULL,
    name TEXT,
    modified TIMESTAMPTZ,
    revoked BOOLEAN NOT NULL DEFAULT FALSE,
    deprecated BOOLEAN NOT NULL DEFAULT FALSE,
    external_id TEXT,
    body JSONB NOT NULL
)
"""

CREATE_REFERENCES = """
CREATE TABLE IF NOT EXISTS external_references (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    stix_id TEXT NOT NULL REFERENCES objects (stix_id) ON DELETE CASCADE,
    source_name TEXT,
    external_id TEXT,
    url TEXT,
    description TEXT
)
"""

CREATE_RELATIONSHIPS = """
CREATE TABLE IF NOT EXISTS relationships (
    stix_id TEXT PRIMARY KEY REFERENCES objects (stix_id) ON DELETE CASCADE,
    relationship_type TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    target_ref TEXT NOT NULL,
    description TEXT
)
"""

CREATE_TACTICS = """
CREATE TABLE IF NOT EXISTS tactics (
    stix_id TEXT PRIMARY KEY,
    external_id TEXT,
    shortname TEXT,
    name TEXT NOT NULL,
    description TEXT,
    url TEXT,
    revoked BOOLEAN NOT NULL DEFAULT FALSE,
    deprecated BOOLEAN NOT NULL DEFAULT FALSE
)
"""

CREATE_TECHNIQUES = """
CREATE TABLE IF NOT EXISTS techniques (
    stix_id TEXT PRIMARY KEY,
    external_id TEXT,
    name TEXT NOT NULL,
    description TEXT,
    is_subtechnique BOOLEAN NOT NULL DEFAULT FALSE,
    parent_stix_id TEXT,
    url TEXT,
    revoked BOOLEAN NOT NULL DEFAULT FALSE,
    deprecated BOOLEAN NOT NULL DEFAULT FALSE
)
"""

CREATE_TECHNIQUE_TACTICS = """
CREATE TABLE IF NOT EXISTS technique_tactics (
    technique_stix_id TEXT NOT NULL,
    tactic_stix_id TEXT NOT NULL,
    PRIMARY KEY (technique_stix_id, tactic_stix_id)
)
"""

CREATE_GROUPS = """
CREATE TABLE IF NOT EXISTS groups (
    stix_id TEXT PRIMARY KEY,
    external_id TEXT,
    name TEXT NOT NULL,
    description TEXT,
    aliases TEXT[] NOT NULL DEFAULT '{}',
    url TEXT,
    revoked BOOLEAN NOT NULL DEFAULT FALSE,
    deprecated BOOLEAN NOT NULL DEFAULT FALSE
)
"""

CREATE_SOFTWARE = """
CREATE TABLE IF NOT EXISTS software (
    stix_id TEXT PRIMARY KEY,
    external_id TEXT,
    name TEXT NOT NULL,
    software_type TEXT NOT NULL,
    description TEXT,
    aliases TEXT[] NOT NULL DEFAULT '{}',
    url TEXT,
    revoked BOOLEAN NOT NULL DEFAULT FALSE,
    deprecated BOOLEAN NOT NULL DEFAULT FALSE
)
"""

CREATE_MITIGATIONS = """
CREATE TABLE IF NOT EXISTS mitigations (
    stix_id TEXT PRIMARY KEY,
    external_id TEXT,
    name TEXT NOT NULL,
    description TEXT,
    url TEXT,
    revoked BOOLEAN NOT NULL DEFAULT FALSE,
    deprecated BOOLEAN NOT NULL DEFAULT FALSE
)
"""

CREATE_CAMPAIGNS = """
CREATE TABLE IF NOT EXISTS campaigns (
    stix_id TEXT PRIMARY KEY,
    external_id TEXT,
    name TEXT NOT NULL,
    description TEXT,
    first_seen TEXT,
    last_seen TEXT,
    url TEXT,
    revoked BOOLEAN NOT NULL DEFAULT FALSE,
    deprecated BOOLEAN NOT NULL DEFAULT FALSE
)
"""

INDEXES = (
    "CREATE INDEX IF NOT EXISTS objects_type_idx ON objects (object_type)",
    "CREATE INDEX IF NOT EXISTS objects_external_id_idx ON objects (external_id)",
    "CREATE INDEX IF NOT EXISTS external_references_stix_idx ON external_references (stix_id)",
    "CREATE INDEX IF NOT EXISTS relationships_source_idx ON relationships (source_ref)",
    "CREATE INDEX IF NOT EXISTS relationships_target_idx ON relationships (target_ref)",
    "CREATE INDEX IF NOT EXISTS relationships_type_idx ON relationships (relationship_type)",
)

TABLES = (
    CREATE_DATASET,
    CREATE_OBJECTS,
    CREATE_REFERENCES,
    CREATE_RELATIONSHIPS,
    CREATE_TACTICS,
    CREATE_TECHNIQUES,
    CREATE_TECHNIQUE_TACTICS,
    CREATE_GROUPS,
    CREATE_SOFTWARE,
    CREATE_MITIGATIONS,
    CREATE_CAMPAIGNS,
)


def mitre_database_url() -> str:
    url = os.environ.get("MITRE_DATABASE_URL")
    if not url:
        raise RuntimeError("MITRE_DATABASE_URL is not set")
    return url


def connect():
    return psycopg.connect(mitre_database_url(), row_factory=dict_row)


def init_mitre_db() -> None:
    _create_database()
    last_error = None
    for _ in range(30):
        try:
            with connect() as connection:
                for statement in TABLES:
                    connection.execute(statement)
                for statement in INDEXES:
                    connection.execute(statement)
                connection.commit()
            _supplement_loaded_dataset()
            return
        except psycopg.OperationalError as exc:
            last_error = exc
            time.sleep(1)
    raise last_error


def _create_database() -> None:
    admin_url = os.environ.get("DATABASE_URL")
    if not admin_url:
        raise RuntimeError("DATABASE_URL is not set")
    last_error = None
    for _ in range(30):
        try:
            with psycopg.connect(admin_url, autocommit=True) as connection:
                exists = connection.execute(
                    "SELECT 1 FROM pg_database WHERE datname = 'mitre_enterprise'"
                ).fetchone()
                if not exists:
                    connection.execute("CREATE DATABASE mitre_enterprise")
            return
        except psycopg.OperationalError as exc:
            last_error = exc
            time.sleep(1)
    raise last_error


def _collection_counts(connection) -> dict:
    counts = {
        name: connection.execute(f"SELECT COUNT(*) AS count FROM {name}").fetchone()["count"]
        for name in TABLE_COLLECTIONS
    }
    for name, object_type in OBJECT_COLLECTIONS.items():
        counts[name] = connection.execute(
            "SELECT COUNT(*) AS count FROM objects WHERE object_type = %s",
            (object_type,),
        ).fetchone()["count"]
    return counts


def mitre_status() -> dict:
    with connect() as connection:
        dataset = connection.execute("SELECT * FROM dataset WHERE id = 1").fetchone()
        counts = _collection_counts(connection)
    if not dataset:
        return {
            "loaded": False,
            "domain": "enterprise-attack",
            "attack_version": None,
            "source_url": None,
            "downloaded_at": None,
            "object_count": 0,
            "counts": counts,
        }
    return {
        "loaded": True,
        "domain": dataset["domain"],
        "attack_version": dataset["attack_version"],
        "source_url": dataset["source_url"],
        "downloaded_at": dataset["downloaded_at"].isoformat(),
        "object_count": dataset["object_count"],
        "counts": counts,
    }


def loaded_attack_ids() -> dict[str, set[str]] | None:
    """Enterprise external IDs, or None when the dataset has not been loaded.

    Revoked and deprecated rows stay in the sets. A save accepts an ID that exists.
    """
    with connect() as connection:
        dataset = connection.execute("SELECT id FROM dataset WHERE id = 1").fetchone()
        if not dataset:
            return None
        techniques = connection.execute(
            "SELECT external_id FROM techniques WHERE external_id IS NOT NULL"
        ).fetchall()
        groups = connection.execute(
            "SELECT external_id FROM groups WHERE external_id IS NOT NULL"
        ).fetchall()
        mitigations = connection.execute(
            "SELECT external_id FROM mitigations WHERE external_id IS NOT NULL"
        ).fetchall()
    return {
        "techniques": {row["external_id"] for row in techniques},
        "groups": {row["external_id"] for row in groups},
        "mitigations": {row["external_id"] for row in mitigations},
    }


def unknown_attack_ids(ids: list[str], known: set[str] | None, label: str) -> str | None:
    if not ids:
        return None
    if known is None:
        return "MITRE Enterprise dataset is not loaded"
    missing = [item for item in ids if item not in known]
    if not missing:
        return None
    return f"unknown {label}: " + ", ".join(missing)


def check_mitre() -> tuple[int, dict]:
    if not _LOCK.acquire(blocking=False):
        return 409, {"ok": False, "error": "A MITRE update is already running."}
    try:
        return _check_mitre()
    finally:
        _LOCK.release()


def _check_mitre() -> tuple[int, dict]:
    try:
        release = _get_json(GITHUB_RELEASE)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return 502, {"ok": False, "error": f"The MITRE release could not be read. {exc}"}
    latest = _release_version(release)
    asset = next((item for item in release.get("assets") or [] if item.get("name") == "enterprise-attack.json"), None)
    if not latest or not asset or not asset.get("browser_download_url"):
        return 502, {"ok": False, "error": "The latest MITRE Enterprise release has no dataset."}
    status = mitre_status()
    if status["loaded"] and status["attack_version"] == latest:
        _supplement_loaded_dataset()
        return 200, {
            "ok": True,
            "updated": False,
            "message": "Latest MITRE version is already loaded",
            **mitre_status(),
        }
    ics_asset = next((item for item in release.get("assets") or [] if item.get("name") == "ics-attack.json"), None)
    if not ics_asset or not ics_asset.get("browser_download_url"):
        return 502, {"ok": False, "error": "The latest MITRE release has no ICS dataset for assets."}
    try:
        bundle = _get_json(asset["browser_download_url"])
        ics_bundle = _get_json(ics_asset["browser_download_url"])
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return 502, {"ok": False, "error": f"The MITRE dataset could not be downloaded. {exc}"}
    objects = bundle.get("objects")
    if bundle.get("type") != "bundle" or not isinstance(objects, list):
        return 502, {"ok": False, "error": "The MITRE dataset is not an ATT&CK bundle."}
    collection = next((item for item in objects if item.get("type") == "x-mitre-collection"), None)
    if collection and "enterprise" not in str(collection.get("name") or "").lower():
        return 502, {"ok": False, "error": "The downloaded bundle is not Enterprise ATT&CK."}
    ics_objects = ics_bundle.get("objects") if isinstance(ics_bundle, dict) else None
    assets = [item for item in ics_objects or [] if item.get("type") == "x-mitre-asset"]
    if not isinstance(ics_objects, list) or not assets:
        return 502, {"ok": False, "error": "The MITRE ICS dataset has no assets."}
    _replace_dataset(objects, latest, asset["browser_download_url"], assets)
    loaded = mitre_status()
    return 200, {
        "ok": True,
        "updated": True,
        "message": f"Loaded MITRE ATT&CK {loaded['attack_version']}.",
        **loaded,
    }


def list_mitre(collection: str, query: str) -> dict:
    if collection not in COLLECTIONS:
        raise KeyError(collection)
    pattern = f"%{_escape_like(query.strip())}%" if query.strip() else None
    with connect() as connection:
        if collection == "tactics":
            rows = _search(connection, """
                SELECT external_id, name, shortname AS summary, revoked, deprecated
                FROM tactics
                WHERE %(pattern)s::text IS NULL
                   OR name ILIKE %(pattern)s ESCAPE '\\'
                   OR external_id ILIKE %(pattern)s ESCAPE '\\'
                   OR shortname ILIKE %(pattern)s ESCAPE '\\'
                ORDER BY external_id
            """, pattern)
        elif collection == "techniques":
            rows = _search(connection, """
                SELECT t.external_id, t.name, t.revoked, t.deprecated,
                       COALESCE(string_agg(tac.name, ', ' ORDER BY tac.name), '') AS summary
                FROM techniques t
                LEFT JOIN technique_tactics link ON link.technique_stix_id = t.stix_id
                LEFT JOIN tactics tac ON tac.stix_id = link.tactic_stix_id
                WHERE %(pattern)s::text IS NULL
                   OR t.name ILIKE %(pattern)s ESCAPE '\\'
                   OR t.external_id ILIKE %(pattern)s ESCAPE '\\'
                GROUP BY t.stix_id
                ORDER BY t.external_id
            """, pattern)
        elif collection == "groups":
            rows = _search(connection, """
                SELECT external_id, name, array_to_string(aliases, ', ') AS summary, revoked, deprecated
                FROM groups
                WHERE %(pattern)s::text IS NULL
                   OR name ILIKE %(pattern)s ESCAPE '\\'
                   OR external_id ILIKE %(pattern)s ESCAPE '\\'
                   OR array_to_string(aliases, ' ') ILIKE %(pattern)s ESCAPE '\\'
                ORDER BY external_id
            """, pattern)
        elif collection == "software":
            rows = _search(connection, """
                SELECT external_id, name, software_type AS summary, revoked, deprecated
                FROM software
                WHERE %(pattern)s::text IS NULL
                   OR name ILIKE %(pattern)s ESCAPE '\\'
                   OR external_id ILIKE %(pattern)s ESCAPE '\\'
                   OR array_to_string(aliases, ' ') ILIKE %(pattern)s ESCAPE '\\'
                ORDER BY external_id
            """, pattern)
        elif collection == "mitigations":
            rows = _search(connection, """
                SELECT external_id, name, '' AS summary, revoked, deprecated
                FROM mitigations
                WHERE %(pattern)s::text IS NULL
                   OR name ILIKE %(pattern)s ESCAPE '\\'
                   OR external_id ILIKE %(pattern)s ESCAPE '\\'
                ORDER BY external_id
            """, pattern)
        elif collection == "campaigns":
            rows = _search(connection, """
                SELECT external_id, name,
                       trim(both ' ' FROM concat_ws(' – ', first_seen, last_seen)) AS summary,
                       revoked, deprecated
                FROM campaigns
                WHERE %(pattern)s::text IS NULL
                   OR name ILIKE %(pattern)s ESCAPE '\\'
                   OR external_id ILIKE %(pattern)s ESCAPE '\\'
                ORDER BY external_id
            """, pattern)
        elif collection == "assets":
            rows = _search(connection, """
                SELECT external_id, name, revoked, deprecated,
                       COALESCE((
                           SELECT string_agg(value, ', ' ORDER BY value)
                           FROM jsonb_array_elements_text(COALESCE(body->'x_mitre_platforms', '[]'::jsonb)) AS value
                       ), '') AS summary
                FROM objects
                WHERE object_type = 'x-mitre-asset'
                  AND (%(pattern)s::text IS NULL
                   OR name ILIKE %(pattern)s ESCAPE '\\'
                   OR external_id ILIKE %(pattern)s ESCAPE '\\'
                   OR COALESCE(body->>'description', '') ILIKE %(pattern)s ESCAPE '\\')
                ORDER BY external_id
            """, pattern)
        elif collection == "detection-strategies":
            rows = _search(connection, """
                SELECT d.external_id, d.name, d.revoked, d.deprecated,
                       COALESCE(string_agg(DISTINCT concat_ws(' ', t.external_id, t.name), ', ' ORDER BY concat_ws(' ', t.external_id, t.name)), '') AS summary
                FROM objects d
                LEFT JOIN relationships rel ON rel.relationship_type = 'detects' AND rel.source_ref = d.stix_id
                LEFT JOIN objects t ON t.stix_id = rel.target_ref
                WHERE d.object_type = 'x-mitre-detection-strategy'
                  AND (%(pattern)s::text IS NULL
                   OR d.name ILIKE %(pattern)s ESCAPE '\\'
                   OR d.external_id ILIKE %(pattern)s ESCAPE '\\'
                   OR t.name ILIKE %(pattern)s ESCAPE '\\'
                   OR t.external_id ILIKE %(pattern)s ESCAPE '\\')
                GROUP BY d.stix_id
                ORDER BY d.external_id
            """, pattern)
        elif collection == "analytics":
            rows = _search(connection, """
                SELECT external_id, name, revoked, deprecated,
                       COALESCE((
                           SELECT string_agg(value, ', ' ORDER BY value)
                           FROM jsonb_array_elements_text(COALESCE(body->'x_mitre_platforms', '[]'::jsonb)) AS value
                       ), '') AS summary
                FROM objects
                WHERE object_type = 'x-mitre-analytic'
                  AND (%(pattern)s::text IS NULL
                   OR name ILIKE %(pattern)s ESCAPE '\\'
                   OR external_id ILIKE %(pattern)s ESCAPE '\\'
                   OR COALESCE(body->>'description', '') ILIKE %(pattern)s ESCAPE '\\')
                ORDER BY external_id
            """, pattern)
        else:
            rows = _search(connection, """
                SELECT external_id, name, '' AS summary, revoked, deprecated
                FROM objects
                WHERE object_type = 'x-mitre-data-component'
                  AND (%(pattern)s::text IS NULL
                   OR name ILIKE %(pattern)s ESCAPE '\\'
                   OR external_id ILIKE %(pattern)s ESCAPE '\\'
                   OR COALESCE(body->>'description', '') ILIKE %(pattern)s ESCAPE '\\')
                ORDER BY external_id
            """, pattern)
    return {"items": [_public_row(row) for row in rows]}


def mitre_object(external_id: str) -> dict | None:
    key = external_id.strip()
    with connect() as connection:
        found = connection.execute(
            """
            SELECT stix_id, object_type, name, revoked, deprecated, external_id, body
            FROM objects
            WHERE external_id = %s
            ORDER BY revoked, deprecated
            LIMIT 1
            """,
            (key,),
        ).fetchone()
        if not found:
            return None
        references = connection.execute(
            """
            SELECT source_name, external_id, url, description
            FROM external_references
            WHERE stix_id = %s
            ORDER BY id
            """,
            (found["stix_id"],),
        ).fetchall()
        relationships = connection.execute(
            """
            SELECT r.relationship_type, r.description, r.source_ref,
                   other.name AS other_name, other.external_id AS other_external_id, other.object_type AS other_type
            FROM relationships r
            JOIN objects other ON other.stix_id = CASE WHEN r.source_ref = %s THEN r.target_ref ELSE r.source_ref END
            WHERE r.source_ref = %s OR r.target_ref = %s
            ORDER BY r.relationship_type, other.name
            """,
            (found["stix_id"], found["stix_id"], found["stix_id"]),
        ).fetchall()
        body = found["body"] or {}
        aliases = body.get("aliases") or body.get("x_mitre_aliases") or []
        return {
            "external_id": found["external_id"],
            "name": found["name"] or found["external_id"],
            "object_type": found["object_type"],
            "revoked": found["revoked"],
            "deprecated": found["deprecated"],
            "description": body.get("description") or "",
            "aliases": [alias for alias in aliases if isinstance(alias, str) and alias.strip()],
            "references": [
                {
                    "source_name": row["source_name"] or "",
                    "external_id": row["external_id"] or "",
                    "url": row["url"] or "",
                    "description": row["description"] or "",
                }
                for row in references
            ],
            "relationships": _object_relationships(connection, found, relationships),
        }


def _search(connection, sql: str, pattern: str | None) -> list[dict]:
    return connection.execute(sql, {"pattern": pattern}).fetchall()


def _public_row(row: dict) -> dict:
    return {
        "external_id": row["external_id"] or "",
        "name": row["name"],
        "summary": row["summary"] or "",
        "revoked": row["revoked"],
        "deprecated": row["deprecated"],
    }


def _relationship_label(relationship_type: str, outbound: bool) -> str:
    labels = {
        ("uses", True): "Uses",
        ("uses", False): "Used by",
        ("mitigates", True): "Mitigates",
        ("mitigates", False): "Mitigated by",
        ("subtechnique-of", True): "Subtechnique of",
        ("subtechnique-of", False): "Subtechnique",
        ("revoked-by", True): "Revoked by",
        ("revoked-by", False): "Revokes",
        ("detects", True): "Detects",
        ("detects", False): "Detected by",
    }
    return labels.get((relationship_type, outbound), relationship_type)


def _object_relationships(connection, found: dict, rows: list[dict]) -> list[dict]:
    body = found["body"] or {}
    linked = [
        {
            "label": _relationship_label(row["relationship_type"], row["source_ref"] == found["stix_id"]),
            "relationship_type": row["relationship_type"],
            "external_id": row["other_external_id"] or "",
            "name": row["other_name"] or row["other_external_id"] or row["other_type"],
            "description": row["description"] or "",
        }
        for row in rows
    ]
    if found["object_type"] == "x-mitre-detection-strategy":
        refs = [item for item in body.get("x_mitre_analytic_refs") or [] if isinstance(item, str)]
        if refs:
            analytics = connection.execute(
                """
                SELECT external_id, name FROM objects
                WHERE stix_id = ANY(%s)
                ORDER BY external_id
                """,
                (refs,),
            ).fetchall()
            linked.extend(_named_links("Analytic", analytics))
    elif found["object_type"] == "x-mitre-analytic":
        strategies = connection.execute(
            """
            SELECT external_id, name FROM objects
            WHERE object_type = 'x-mitre-detection-strategy'
              AND body->'x_mitre_analytic_refs' ? %s
            ORDER BY external_id
            """,
            (found["stix_id"],),
        ).fetchall()
        linked.extend(_named_links("Detection strategy", strategies))
        component_ids = []
        for source in body.get("x_mitre_log_source_references") or []:
            if isinstance(source, dict) and isinstance(source.get("x_mitre_data_component_ref"), str):
                component_ids.append(source["x_mitre_data_component_ref"])
        if component_ids:
            components = connection.execute(
                """
                SELECT external_id, name FROM objects
                WHERE stix_id = ANY(%s)
                ORDER BY external_id
                """,
                (list(dict.fromkeys(component_ids)),),
            ).fetchall()
            linked.extend(_named_links("Data component", components))
    elif found["object_type"] == "x-mitre-data-component":
        analytics = connection.execute(
            """
            SELECT external_id, name FROM objects
            WHERE object_type = 'x-mitre-analytic'
              AND body @> %s::jsonb
            ORDER BY external_id
            """,
            (json.dumps({"x_mitre_log_source_references": [{"x_mitre_data_component_ref": found["stix_id"]}]}),),
        ).fetchall()
        linked.extend(_named_links("Analytic", analytics))
    elif found["object_type"] == "x-mitre-asset":
        for related in body.get("x_mitre_related_assets") or []:
            if not isinstance(related, dict) or not related.get("name"):
                continue
            linked.append({
                "label": "Related",
                "relationship_type": "related-asset",
                "external_id": "",
                "name": _text(related.get("name")),
                "description": _text(related.get("description")),
            })
    return linked


def _named_links(label: str, rows: list[dict]) -> list[dict]:
    return [
        {
            "label": label,
            "relationship_type": label.lower().replace(" ", "-"),
            "external_id": row["external_id"] or "",
            "name": row["name"] or row["external_id"] or "",
            "description": "",
        }
        for row in rows
    ]


def _supplement_loaded_dataset() -> None:
    with connect() as connection:
        dataset = connection.execute("SELECT attack_version FROM dataset WHERE id = 1").fetchone()
        if not dataset:
            return
        connection.execute(
            """
            INSERT INTO relationships (stix_id, relationship_type, source_ref, target_ref, description)
            SELECT rel.stix_id,
                   rel.body->>'relationship_type',
                   rel.body->>'source_ref',
                   rel.body->>'target_ref',
                   NULLIF(rel.body->>'description', '')
            FROM objects rel
            JOIN objects source_object ON source_object.stix_id = rel.body->>'source_ref'
            JOIN objects target_object ON target_object.stix_id = rel.body->>'target_ref'
            WHERE rel.object_type = 'relationship'
              AND rel.body->>'relationship_type' = 'detects'
              AND NOT EXISTS (
                  SELECT 1 FROM relationships existing WHERE existing.stix_id = rel.stix_id
              )
            """
        )
        has_assets = connection.execute(
            "SELECT 1 FROM objects WHERE object_type = 'x-mitre-asset' LIMIT 1"
        ).fetchone()
        version = dataset["attack_version"]
        connection.commit()
    if has_assets:
        return
    try:
        bundle = _get_json(_release_bundle_url(version, "ics-attack.json"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return
    assets = [item for item in bundle.get("objects") or [] if item.get("type") == "x-mitre-asset"]
    if not assets:
        return
    with connect() as connection:
        _insert_objects(connection, assets)
        _insert_references(connection, assets)
        connection.commit()


def _release_bundle_url(version: str, filename: str) -> str:
    tag = version if str(version).startswith("v") else f"v{version}"
    return f"https://github.com/mitre-attack/attack-stix-data/releases/download/{tag}/{filename}"


def _replace_dataset(objects: list[dict], version: str, source_url: str, assets: list[dict] | None = None) -> None:
    prepared = []
    by_id = {}
    for item in objects:
        stix_id = str(item.get("id") or "").strip()
        if not stix_id or stix_id in by_id:
            continue
        by_id[stix_id] = item
        prepared.append(item)
    tactics = {}
    with connect() as connection:
        with connection.transaction():
            connection.execute(
                "TRUNCATE external_references, relationships, technique_tactics, tactics, techniques, groups, software, mitigations, campaigns, objects, dataset"
            )
            _insert_objects(connection, prepared)
            _insert_references(connection, prepared)
            _insert_relationships(connection, prepared, set(by_id))
            for item in prepared:
                if item.get("type") == "x-mitre-tactic":
                    tactics[item["id"]] = _text(item.get("x_mitre_shortname"))
            _insert_projected(connection, prepared, tactics)
            if assets:
                _insert_objects(connection, assets)
                _insert_references(connection, assets)
            connection.execute(
                """
                INSERT INTO dataset (id, domain, attack_version, source_url, downloaded_at, object_count)
                VALUES (1, 'enterprise-attack', %s, %s, %s, %s)
                """,
                (version, source_url, datetime.now(timezone.utc), len(prepared)),
            )


def _insert_objects(connection, objects: list[dict]) -> None:
    rows = [
        (
            item["id"],
            item.get("type") or "",
            _text(item.get("name")) or None,
            _timestamp(item.get("modified")),
            bool(item.get("revoked")),
            bool(item.get("x_mitre_deprecated")),
            _attack_external_id(item),
            _json_text(item),
        )
        for item in objects
    ]
    connection.cursor().executemany(
        """
        INSERT INTO objects (stix_id, object_type, name, modified, revoked, deprecated, external_id, body)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
        """,
        rows,
    )


def _insert_references(connection, objects: list[dict]) -> None:
    rows = []
    for item in objects:
        for reference in item.get("external_references") or []:
            if not isinstance(reference, dict):
                continue
            rows.append(
                (
                    item["id"],
                    _text(reference.get("source_name")) or None,
                    _text(reference.get("external_id")) or None,
                    _text(reference.get("url")) or None,
                    _text(reference.get("description")) or None,
                )
            )
    if rows:
        connection.cursor().executemany(
            """
            INSERT INTO external_references (stix_id, source_name, external_id, url, description)
            VALUES (%s, %s, %s, %s, %s)
            """,
            rows,
        )


def _insert_relationships(connection, objects: list[dict], known_ids: set[str]) -> None:
    rows = []
    for item in objects:
        if item.get("type") != "relationship":
            continue
        relationship_type = _text(item.get("relationship_type"))
        source_ref = _text(item.get("source_ref"))
        target_ref = _text(item.get("target_ref"))
        if relationship_type not in RELATIONSHIP_TYPES:
            continue
        if source_ref not in known_ids or target_ref not in known_ids:
            continue
        rows.append((item["id"], relationship_type, source_ref, target_ref, _text(item.get("description")) or None))
    if rows:
        connection.cursor().executemany(
            """
            INSERT INTO relationships (stix_id, relationship_type, source_ref, target_ref, description)
            VALUES (%s, %s, %s, %s, %s)
            """,
            rows,
        )


def _insert_projected(connection, objects: list[dict], tactic_shortnames: dict[str, str]) -> None:
    tactic_rows = []
    technique_rows = []
    tactic_links = []
    shortname_to_id = {shortname: stix_id for stix_id, shortname in tactic_shortnames.items() if shortname}
    group_rows = []
    software_rows = []
    mitigation_rows = []
    campaign_rows = []
    for item in objects:
        kind = item.get("type")
        flags = (bool(item.get("revoked")), bool(item.get("x_mitre_deprecated")))
        url = _attack_url(item)
        name = _text(item.get("name")) or _attack_external_id(item) or item["id"]
        if kind == "x-mitre-tactic":
            tactic_rows.append((item["id"], _attack_external_id(item), _text(item.get("x_mitre_shortname")) or None, name, _text(item.get("description")) or None, url, *flags))
        elif kind == "attack-pattern":
            technique_rows.append((item["id"], _attack_external_id(item), name, _text(item.get("description")) or None, bool(item.get("x_mitre_is_subtechnique")), url, *flags))
            for phase in item.get("kill_chain_phases") or []:
                if not isinstance(phase, dict) or phase.get("kill_chain_name") != "mitre-attack":
                    continue
                tactic_id = shortname_to_id.get(_text(phase.get("phase_name")))
                if tactic_id:
                    tactic_links.append((item["id"], tactic_id))
        elif kind == "intrusion-set":
            group_rows.append((item["id"], _attack_external_id(item), name, _text(item.get("description")) or None, _aliases(item.get("aliases")), url, *flags))
        elif kind in ("malware", "tool"):
            software_rows.append((item["id"], _attack_external_id(item), name, "Malware" if kind == "malware" else "Tool", _text(item.get("description")) or None, _aliases(item.get("x_mitre_aliases")), url, *flags))
        elif kind == "course-of-action":
            mitigation_rows.append((item["id"], _attack_external_id(item), name, _text(item.get("description")) or None, url, *flags))
        elif kind == "campaign":
            campaign_rows.append((item["id"], _attack_external_id(item), name, _text(item.get("description")) or None, _text(item.get("first_seen")) or None, _text(item.get("last_seen")) or None, url, *flags))
    _executemany(connection, """
        INSERT INTO tactics (stix_id, external_id, shortname, name, description, url, revoked, deprecated)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """, tactic_rows)
    _executemany(connection, """
        INSERT INTO techniques (stix_id, external_id, name, description, is_subtechnique, url, revoked, deprecated)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """, technique_rows)
    _executemany(connection, """
        INSERT INTO technique_tactics (technique_stix_id, tactic_stix_id)
        VALUES (%s, %s)
        ON CONFLICT DO NOTHING
    """, tactic_links)
    connection.execute(
        """
        UPDATE techniques AS technique
        SET parent_stix_id = relationship.target_ref
        FROM relationships AS relationship
        WHERE relationship.relationship_type = 'subtechnique-of'
          AND relationship.source_ref = technique.stix_id
        """
    )
    _executemany(connection, """
        INSERT INTO groups (stix_id, external_id, name, description, aliases, url, revoked, deprecated)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """, group_rows)
    _executemany(connection, """
        INSERT INTO software (stix_id, external_id, name, software_type, description, aliases, url, revoked, deprecated)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, software_rows)
    _executemany(connection, """
        INSERT INTO mitigations (stix_id, external_id, name, description, url, revoked, deprecated)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, mitigation_rows)
    _executemany(connection, """
        INSERT INTO campaigns (stix_id, external_id, name, description, first_seen, last_seen, url, revoked, deprecated)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, campaign_rows)


def _executemany(connection, sql: str, rows: list[tuple]) -> None:
    if rows:
        connection.cursor().executemany(sql, rows)


def _get_json(url: str):
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "crq-mitre"},
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        return json.load(response)


def _release_version(release: dict) -> str:
    tag = str(release.get("tag_name") or "").strip()
    if tag.startswith("v") and tag[1:2].isdigit():
        return tag[1:]
    return tag


def _attack_external_id(item: dict) -> str | None:
    for reference in item.get("external_references") or []:
        if isinstance(reference, dict) and reference.get("source_name") == "mitre-attack" and reference.get("external_id"):
            return str(reference["external_id"]).strip()
    return None


def _attack_url(item: dict) -> str | None:
    for reference in item.get("external_references") or []:
        if isinstance(reference, dict) and reference.get("source_name") == "mitre-attack" and reference.get("url"):
            return str(reference["url"]).strip()
    return None


def _aliases(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _text(value) -> str:
    return str(value).strip() if value is not None else ""


def _timestamp(value):
    text = _text(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed


def _json_text(item: dict) -> str:
    return json.dumps(item, ensure_ascii=False).replace("\\u0000", "")


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
