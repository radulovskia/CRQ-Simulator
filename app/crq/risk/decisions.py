import hashlib
import json
from datetime import datetime, timezone

from psycopg.types.json import Json

from crq.catalog.catalog_io import connect, wait_for_database

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS decision_records (
    record_id TEXT PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL,
    title TEXT NOT NULL,
    prepared_by TEXT NOT NULL,
    status TEXT NOT NULL,
    approved_by TEXT,
    approved_at TIMESTAMPTZ,
    approval_note TEXT,
    model_version TEXT NOT NULL,
    benchmarks_version TEXT NOT NULL,
    seed INTEGER NOT NULL,
    iterations INTEGER NOT NULL,
    content_hash TEXT NOT NULL,
    report JSONB NOT NULL,
    inputs JSONB NOT NULL,
    assumptions JSONB NOT NULL
)
"""


def init_decisions() -> None:
    def apply(connection) -> None:
        connection.execute(CREATE_TABLE)

    wait_for_database(apply)


def _json_default(value):
    if hasattr(value, "item"):
        return _json_default(value.item())
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def normalize(value):
    def fold(item):
        if isinstance(item, dict):
            return {str(key): fold(inner) for key, inner in item.items()}
        if isinstance(item, list):
            return [fold(inner) for inner in item]
        if isinstance(item, bool) or item is None or isinstance(item, str):
            return item
        if isinstance(item, int) and not isinstance(item, bool):
            return item
        if isinstance(item, float):
            if item != item or item in (float("inf"), float("-inf")):
                return None
            return int(item) if item.is_integer() else item
        return item

    return fold(json.loads(json.dumps(value, default=_json_default)))


def canonical(value) -> str:
    return json.dumps(normalize(value), sort_keys=True, separators=(",", ":"))


def content_hash(report: dict) -> str:
    payload = normalize(report)
    payload.setdefault("meta", {})["content_hash"] = None
    return hashlib.sha256(canonical(payload).encode()).hexdigest()


def next_record_id(connection) -> str:
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    count = connection.execute(
        """
        SELECT COUNT(*) AS count
        FROM decision_records
        WHERE to_char(created_at AT TIME ZONE 'UTC', 'YYYYMMDD') = %s
        """,
        (today,),
    ).fetchone()["count"]
    return f"DR-{today}-{count + 1:03d}"


def insert_record(record: dict) -> dict:
    with connect() as connection:
        with connection.transaction():
            record["record_id"] = next_record_id(connection)
            record["report"] = normalize(record["report"])
            record["inputs"] = normalize(record["inputs"])
            record["assumptions"] = normalize(record["assumptions"])
            record["report"]["meta"]["record_id"] = record["record_id"]
            record["report"]["meta"]["content_hash"] = None
            record["report"]["meta"]["status"] = "Proposed"
            record["content_hash"] = content_hash(record["report"])
            record["report"]["meta"]["content_hash"] = record["content_hash"]
            connection.execute(
                """
                INSERT INTO decision_records (
                    record_id, created_at, title, prepared_by, status, approved_by, approved_at, approval_note,
                    model_version, benchmarks_version, seed, iterations, content_hash, report, inputs, assumptions
                )
                VALUES (
                    %(record_id)s, NOW(), %(title)s, %(prepared_by)s, 'Proposed', NULL, NULL, NULL,
                    %(model_version)s, %(benchmarks_version)s, %(seed)s, %(iterations)s, %(content_hash)s,
                    %(report)s, %(inputs)s, %(assumptions)s
                )
                """,
                {
                    **record,
                    "report": Json(record["report"]),
                    "inputs": Json(record["inputs"]),
                    "assumptions": Json(record["assumptions"]),
                },
            )
    return get_decision(record["record_id"])


def list_decisions() -> dict:
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT record_id, created_at, title, prepared_by, status, approved_by, approved_at,
                   model_version, benchmarks_version, seed, iterations, report
            FROM decision_records
            ORDER BY created_at DESC
            """
        ).fetchall()
    items = []
    for row in rows:
        report = row["report"] or {}
        portfolio = ((report.get("portfolio") or {}).get("current") or {}).get("mean")
        appetite = ((report.get("appetite") or {}).get("evaluation") or {}).get("portfolio_ale") or {}
        items.append(
            {
                "record_id": row["record_id"],
                "created_at": row["created_at"].isoformat(),
                "title": row["title"],
                "prepared_by": row["prepared_by"],
                "status": row["status"],
                "approved_by": row["approved_by"],
                "approved_at": row["approved_at"].isoformat() if row["approved_at"] else None,
                "model_version": row["model_version"],
                "portfolio_current_mean": portfolio,
                "appetite_status": appetite.get("status"),
                "decision_count": len(report.get("decisions") or []),
            }
        )
    return {"items": items}


def get_decision(record_id: str) -> dict | None:
    with connect() as connection:
        row = connection.execute("SELECT * FROM decision_records WHERE record_id = %s", (record_id,)).fetchone()
    if not row:
        return None
    return _present(row)


def verify_decision(record_id: str) -> dict | None:
    with connect() as connection:
        row = connection.execute(
            "SELECT record_id, content_hash, report FROM decision_records WHERE record_id = %s",
            (record_id,),
        ).fetchone()
    if not row:
        return None
    return {"record_id": row["record_id"], "valid": content_hash(row["report"]) == row["content_hash"]}


def approve_decision(record_id: str, status: str, approved_by: str, note: str) -> tuple[int, dict]:
    if status not in ("Approved", "Rejected"):
        return 422, {"detail": 'status must be "Approved" or "Rejected"'}
    if not str(approved_by or "").strip():
        return 422, {"detail": "approved_by must not be empty"}
    if not str(note or "").strip():
        return 422, {"detail": "note must not be empty"}
    with connect() as connection:
        row = connection.execute("SELECT status FROM decision_records WHERE record_id = %s", (record_id,)).fetchone()
        if not row:
            return 404, {"detail": "That decision record was not found."}
        if row["status"] != "Proposed":
            return 409, {"detail": f"Decision record {record_id} is already {row['status']}."}
        connection.execute(
            """
            UPDATE decision_records
            SET status = %s, approved_by = %s, approved_at = NOW(), approval_note = %s
            WHERE record_id = %s
            """,
            (status, approved_by.strip(), str(note or "").strip(), record_id),
        )
        connection.commit()
    return 200, get_decision(record_id)


def _present(row: dict) -> dict:
    report = json.loads(canonical(row["report"]))
    report.setdefault("meta", {})["status"] = row["status"]
    return {
        "record_id": row["record_id"],
        "created_at": row["created_at"].isoformat(),
        "title": row["title"],
        "prepared_by": row["prepared_by"],
        "status": row["status"],
        "approved_by": row["approved_by"],
        "approved_at": row["approved_at"].isoformat() if row["approved_at"] else None,
        "approval_note": row["approval_note"],
        "model_version": row["model_version"],
        "benchmarks_version": row["benchmarks_version"],
        "seed": row["seed"],
        "iterations": row["iterations"],
        "content_hash": row["content_hash"],
        "report": report,
        "inputs": row["inputs"],
        "assumptions": row["assumptions"],
    }
