import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime

import psycopg
from psycopg.rows import dict_row

from inventory import list_inventory

OSV_BATCH_URL = "https://api.osv.dev/v1/querybatch"
MAX_PAGES = 20

CREATE_FINDINGS = """
CREATE TABLE IF NOT EXISTS findings (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    purl TEXT NOT NULL,
    vuln_id TEXT NOT NULL,
    modified TIMESTAMPTZ
)
"""

CREATE_META = """
CREATE TABLE IF NOT EXISTS vulnerability_meta (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    extracted_at TIMESTAMPTZ NOT NULL
)
"""


class OsvError(Exception):
    pass


def vulnerability_database_url() -> str:
    url = os.environ.get("VULNERABILITY_DATABASE_URL")
    if not url:
        raise RuntimeError("VULNERABILITY_DATABASE_URL is not set")
    return url


def connect():
    return psycopg.connect(vulnerability_database_url(), row_factory=dict_row)


def init_vulnerability_db() -> None:
    _create_database()
    last_error = None
    for _ in range(30):
        try:
            with connect() as connection:
                connection.execute(CREATE_FINDINGS)
                connection.execute(CREATE_META)
                connection.commit()
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
                    "SELECT 1 FROM pg_database WHERE datname = 'vulnerabilities'"
                ).fetchone()
                if not exists:
                    connection.execute("CREATE DATABASE vulnerabilities")
            return
        except psycopg.OperationalError as exc:
            last_error = exc
            time.sleep(1)
    raise last_error


def list_findings() -> dict:
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT purl, vuln_id, modified
            FROM findings
            ORDER BY purl, vuln_id
            """
        ).fetchall()
        meta = connection.execute(
            "SELECT extracted_at FROM vulnerability_meta WHERE id = 1"
        ).fetchone()
    extracted_at = meta["extracted_at"].isoformat() if meta else None
    return {
        "items": [
            {
                "purl": row["purl"],
                "vuln_id": row["vuln_id"],
                "modified": row["modified"].isoformat() if row["modified"] else None,
            }
            for row in rows
        ],
        "extracted_at": extracted_at,
    }


def scan_vulnerabilities() -> tuple[int, dict]:
    purls = list(dict.fromkeys(item["purl"] for item in list_inventory()["items"] if item.get("purl")))
    if not purls:
        return 422, {"ok": False, "error": "Upload an asset inventory before scanning."}

    try:
        findings = _query_osv(purls)
    except OsvError as exc:
        return 502, {"ok": False, "error": str(exc)}

    _replace_findings(findings)
    stored = list_findings()
    return 200, {"ok": True, "count": len(stored["items"]), **stored}


def _query_osv(purls: list[str]) -> list[dict]:
    queries = [{"package": {"purl": purl}} for purl in purls]
    collected: dict[tuple[str, str], str | None] = {}

    for _ in range(MAX_PAGES):
        if not queries:
            break
        payload = _post_batch(queries)
        results = payload.get("results")
        if not isinstance(results, list) or len(results) != len(queries):
            raise OsvError("OSV returned a batch response that does not match the queries.")

        next_queries = []
        for query, result in zip(queries, results):
            purl = query["package"]["purl"]
            for vulnerability in result.get("vulns") or []:
                vuln_id = vulnerability.get("id")
                if vuln_id:
                    collected[(purl, vuln_id)] = vulnerability.get("modified")
            token = result.get("next_page_token")
            if token:
                next_queries.append({**query, "page_token": token})
        queries = next_queries
    else:
        if queries:
            raise OsvError("OSV kept returning another page of results.")

    return [
        {"purl": purl, "vuln_id": vuln_id, "modified": _parse_modified(modified)}
        for (purl, vuln_id), modified in collected.items()
    ]


def _post_batch(queries: list[dict]) -> dict:
    request = urllib.request.Request(
        OSV_BATCH_URL,
        data=json.dumps({"queries": queries}).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "crq-vulnerability-scan"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:300]
        raise OsvError(f"OSV returned {exc.code}. {detail}".strip()) from exc
    except urllib.error.URLError as exc:
        raise OsvError(f"The OSV request failed: {exc.reason}") from exc
    except TimeoutError as exc:
        raise OsvError("The OSV request timed out.") from exc


def _parse_modified(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def clear_findings() -> None:
    with connect() as connection:
        with connection.transaction():
            connection.execute("DELETE FROM findings")
            connection.execute("DELETE FROM vulnerability_meta")


def _replace_findings(findings: list[dict]) -> None:
    with connect() as connection:
        with connection.transaction():
            connection.execute("DELETE FROM findings")
            if findings:
                with connection.cursor() as cursor:
                    cursor.executemany(
                        """
                        INSERT INTO findings (purl, vuln_id, modified)
                        VALUES (%(purl)s, %(vuln_id)s, %(modified)s)
                        """,
                        findings,
                    )
            connection.execute(
                """
                INSERT INTO vulnerability_meta (id, extracted_at)
                VALUES (1, NOW())
                ON CONFLICT (id) DO UPDATE SET extracted_at = EXCLUDED.extracted_at
                """
            )
