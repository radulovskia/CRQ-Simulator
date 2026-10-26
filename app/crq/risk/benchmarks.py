"""Benchmark table used by Suggest.

The code dictionary is the shipped default. A saved Settings row replaces it.
Stored scenarios keep the numbers on their worksheets.
"""

import json
from datetime import datetime, timezone

from psycopg.types.json import Jsonb

from crq.catalog.catalog_io import connect, wait_for_database
from crq.version import BENCHMARKS_VERSION

LOSS_TYPES = ("Availability", "Integrity", "Confidentiality", "Fraud")
CLASSIFICATIONS = ("Public", "Internal", "Confidential")
CRITICALITIES = ("Low", "Medium", "High")

DEFAULT_BENCHMARKS = {
    "version": BENCHMARKS_VERSION,
    "targeting_multiplier": {"Low": 0.5, "Medium": 1.0, "High": 1.5},
    "reachability_unexposed": 0.25,
    "evidence_factor": {"none": 0.5, "low_cvss": 0.8, "high_cvss": 1.0, "unknown_cvss": 1.0, "exploited": 1.5},
    "cap": {
        "Fraud": 52,
        "Confidentiality": 12,
        "Availability": {"High": 4, "Medium": 6, "Low": 12},
        "Integrity": {"High": 4, "Medium": 6, "Low": 12},
    },
    "frequency_lambda": 3,
    "magnitude_lambda": 4,
    "replacement_fraction": {
        "Availability": [0.05, 0.20, 0.60],
        "Integrity": [0.05, 0.25, 0.75],
        "Confidentiality": [0, 0.02, 0.10],
        "Fraud": [0, 0.01, 0.05],
    },
    "response": {
        "Availability": [25000, 75000, 250000],
        "Integrity": [30000, 90000, 300000],
        "Fraud": [10000, 40000, 150000],
        "Confidentiality": {
            "Confidential": [50000, 150000, 500000],
            "Internal": [20000, 60000, 200000],
            "Public": [5000, 15000, 50000],
        },
    },
    "secondary_loss_probability": {
        "Confidentiality": {"Confidential": 0.70, "Internal": 0.30, "Public": 0.05},
        "Availability": {"exposed_high": 0.40, "other": 0.15},
        "Integrity": 0.50,
        "Fraud": 0.30,
    },
    "fine_per_record": {
        "Confidentiality": [0, 5, 25],
        "Integrity": [0, 5, 25],
        "Availability": [0, 1, 5],
        "Fraud": [0, 0, 0],
    },
    "fine_cap": 20_000_000,
    "reputation": {
        "High": [100000, 500000, 3000000],
        "Medium": [25000, 100000, 750000],
        "Low": [5000, 25000, 150000],
    },
    "competitive": [0, 50000, 500000],
}

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS benchmark_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    benchmarks JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    updated_by TEXT NOT NULL
)
"""


def init_benchmarks() -> None:
    wait_for_database(lambda connection: connection.execute(CREATE_TABLE))


def default_benchmarks() -> dict:
    return json.loads(json.dumps(DEFAULT_BENCHMARKS))


def active_benchmarks() -> dict:
    row = _row()
    if not row:
        return default_benchmarks()
    return _merge(default_benchmarks(), row["benchmarks"])


def benchmarks_version() -> str:
    return str(active_benchmarks()["version"])


def get_benchmarks() -> dict:
    row = _row()
    if not row:
        return {"saved": False, "updated_at": None, "updated_by": "", "benchmarks": default_benchmarks()}
    return {
        "saved": True,
        "updated_at": row["updated_at"].isoformat(),
        "updated_by": row["updated_by"],
        "benchmarks": _merge(default_benchmarks(), row["benchmarks"]),
    }


def save_benchmarks(payload: dict) -> tuple[int, dict]:
    errors: dict[str, str] = {}
    updated_by = str(payload.get("updated_by") or "").strip()
    if not updated_by:
        errors["updated_by"] = "Last modified by cannot be empty"
    source = payload.get("benchmarks")
    if not isinstance(source, dict):
        errors["benchmarks"] = "must be an object"
        return 422, {"ok": False, "errors": errors}
    cleaned = _clean(source, errors)
    if errors:
        return 422, {"ok": False, "errors": errors}
    stamp = datetime.now(timezone.utc)
    cleaned["version"] = stamp.strftime("%Y.%m.%d.%H%M%S")
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO benchmark_settings (id, benchmarks, updated_at, updated_by)
            VALUES (1, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                benchmarks = EXCLUDED.benchmarks,
                updated_at = EXCLUDED.updated_at,
                updated_by = EXCLUDED.updated_by
            """,
            (Jsonb(cleaned), stamp, updated_by),
        )
        connection.commit()
    return 200, {"ok": True, **get_benchmarks()}


def _row():
    with connect() as connection:
        return connection.execute("SELECT benchmarks, updated_at, updated_by FROM benchmark_settings WHERE id = 1").fetchone()


def _merge(default, stored):
    if isinstance(default, dict):
        incoming = stored if isinstance(stored, dict) else {}
        return {key: _merge(value, incoming.get(key)) for key, value in default.items()}
    if isinstance(default, list):
        if isinstance(stored, list) and len(stored) == len(default):
            return [float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else value for value in stored]
        return list(default)
    if stored is None:
        return default
    return stored


