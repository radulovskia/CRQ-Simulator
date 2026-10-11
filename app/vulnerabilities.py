import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import psycopg
from psycopg.rows import dict_row

from inventory import list_inventory

OSV_BATCH_URL = "https://api.osv.dev/v1/querybatch"
OSV_VULN_URL = "https://api.osv.dev/v1/vulns/"
NVD_CVE_URL = "https://services.nvd.nist.gov/rest/json/cves/2.0"
FIRST_EPSS_URL = "https://api.first.org/data/v1/epss"
MAX_PAGES = 20
NVD_BATCH_SIZE = 50
NVD_PUBLIC_PAUSE_SECONDS = 6
EPSS_CVE_PARAM_LIMIT = 2000
CVE_ID = re.compile(r"^CVE-\d{4}-\d+$", re.IGNORECASE)
CVSS_METRICS = (
    ("cvssMetricV40", "4.0"),
    ("cvssMetricV31", "3.1"),
    ("cvssMetricV30", "3.0"),
    ("cvssMetricV2", "2.0"),
)

CREATE_FINDINGS = """
CREATE TABLE IF NOT EXISTS findings (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    purl TEXT NOT NULL,
    vuln_id TEXT NOT NULL,
    modified TIMESTAMPTZ,
    cves TEXT,
    cvss_score DOUBLE PRECISION,
    cvss_version TEXT,
    epss DOUBLE PRECISION
)
"""

ADD_SCORE_COLUMNS = (
    "ALTER TABLE findings ADD COLUMN IF NOT EXISTS cves TEXT",
    "ALTER TABLE findings ADD COLUMN IF NOT EXISTS cvss_score DOUBLE PRECISION",
    "ALTER TABLE findings ADD COLUMN IF NOT EXISTS cvss_version TEXT",
    "ALTER TABLE findings ADD COLUMN IF NOT EXISTS epss DOUBLE PRECISION",
)

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
                for statement in ADD_SCORE_COLUMNS:
                    connection.execute(statement)
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
            SELECT purl, vuln_id, modified, cves, cvss_score, cvss_version, epss
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
                "cves": row["cves"],
                "cvss_score": row["cvss_score"],
                "cvss_version": row["cvss_version"],
                "epss": row["epss"],
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
        _attach_scores(findings)
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


def _attach_scores(findings: list[dict]) -> None:
    vuln_ids = list({item["vuln_id"] for item in findings})
    with ThreadPoolExecutor(max_workers=8) as pool:
        resolved = pool.map(_cves_for_vulnerability, vuln_ids)
    cves_by_vuln = dict(zip(vuln_ids, resolved))
    cves = sorted({cve for aliases in cves_by_vuln.values() for cve in aliases})
    cvss_by_cve = _cvss_by_cve(cves)
    epss_by_cve = _epss_by_cve(cves)

    for finding in findings:
        aliases = cves_by_vuln.get(finding["vuln_id"], [])
        finding["cves"] = ", ".join(aliases) if aliases else None
        cvss_matches = [cvss_by_cve[cve] for cve in aliases if cve in cvss_by_cve]
        if cvss_matches:
            score, version = max(cvss_matches, key=lambda item: item[0])
            finding["cvss_score"] = score
            finding["cvss_version"] = version
        else:
            finding["cvss_score"] = None
            finding["cvss_version"] = None
        epss_matches = [epss_by_cve[cve] for cve in aliases if cve in epss_by_cve]
        finding["epss"] = max(epss_matches) if epss_matches else None


def _cves_for_vulnerability(vuln_id: str) -> list[str]:
    if CVE_ID.fullmatch(vuln_id):
        return [vuln_id.upper()]
    try:
        document = _get_json(OSV_VULN_URL + urllib.parse.quote(vuln_id, safe=""))
    except (OsvError, TimeoutError, json.JSONDecodeError, UnicodeError):
        return []
    aliases = []
    for alias in document.get("aliases") or []:
        if isinstance(alias, str) and CVE_ID.fullmatch(alias):
            aliases.append(alias.upper())
    return sorted(set(aliases))


