"""FAIR scenario, treatment, report, and decision routes."""

from fastapi import File, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from crq.intelligence.actors import add_actor, delete_actor, list_actors, update_actor, upload_actors
from crq.risk.appetite import get_appetite, save_appetite
from crq.risk.benchmarks import benchmarks_version, get_benchmarks, save_benchmarks
from crq.risk.controls import add_control, delete_control, list_controls, update_control, upload_controls
from crq.risk.decisions import approve_decision, get_decision, insert_record, list_decisions, verify_decision
from crq.risk.monte_carlo import run_fair_simulation
from crq.risk.portfolio import build_register, run_control_set
from crq.risk.report import assumptions_for, build_report, public_treatments
from crq.risk.report import snapshot_inputs
from crq.risk.risk_engine import (
    apply_controls,
    build_target_context,
    collapse,
    data_quality,
    effective_factors,
    exposure_summary,
    load_scenario_context,
    suggest_factors,
)
from crq.risk.scenario_controls import (
    add_scenario_control,
    delete_scenario_control,
    list_scenario_controls,
    update_scenario_control,
    upload_scenario_controls,
)
from crq.risk.scenarios import add_scenario, delete_scenario, list_scenarios, update_scenario, upload_scenarios
from crq.risk.treatment import build_treatments
from crq.intelligence.vectors import add_vector, delete_vector, list_vectors, update_vector, upload_vectors
from crq.version import INDEPENDENCE_NOTE, MODEL_VERSION


class EntryBody(BaseModel):
    model_config = ConfigDict(extra="allow")


def _json(status: int, payload: dict) -> JSONResponse:
    return JSONResponse(status_code=status, content=payload)


def _triple(values) -> dict:
    return {"minimum": values[0], "mode": values[1], "maximum": values[2]}


def _context_or_404(scenario_id: str) -> dict:
    context = load_scenario_context(scenario_id)
    if not context:
        raise HTTPException(status_code=404, detail="That risk scenario was not found.")
    return context


def scenario_inputs(context: dict, control_set: str, control_ids: list[str] | None) -> dict:
    applied = apply_controls(context, control_set, control_ids)
    factors = effective_factors(context, applied)
    collapsed = collapse(factors)
    scenario = context["scenario"]
    return {
        "scenario_id": scenario.get("scenario_id"),
        "scenario": scenario.get("scenario"),
        "control_set": control_set,
        "eliminated": applied["eliminated"],
        "eliminated_by": applied["eliminated_by"],
        "applied_controls": applied["applied_controls"],
        "frequency": {**_triple(collapsed["frequency"]), "lambda": collapsed["frequency_lambda"]},
        "magnitude": {**_triple(collapsed["magnitude"]), "lambda": collapsed["magnitude_lambda"]},
        "primary": {name: _triple(triple) for name, triple in collapsed["primary"].items()},
        "secondary": {name: _triple(triple) for name, triple in collapsed["secondary"].items()},
        "secondary_loss_probability": collapsed["slp"],
        "analytic_ale": collapsed["analytic_ale"],
        "exposure": exposure_summary(context),
        "data_quality": data_quality(context),
    }


def public_register(register: dict) -> dict:
    return {
        "iterations": register["iterations"],
        "seed": register["seed"],
        "independence_note": INDEPENDENCE_NOTE,
        "items": [{key: value for key, value in item.items() if key not in ("context", "runs")} for item in register["items"]],
        "portfolio": register["portfolio"],
        "curves": register["curves"],
        "appetite": register["appetite"],
        "evaluation": register["evaluation"],
        "benchmarks_version": benchmarks_version(),
    }


