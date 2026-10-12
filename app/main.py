from contextlib import asynccontextmanager

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, model_validator

from inventory import init_db, list_inventory, process_upload
from processes import add_process, init_processes, list_processes, update_process, upload_processes
from systems import add_system, init_systems, list_systems, update_system, upload_systems
from units import add_unit, init_units, list_units, update_unit, upload_units
from vulnerabilities import clear_findings, init_vulnerability_db, list_findings, scan_vulnerabilities
from monte_carlo import run_monte_carlo


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    init_units()
    init_systems()
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
    return JSONResponse(status_code=status_code, content=body)


class UnitBody(BaseModel):
    ou_id: str = ""
    organisational_unit: str = ""
    primary_responsibilities: str = ""
    oversight: str = ""


class UnitUpdateBody(UnitBody):
    previous_ou_id: str = ""


class SystemBody(BaseModel):
    system_id: str = ""
    software_system: str = ""
    primary_function: str = ""
    business_owner_ou_id: str = ""
    technical_custodian_ou_id: str = ""
    criticality: str = ""
    data_classification: str = ""
    deployment: str = ""


class SystemUpdateBody(SystemBody):
    previous_system_id: str = ""


class ProcessEntryBody(BaseModel):
    bp_id: str = ""
    ou_id: str = ""
    business_process: str = ""
    activity_scope: str = ""
    primary_system_ids: str = ""
    criticality: str = ""
    key_information: str = ""


class ProcessUpdateBody(ProcessEntryBody):
    previous_bp_id: str = ""


@app.get("/units")
def get_units() -> dict:
    return list_units()


@app.post("/units")
async def post_units(file: UploadFile = File(...)) -> JSONResponse:
    content = await file.read()
    status_code, body = upload_units(file.filename or "", content)
    return JSONResponse(status_code=status_code, content=body)


@app.post("/units/entry")
def post_unit_entry(body: UnitBody) -> JSONResponse:
    status_code, payload = add_unit(body.model_dump())
    return JSONResponse(status_code=status_code, content=payload)


@app.put("/units/entry")
def put_unit_entry(body: UnitUpdateBody) -> JSONResponse:
    status_code, payload = update_unit(body.previous_ou_id, body.model_dump())
    return JSONResponse(status_code=status_code, content=payload)


@app.get("/systems")
def get_systems() -> dict:
    return list_systems()


@app.post("/systems")
async def post_systems(file: UploadFile = File(...)) -> JSONResponse:
    content = await file.read()
    status_code, body = upload_systems(file.filename or "", content)
    return JSONResponse(status_code=status_code, content=body)


@app.post("/systems/entry")
def post_system_entry(body: SystemBody) -> JSONResponse:
    status_code, payload = add_system(body.model_dump())
    return JSONResponse(status_code=status_code, content=payload)


@app.put("/systems/entry")
def put_system_entry(body: SystemUpdateBody) -> JSONResponse:
    status_code, payload = update_system(body.previous_system_id, body.model_dump())
    return JSONResponse(status_code=status_code, content=payload)


@app.get("/processes")
def get_processes() -> dict:
    return list_processes()


@app.post("/processes")
async def post_processes(file: UploadFile = File(...)) -> JSONResponse:
    content = await file.read()
    status_code, body = upload_processes(file.filename or "", content)
    return JSONResponse(status_code=status_code, content=body)


@app.post("/processes/entry")
def post_process_entry(body: ProcessEntryBody) -> JSONResponse:
    status_code, payload = add_process(body.model_dump())
    return JSONResponse(status_code=status_code, content=payload)


@app.put("/processes/entry")
def put_process_entry(body: ProcessUpdateBody) -> JSONResponse:
    status_code, payload = update_process(body.previous_bp_id, body.model_dump())
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