def _cvss_by_cve(cves: list[str]) -> dict[str, tuple[float, str]]:
    scores = {}
    api_key = os.environ.get("NVD_API_KEY")
    for index, batch in enumerate(_chunks(cves, NVD_BATCH_SIZE)):
        if index and not api_key:
            time.sleep(NVD_PUBLIC_PAUSE_SECONDS)
        try:
            payload = _get_json(
                f"{NVD_CVE_URL}?{urllib.parse.urlencode({'cveIds': ','.join(batch)})}",
                headers={"apiKey": api_key} if api_key else None,
                retries=2,
            )
        except (OsvError, TimeoutError, json.JSONDecodeError, UnicodeError):
            continue
        for vulnerability in payload.get("vulnerabilities") or []:
            cve = vulnerability.get("cve") or {}
            parsed = _primary_cvss(cve.get("metrics") or {})
            cve_id = cve.get("id")
            if cve_id and parsed:
                scores[str(cve_id).upper()] = parsed
    return scores


def _primary_cvss(metrics: dict) -> tuple[float, str] | None:
    for metric_name, fallback_version in CVSS_METRICS:
        entries = metrics.get(metric_name) or []
        if not entries:
            continue
        primary = next((entry for entry in entries if entry.get("type") == "Primary"), entries[0])
        data = primary.get("cvssData") or {}
        score = data.get("baseScore")
        if isinstance(score, (int, float)):
            return float(score), str(data.get("version") or fallback_version)
    return None


def _epss_by_cve(cves: list[str]) -> dict[str, float]:
    scores = {}
    for batch in _epss_batches(cves):
        offset = 0
        while offset < len(batch):
            try:
                payload = _get_json(
                    f"{FIRST_EPSS_URL}?{urllib.parse.urlencode({'cve': ','.join(batch), 'limit': len(batch), 'offset': offset})}"
                )
            except (OsvError, TimeoutError, json.JSONDecodeError, UnicodeError):
                break
            rows = payload.get("data") or []
            if not rows:
                break
            for row in rows:
                cve_id = str(row.get("cve") or "").upper()
                try:
                    scores[cve_id] = float(row["epss"])
                except (KeyError, TypeError, ValueError):
                    continue
            offset += len(rows)
            total = payload.get("total")
            if isinstance(total, int) and offset >= total:
                break
    return scores


def _epss_batches(cves: list[str]) -> list[list[str]]:
    batches = []
    current: list[str] = []
    length = 0
    for cve in cves:
        added = len(cve) if not current else len(cve) + 1
        if current and length + added > EPSS_CVE_PARAM_LIMIT:
            batches.append(current)
            current = [cve]
            length = len(cve)
        else:
            current.append(cve)
            length += added
    if current:
        batches.append(current)
    return batches


def _chunks(values: list[str], size: int) -> list[list[str]]:
    return [values[index:index + size] for index in range(0, len(values), size)]


def _get_json(url: str, headers: dict | None = None, retries: int = 0) -> dict:
    request_headers = {"User-Agent": "crq-vulnerability-scan", "Accept": "application/json"}
    if headers:
        request_headers.update({key: value for key, value in headers.items() if value})
    request = urllib.request.Request(url, headers=request_headers)
    attempt = 0
    while True:
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:300]
            if exc.code in (403, 429) and attempt < retries:
                attempt += 1
                time.sleep(NVD_PUBLIC_PAUSE_SECONDS)
                continue
            raise OsvError(f"Lookup returned {exc.code}. {detail}".strip()) from exc
        except urllib.error.URLError as exc:
            raise OsvError(f"Lookup failed: {exc.reason}") from exc


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
                        INSERT INTO findings (purl, vuln_id, modified, cves, cvss_score, cvss_version, epss)
                        VALUES (
                            %(purl)s, %(vuln_id)s, %(modified)s, %(cves)s,
                            %(cvss_score)s, %(cvss_version)s, %(epss)s
                        )
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