def _fair_response(types, fair, body, scenario: dict | None):
    result = fair.simulation
    breakdown = types["BreakdownResponse"](
        probability_of_loss_year=fair.probability_of_loss_year,
        expected_annual_loss_by_form=fair.expected_annual_loss_by_form,
        expected_primary=fair.expected_primary,
        expected_secondary=fair.expected_secondary,
    )
    return types["MCResponse"](
        iterations=result.iterations,
        seed=result.seed,
        frequency=types["variable"](result.frequency),
        magnitude=types["variable"](result.magnitude),
        aggregate_loss=types["aggregate"](result.aggregate_loss),
        scatter=[
            types["ScatterPointResponse"](
                frequency=point.frequency,
                magnitude=point.magnitude,
                aggregate_loss=point.aggregate_loss,
            )
            for point in result.scatter
        ],
        input=body,
        breakdown=breakdown,
        scenario=scenario,
    )


def mount(app, types) -> None:
    @app.get("/actors")
    def get_actors() -> dict:
        return list_actors()

    @app.post("/actors")
    async def post_actors(file: UploadFile = File(...)) -> JSONResponse:
        content = await file.read()
        return _json(*upload_actors(file.filename or "", content))

    @app.post("/actors/entry")
    def post_actor_entry(body: EntryBody) -> JSONResponse:
        return _json(*add_actor(body.model_dump()))

    @app.put("/actors/entry")
    def put_actor_entry(body: EntryBody) -> JSONResponse:
        payload = body.model_dump()
        return _json(*update_actor(str(payload.get("previous_actor_id") or ""), payload))

    @app.delete("/actors/entry")
    def delete_actor_entry(actor_id: str = Query(...)) -> JSONResponse:
        return _json(*delete_actor(actor_id))

    @app.get("/vectors")
    def get_vectors() -> dict:
        return list_vectors()

    @app.post("/vectors")
    async def post_vectors(file: UploadFile = File(...)) -> JSONResponse:
        content = await file.read()
        return _json(*upload_vectors(file.filename or "", content))

    @app.post("/vectors/entry")
    def post_vector_entry(body: EntryBody) -> JSONResponse:
        return _json(*add_vector(body.model_dump()))

    @app.put("/vectors/entry")
    def put_vector_entry(body: EntryBody) -> JSONResponse:
        payload = body.model_dump()
        return _json(*update_vector(str(payload.get("previous_vector_id") or ""), payload))

    @app.delete("/vectors/entry")
    def delete_vector_entry(vector_id: str = Query(...)) -> JSONResponse:
        return _json(*delete_vector(vector_id))

    @app.get("/controls")
    def get_controls() -> dict:
        return list_controls()

    @app.post("/controls")
    async def post_controls(file: UploadFile = File(...)) -> JSONResponse:
        content = await file.read()
        return _json(*upload_controls(file.filename or "", content))

    @app.post("/controls/entry")
    def post_control_entry(body: EntryBody) -> JSONResponse:
        return _json(*add_control(body.model_dump()))

    @app.put("/controls/entry")
    def put_control_entry(body: EntryBody) -> JSONResponse:
        payload = body.model_dump()
        return _json(*update_control(str(payload.get("previous_control_id") or ""), payload))

    @app.delete("/controls/entry")
    def delete_control_entry(control_id: str = Query(...)) -> JSONResponse:
        return _json(*delete_control(control_id))

    @app.get("/scenario-controls")
    def get_scenario_controls() -> dict:
        return list_scenario_controls()

    @app.post("/scenario-controls")
    async def post_scenario_controls(file: UploadFile = File(...)) -> JSONResponse:
        content = await file.read()
        return _json(*upload_scenario_controls(file.filename or "", content))

    @app.post("/scenario-controls/entry")
    def post_scenario_control_entry(body: EntryBody) -> JSONResponse:
        return _json(*add_scenario_control(body.model_dump()))

    @app.delete("/scenario-controls/entry")
    def delete_scenario_control_entry(scenario_id: str = Query(...), control_id: str = Query(...)) -> JSONResponse:
        return _json(*delete_scenario_control(scenario_id, control_id))

    @app.put("/scenario-controls/entry")
    def put_scenario_control_entry(body: EntryBody) -> JSONResponse:
        payload = body.model_dump()
        return _json(
            *update_scenario_control(
                str(payload.get("previous_scenario_id") or ""),
                str(payload.get("previous_control_id") or ""),
                payload,
            )
        )

    @app.get("/scenarios")
    def get_scenarios() -> dict:
        return list_scenarios()

    @app.post("/scenarios")
    async def post_scenarios(file: UploadFile = File(...)) -> JSONResponse:
        content = await file.read()
        return _json(*upload_scenarios(file.filename or "", content))

    @app.get("/scenarios/suggest")
    def get_suggestions(
        threat_actor_id: str = Query(...),
        attack_vector_id: str = Query(...),
        target_type: str = Query(...),
        target_id: str = Query(...),
    ) -> dict:
        context = build_target_context(threat_actor_id, attack_vector_id, target_type, target_id)
        if not context:
            raise HTTPException(status_code=404, detail="That actor, vector, or target was not found.")
        return {
            "benchmarks_version": benchmarks_version(),
            "exposure": exposure_summary(context),
            "suggestions": suggest_factors(context),
            "data_quality": data_quality(context),
        }

    @app.post("/scenarios/entry")
    def post_scenario_entry(body: EntryBody) -> JSONResponse:
        return _json(*add_scenario(body.model_dump()))

    @app.put("/scenarios/entry")
    def put_scenario_entry(body: EntryBody) -> JSONResponse:
        payload = body.model_dump()
        return _json(*update_scenario(str(payload.get("previous_scenario_id") or ""), payload))

    @app.delete("/scenarios/entry")
    def delete_scenario_entry(scenario_id: str = Query(...)) -> JSONResponse:
        return _json(*delete_scenario(scenario_id))

    @app.get("/scenarios/{scenario_id}/inputs")
    def get_scenario_inputs(
        scenario_id: str,
        control_set: str = Query("current"),
        control_ids: list[str] = Query(default=[]),
    ) -> dict:
        context = _context_or_404(scenario_id)
        try:
            return scenario_inputs(context, control_set, control_ids or None)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/scenarios/{scenario_id}/simulate", response_model=types["MCResponse"], response_model_exclude_none=True)
    def post_scenario_simulate(scenario_id: str, body: EntryBody):
        context = _context_or_404(scenario_id)
        payload = body.model_dump()
        control_set = str(payload.get("control_set") or "current")
        control_ids = payload.get("control_ids") or None
        iterations = int(payload.get("iterations") or 10_000)
        seed = payload.get("seed")
        try:
            applied = apply_controls(context, control_set, control_ids)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if applied["eliminated"]:
            names = ", ".join(applied["eliminated_by"])
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Scenario {scenario_id} is eliminated by {names} under the '{control_set}' "
                    "control set; nothing to simulate."
                ),
            )
        factors = effective_factors(context, applied)
        try:
            collapsed = collapse(factors)
            fair = run_fair_simulation(
                lef=collapsed["frequency"],
                frequency_lambda=collapsed["frequency_lambda"],
                primary=collapsed["primary"],
                secondary=collapsed["secondary"],
                secondary_probability=collapsed["slp"],
                magnitude_lambda=collapsed["magnitude_lambda"],
                iterations=iterations,
                seed=seed,
                magnitude_reference=collapsed["magnitude"],
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        request = types["MCRequest"](
            frequency=types["VariableInput"](
                minimum=collapsed["frequency"][0],
                mode=collapsed["frequency"][1],
                maximum=collapsed["frequency"][2],
                lambda_param=collapsed["frequency_lambda"],
            ),
            magnitude=types["VariableInput"](
                minimum=collapsed["magnitude"][0],
                mode=collapsed["magnitude"][1],
                maximum=collapsed["magnitude"][2],
                lambda_param=collapsed["magnitude_lambda"],
            ),
            iterations=iterations,
            seed=seed,
        )
        scenario = context["scenario"]
        return _fair_response(
            types,
            fair,
            request,
            {
                "scenario_id": scenario_id,
                "scenario": scenario.get("scenario"),
                "control_set": control_set,
                "applied_control_ids": [control["control_id"] for control in applied["applied_controls"]],
                "analytic_ale": collapsed["analytic_ale"],
            },
        )

    @app.get("/scenarios/{scenario_id}/compare")
    def get_scenario_compare(scenario_id: str, iterations: int = Query(10_000), seed: int = Query(1)) -> dict:
        context = _context_or_404(scenario_id)
        sets = {}
        for name in ("inherent", "current", "target"):
            run = run_control_set(context, name, iterations, seed)
            sets[name] = {**run["summary"], "analytic_ale": run["collapsed"]["analytic_ale"]}
        inherent_mean = sets["inherent"]["mean"]
        for name in ("current", "target"):
            mean = sets[name]["mean"]
            sets[name]["reduction_vs_inherent_pct"] = None if inherent_mean == 0 else 100 * (1 - mean / inherent_mean)
        sets["inherent"]["reduction_vs_inherent_pct"] = None
        return {"scenario_id": scenario_id, "iterations": iterations, "seed": seed, "sets": sets}

    @app.get("/benchmarks")
    def read_benchmarks() -> dict:
        return get_benchmarks()

    @app.put("/benchmarks")
    def put_benchmarks(body: EntryBody) -> JSONResponse:
        return _json(*save_benchmarks(body.model_dump()))

    @app.get("/appetite")
    def read_appetite() -> dict:
        return get_appetite()

    @app.put("/appetite")
    def put_appetite(body: EntryBody) -> JSONResponse:
        return _json(*save_appetite(body.model_dump()))

    @app.get("/register")
    def get_register(iterations: int = Query(10_000), seed: int = Query(1)) -> dict:
        return public_register(build_register(iterations, seed))

    @app.get("/treatments")
    def get_treatments(iterations: int = Query(10_000), seed: int = Query(1)) -> dict:
        return public_treatments(build_treatments(iterations, seed))

    @app.get("/report")
    def get_report(iterations: int = Query(10_000), seed: int = Query(1)) -> dict:
        return build_report(iterations, seed)

    @app.get("/decisions")
    def get_decisions() -> dict:
        return list_decisions()

    @app.post("/decisions")
    def post_decision(body: EntryBody) -> dict:
        payload = body.model_dump()
        title = str(payload.get("title") or "").strip()
        prepared_by = str(payload.get("prepared_by") or "").strip()
        if not title or not prepared_by:
            raise HTTPException(status_code=422, detail="title and prepared_by must not be empty")
        iterations = int(payload.get("iterations") or 10_000)
        seed = int(payload.get("seed") or 1)
        treatments = build_treatments(iterations, seed)
        report = build_report(iterations, seed, treatments)
        inputs, _digest, _kev = snapshot_inputs()
        return insert_record(
            {
                "title": title,
                "prepared_by": prepared_by,
                "model_version": MODEL_VERSION,
                "benchmarks_version": benchmarks_version(),
                "seed": seed,
                "iterations": iterations,
                "report": report,
                "inputs": inputs,
                "assumptions": assumptions_for(benchmarks_version()),
            }
        )

    @app.get("/decisions/{record_id}")
    def read_decision(record_id: str) -> dict:
        record = get_decision(record_id)
        if not record:
            raise HTTPException(status_code=404, detail="That decision record was not found.")
        return record

    @app.get("/decisions/{record_id}/verify")
    def read_decision_verify(record_id: str) -> dict:
        result = verify_decision(record_id)
        if not result:
            raise HTTPException(status_code=404, detail="That decision record was not found.")
        return result

    @app.post("/decisions/{record_id}/approval")
    def post_decision_approval(record_id: str, body: EntryBody) -> JSONResponse:
        payload = body.model_dump()
        return _json(
            *approve_decision(
                record_id,
                str(payload.get("status") or ""),
                str(payload.get("approved_by") or ""),
                str(payload.get("note") or ""),
            )
        )