def _clean(source: dict, errors: dict) -> dict:
    cleaned = {
        "version": "",
        "targeting_multiplier": _numbers(source.get("targeting_multiplier"), "targeting_multiplier", CRITICALITIES, errors, minimum=0),
        "reachability_unexposed": _number(source.get("reachability_unexposed"), "reachability_unexposed", errors, minimum=0, maximum=1),
        "evidence_factor": _numbers(
            source.get("evidence_factor"),
            "evidence_factor",
            ("none", "low_cvss", "high_cvss", "unknown_cvss", "exploited"),
            errors,
            minimum=0,
        ),
        "cap": _caps(source.get("cap"), errors),
        "frequency_lambda": _number(source.get("frequency_lambda"), "frequency_lambda", errors, minimum=1, maximum=10),
        "magnitude_lambda": _number(source.get("magnitude_lambda"), "magnitude_lambda", errors, minimum=1, maximum=10),
        "replacement_fraction": _triples(source.get("replacement_fraction"), "replacement_fraction", LOSS_TYPES, errors, maximum=1),
        "response": _response(source.get("response"), errors),
        "secondary_loss_probability": _secondary(source.get("secondary_loss_probability"), errors),
        "fine_per_record": _triples(source.get("fine_per_record"), "fine_per_record", LOSS_TYPES, errors),
        "fine_cap": _number(source.get("fine_cap"), "fine_cap", errors, minimum=0),
        "reputation": _triples(source.get("reputation"), "reputation", CRITICALITIES, errors),
        "competitive": _triple(source.get("competitive"), "competitive", errors),
    }
    return cleaned


def _caps(value, errors: dict) -> dict:
    path = "cap"
    if not isinstance(value, dict):
        errors[path] = "must be an object"
        return {}
    return {
        "Fraud": _number(value.get("Fraud"), f"{path}.Fraud", errors, minimum=0),
        "Confidentiality": _number(value.get("Confidentiality"), f"{path}.Confidentiality", errors, minimum=0),
        "Availability": _numbers(value.get("Availability"), f"{path}.Availability", CRITICALITIES, errors, minimum=0),
        "Integrity": _numbers(value.get("Integrity"), f"{path}.Integrity", CRITICALITIES, errors, minimum=0),
    }


def _response(value, errors: dict) -> dict:
    path = "response"
    if not isinstance(value, dict):
        errors[path] = "must be an object"
        return {}
    confidentiality = value.get("Confidentiality")
    cleaned = {loss: _triple(value.get(loss), f"{path}.{loss}", errors) for loss in ("Availability", "Integrity", "Fraud")}
    if not isinstance(confidentiality, dict):
        errors[f"{path}.Confidentiality"] = "must be an object"
        cleaned["Confidentiality"] = {}
        return cleaned
    cleaned["Confidentiality"] = {
        name: _triple(confidentiality.get(name), f"{path}.Confidentiality.{name}", errors) for name in CLASSIFICATIONS
    }
    return cleaned


def _secondary(value, errors: dict) -> dict:
    path = "secondary_loss_probability"
    if not isinstance(value, dict):
        errors[path] = "must be an object"
        return {}
    return {
        "Confidentiality": _numbers(value.get("Confidentiality"), f"{path}.Confidentiality", CLASSIFICATIONS, errors, minimum=0, maximum=1),
        "Availability": _numbers(value.get("Availability"), f"{path}.Availability", ("exposed_high", "other"), errors, minimum=0, maximum=1),
        "Integrity": _number(value.get("Integrity"), f"{path}.Integrity", errors, minimum=0, maximum=1),
        "Fraud": _number(value.get("Fraud"), f"{path}.Fraud", errors, minimum=0, maximum=1),
    }


def _numbers(value, path: str, keys: tuple[str, ...], errors: dict, **bounds) -> dict:
    if not isinstance(value, dict):
        errors[path] = "must be an object"
        return {}
    return {key: _number(value.get(key), f"{path}.{key}", errors, **bounds) for key in keys}


def _triples(value, path: str, keys: tuple[str, ...], errors: dict, **bounds) -> dict:
    if not isinstance(value, dict):
        errors[path] = "must be an object"
        return {}
    return {key: _triple(value.get(key), f"{path}.{key}", errors, **bounds) for key in keys}


def _triple(value, path: str, errors: dict, **bounds):
    if isinstance(value, dict):
        parts = [value.get("minimum"), value.get("mode"), value.get("maximum")]
    elif isinstance(value, list):
        parts = value
    else:
        errors[path] = "must be minimum, mode, and maximum"
        return []
    if len(parts) != 3:
        errors[path] = "must be minimum, mode, and maximum"
        return []
    names = ("minimum", "mode", "maximum")
    numbers = [_number(part, f"{path}.{name}", errors, minimum=0, **bounds) for name, part in zip(names, parts)]
    if any(number is None for number in numbers):
        return []
    if not numbers[0] <= numbers[1] <= numbers[2]:
        errors[path] = "minimum, mode, and maximum are out of order"
    return numbers


def _number(value, path: str, errors: dict, *, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        errors[path] = "must be a number"
        return None
    number = float(value)
    if minimum is not None and number < minimum:
        errors[path] = f"must be at least {minimum}"
        return None
    if maximum is not None and number > maximum:
        errors[path] = f"must be at most {maximum}"
        return None
    return number
