from crq.catalog.catalog_io import connect, number_error, parse_int, parse_number, rename_column, wait_for_database

COLUMNS = (
    "Statement",
    "Portfolio ALE Limit",
    "Portfolio VaR95 Limit",
    "Scenario ALE Tolerance",
    "Annual Treatment Budget",
    "Approval Threshold",
    "Amortisation Years",
    "Updated By",
)

DB_FIELDS = {
    "Statement": "statement",
    "Portfolio ALE Limit": "portfolio_ale_limit",
    "Portfolio VaR95 Limit": "portfolio_var95_limit",
    "Scenario ALE Tolerance": "scenario_ale_tolerance",
    "Annual Treatment Budget": "annual_treatment_budget",
    "Approval Threshold": "approval_threshold",
    "Amortisation Years": "amortisation_years",
    "Updated By": "updated_by",
}

LIMIT_FIELDS = (
    "portfolio_ale_limit",
    "portfolio_var95_limit",
    "scenario_ale_tolerance",
    "annual_treatment_budget",
    "approval_threshold",
)

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS risk_appetite (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    statement TEXT NOT NULL,
    portfolio_ale_limit DOUBLE PRECISION,
    portfolio_var95_limit DOUBLE PRECISION,
    scenario_ale_tolerance DOUBLE PRECISION,
    annual_treatment_budget DOUBLE PRECISION,
    approval_threshold DOUBLE PRECISION,
    amortisation_years INTEGER NOT NULL DEFAULT 3,
    updated_at TIMESTAMPTZ NOT NULL,
    updated_by TEXT NOT NULL
)
"""


def init_appetite() -> None:
    def apply(connection) -> None:
        connection.execute(CREATE_TABLE)
        for old, new in (
            ("portfolio_ale_limit_eur", "portfolio_ale_limit"),
            ("portfolio_var95_limit_eur", "portfolio_var95_limit"),
            ("scenario_ale_tolerance_eur", "scenario_ale_tolerance"),
            ("annual_treatment_budget_eur", "annual_treatment_budget"),
            ("approval_threshold_eur", "approval_threshold"),
        ):
            rename_column(connection, "risk_appetite", old, new)

    wait_for_database(apply)


def get_appetite() -> dict:
    with connect() as connection:
        row = connection.execute("SELECT * FROM risk_appetite WHERE id = 1").fetchone()
    if not row:
        return {
            "defined": False,
            "statement": "",
            "portfolio_ale_limit": None,
            "portfolio_var95_limit": None,
            "scenario_ale_tolerance": None,
            "annual_treatment_budget": None,
            "approval_threshold": None,
            "amortisation_years": 3,
            "updated_at": None,
            "updated_by": "",
        }
    payload = dict(row)
    payload.pop("id", None)
    payload["defined"] = True
    payload["updated_at"] = row["updated_at"].isoformat()
    return payload


def save_appetite(fields: dict) -> tuple[int, dict]:
    errors = _validate_fields(fields)
    if errors:
        return 422, {"ok": False, "errors": errors}
    cleaned = _clean(fields)
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO risk_appetite (
                id, statement, portfolio_ale_limit, portfolio_var95_limit,
                scenario_ale_tolerance, annual_treatment_budget, approval_threshold,
                amortisation_years, updated_at, updated_by
            )
            VALUES (
                1, %(statement)s, %(portfolio_ale_limit)s, %(portfolio_var95_limit)s,
                %(scenario_ale_tolerance)s, %(annual_treatment_budget)s, %(approval_threshold)s,
                %(amortisation_years)s, NOW(), %(updated_by)s
            )
            ON CONFLICT (id) DO UPDATE SET
                statement = EXCLUDED.statement,
                portfolio_ale_limit = EXCLUDED.portfolio_ale_limit,
                portfolio_var95_limit = EXCLUDED.portfolio_var95_limit,
                scenario_ale_tolerance = EXCLUDED.scenario_ale_tolerance,
                annual_treatment_budget = EXCLUDED.annual_treatment_budget,
                approval_threshold = EXCLUDED.approval_threshold,
                amortisation_years = EXCLUDED.amortisation_years,
                updated_at = NOW(),
                updated_by = EXCLUDED.updated_by
            """,
            cleaned,
        )
        connection.commit()
    return 200, {"ok": True, **get_appetite()}


def _validate_fields(fields: dict) -> dict:
    return _validate_values({column: fields.get(DB_FIELDS[column], "") for column in COLUMNS})


def _validate_values(values: dict) -> dict:
    errors = {}
    if not str(values.get("Statement") or "").strip():
        errors["Statement"] = "must not be empty"
    if not str(values.get("Updated By") or "").strip():
        errors["Updated By"] = "must not be empty"
    for column in (
        "Portfolio ALE Limit",
        "Portfolio VaR95 Limit",
        "Scenario ALE Tolerance",
        "Annual Treatment Budget",
        "Approval Threshold",
    ):
        error = number_error(values.get(column, ""), allow_blank=True, minimum=0)
        if error:
            errors[column] = error
    years = number_error(values.get("Amortisation Years", ""), allow_blank=False, minimum=1, maximum=10, integer=True)
    if years:
        errors["Amortisation Years"] = years
    return errors


def _clean(fields: dict) -> dict:
    cleaned = {
        "statement": str(fields.get("statement") or "").strip(),
        "updated_by": str(fields.get("updated_by") or "").strip(),
        "amortisation_years": parse_int(fields.get("amortisation_years")),
    }
    for field in LIMIT_FIELDS:
        cleaned[field] = parse_number(fields.get(field))
    return cleaned
