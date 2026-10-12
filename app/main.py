from contextlib import asynccontextmanager

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, model_validator

from inventory import init_db, list_inventory, process_upload
from processes import (
    add_entries,
    add_entry,
    init_processes,
    list_processes,
    missing_names,
    process_catalog_upload,
    update_entry,
)
from vulnerabilities import clear_findings, init_vulnerability_db, list_findings, scan_vulnerabilities
from monte_carlo import run_monte_carlo


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    init_processes()
    init_vulnerability_db()
    yield


app = FastAPI(
    title="CRQ Monte Carlo API",
    description=(
        "Monte Carlo simulation for frequency and magnitude using "
        "independent Beta PERT distributions."
    ),
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class VariableInput(BaseModel):
    minimum: float = Field(..., description="Minimum value of the distribution")
    mode: float = Field(..., description="Most likely value (mode)")
    maximum: float = Field(..., description="Maximum value of the distribution")
    lambda_param: float = Field(
        4.0,
        ge=1,
        le=10,
        description="PERT confidence level / lambda shape parameter (1-10, default 4)",
    )

    @model_validator(mode="after")
    def check_value_order(self) -> "VariableInput":
        if not (self.minimum < self.maximum):
            raise ValueError("Minimum must be less than maximum")
        if not (self.minimum <= self.mode <= self.maximum):
            raise ValueError("Mode must satisfy minimum <= mode <= maximum")
        return self


class MCRequest(BaseModel):
    frequency: VariableInput
    magnitude: VariableInput
    iterations: int = Field(10_000, ge=1_000, le=1_000_000, description="Number of simulation draws")
    seed: int | None = Field(None, description="Optional RNG seed for reproducibility")


class DistributionResponse(BaseModel):
    type: str
    minimum: float
    mode: float
    maximum: float
    alpha: float
    beta: float
    lambda_param: float


class HistogramResponse(BaseModel):
    bin_edges: list[float]
    counts: list[int]


class ExceedancePointResponse(BaseModel):
    loss: float
    exceedance_probability: float


class ExceedanceCurveResponse(BaseModel):
    points: list[ExceedancePointResponse]


class ScatterPointResponse(BaseModel):
    frequency: float
    magnitude: float
    aggregate_loss: float


class VariableResponse(BaseModel):
    mean: float
    median: float
    std: float
    p5: float
    p50: float
    p95: float
    p99: float
    min: float
    max: float
    distribution: DistributionResponse
    histogram: HistogramResponse


class AggregateLossResponse(BaseModel):
    mean: float
    median: float
    std: float
    p5: float
    p50: float
    p95: float
    p99: float
    min: float
    max: float
    var_95: float
    var_99: float
    tvar_95: float
    tvar_99: float
    histogram: HistogramResponse
    exceedance_curve: ExceedanceCurveResponse


class MCResponse(BaseModel):
    iterations: int
    seed: int
    frequency: VariableResponse
    magnitude: VariableResponse
    aggregate_loss: AggregateLossResponse
    scatter: list[ScatterPointResponse]
    input: MCRequest


def _variable_response(result) -> VariableResponse:
    return VariableResponse(
        mean=result.mean,
        median=result.median,
        std=result.std,
        p5=result.p5,
        p50=result.p50,
        p95=result.p95,
        p99=result.p99,
        min=result.min,
        max=result.max,
        distribution=DistributionResponse(
            type=result.distribution.distribution,
            minimum=result.distribution.minimum,
            mode=result.distribution.mode,
            maximum=result.distribution.maximum,
            alpha=result.distribution.alpha,
            beta=result.distribution.beta,
            lambda_param=result.distribution.lambda_param,
        ),
        histogram=HistogramResponse(
            bin_edges=result.histogram.bin_edges,
            counts=result.histogram.counts,
        ),
    )


def _aggregate_loss_response(result) -> AggregateLossResponse:
    return AggregateLossResponse(
        mean=result.mean,
        median=result.median,
        std=result.std,
        p5=result.p5,
        p50=result.p50,
        p95=result.p95,
        p99=result.p99,
        min=result.min,
        max=result.max,
        var_95=result.var_95,
        var_99=result.var_99,
        tvar_95=result.tvar_95,
        tvar_99=result.tvar_99,
        histogram=HistogramResponse(
            bin_edges=result.histogram.bin_edges,
            counts=result.histogram.counts,
        ),
        exceedance_curve=ExceedanceCurveResponse(
            points=[
                ExceedancePointResponse(
                    loss=point.loss,
                    exceedance_probability=point.exceedance_probability,
                )
                for point in result.exceedance_curve.points
            ]
        ),
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/inventory")
def get_inventory() -> dict:
    return list_inventory()


@app.get("/vulnerabilities")
def get_vulnerabilities() -> dict:
    return list_findings()


@app.post("/vulnerabilities")
def post_vulnerabilities() -> JSONResponse:
    status_code, body = scan_vulnerabilities()
    return JSONResponse(status_code=status_code, content=body)


@app.post("/inventory")
async def post_inventory(file: UploadFile = File(...)) -> JSONResponse:
    content = await file.read()
    status_code, body = process_upload(file.filename or "", content)
    if status_code == 200:
        clear_findings()
        _scan_status, scan_body = scan_vulnerabilities()
        body["scan_ok"] = bool(scan_body.get("ok"))
        if scan_body.get("ok"):
            body["vulnerability_count"] = scan_body.get("count", 0)
        else:
            body["scan_error"] = scan_body.get("error") or "The vulnerability scan failed."
        names = [item["business_process"] for item in list_inventory()["items"]]
        body["missing_business_processes"] = missing_names(names)
    return JSONResponse(status_code=status_code, content=body)


class ProcessEntryBody(BaseModel):
    business_process: str = ""
    organisational_unit: str = ""
    criticality: str = ""


class ProcessUpdateBody(ProcessEntryBody):
    id: int


class ProcessEntriesBody(BaseModel):
    entries: list[ProcessEntryBody]


@app.get("/processes")
def get_processes() -> dict:
    return list_processes()


@app.get("/processes/missing")
def get_missing_processes() -> dict:
    names = [item["business_process"] for item in list_inventory()["items"]]
    return {"names": missing_names(names)}


@app.post("/processes")
async def post_processes(file: UploadFile = File(...)) -> JSONResponse:
    content = await file.read()
    status_code, body = process_catalog_upload(file.filename or "", content)
    return JSONResponse(status_code=status_code, content=body)


@app.post("/processes/entry")
def post_process_entry(body: ProcessEntryBody) -> JSONResponse:
    status_code, payload = add_entry(body.model_dump())
    return JSONResponse(status_code=status_code, content=payload)


@app.put("/processes/entry")
def put_process_entry(body: ProcessUpdateBody) -> JSONResponse:
    status_code, payload = update_entry(body.id, body.model_dump())
    return JSONResponse(status_code=status_code, content=payload)


@app.post("/processes/entries")
def post_process_entries(body: ProcessEntriesBody) -> JSONResponse:
    status_code, payload = add_entries([entry.model_dump() for entry in body.entries])
    return JSONResponse(status_code=status_code, content=payload)


@app.post("/mc", response_model=MCResponse)
def monte_carlo(body: MCRequest) -> MCResponse:
    """
    Run a Monte Carlo simulation for frequency and magnitude.

    Each variable is modeled with its own Beta PERT distribution derived from
    a three-point estimate. Both variables share the same iteration count and
    RNG seed.
    """
    try:
        result = run_monte_carlo(
            frequency_minimum=body.frequency.minimum,
            frequency_mode=body.frequency.mode,
            frequency_maximum=body.frequency.maximum,
            frequency_lambda=body.frequency.lambda_param,
            magnitude_minimum=body.magnitude.minimum,
            magnitude_mode=body.magnitude.mode,
            magnitude_maximum=body.magnitude.maximum,
            magnitude_lambda=body.magnitude.lambda_param,
            iterations=body.iterations,
            seed=body.seed,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return MCResponse(
        iterations=result.iterations,
        seed=result.seed,
        frequency=_variable_response(result.frequency),
        magnitude=_variable_response(result.magnitude),
        aggregate_loss=_aggregate_loss_response(result.aggregate_loss),
        scatter=[
            ScatterPointResponse(
                frequency=point.frequency,
                magnitude=point.magnitude,
                aggregate_loss=point.aggregate_loss,
            )
            for point in result.scatter
        ],
        input=body,
    )


@app.get("/mc", response_model=MCResponse)
def monte_carlo_get(
    frequency_minimum: float = Query(..., description="Frequency minimum"),
    frequency_mode: float = Query(..., description="Frequency mode"),
    frequency_maximum: float = Query(..., description="Frequency maximum"),
    frequency_lambda: float = Query(4.0, ge=1, le=10, description="Frequency confidence level (lambda)"),
    magnitude_minimum: float = Query(..., description="Magnitude minimum"),
    magnitude_mode: float = Query(..., description="Magnitude mode"),
    magnitude_maximum: float = Query(..., description="Magnitude maximum"),
    magnitude_lambda: float = Query(4.0, ge=1, le=10, description="Magnitude confidence level (lambda)"),
    iterations: int = Query(10_000, ge=1_000, le=1_000_000),
    seed: int | None = Query(None),
) -> MCResponse:
    """GET variant of /mc for quick testing from a browser or curl."""
    return monte_carlo(
        MCRequest(
            frequency=VariableInput(
                minimum=frequency_minimum,
                mode=frequency_mode,
                maximum=frequency_maximum,
                lambda_param=frequency_lambda,
            ),
            magnitude=VariableInput(
                minimum=magnitude_minimum,
                mode=magnitude_mode,
                maximum=magnitude_maximum,
                lambda_param=magnitude_lambda,
            ),
            iterations=iterations,
            seed=seed,
        )
    )
