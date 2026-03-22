from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from libs.adapters.llm.gateway import ModelGateway
from libs.core.config import get_config
from libs.core.logging import configure_logging
from libs.core.policy import Actor, TokenScope
from libs.orchestration.job_queue import enqueue_job
from libs.orchestration.worker import run_worker_once
from libs.schemas.api import (
    CreateCycleRequest,
    CycleCommandRequest,
    CycleDetailResponse,
    CycleListResponse,
    EvidenceCardDetail,
    EvidenceListResponse,
    EvidenceSummaryResponse,
    ExperimentSpecDetail,
    ExperimentSpecListResponse,
    HealthResponse,
    HypothesisCardDetail,
    HypothesisListResponse,
    JobDetailResponse,
    JobListResponse,
    LiteratureTriageResponse,
    PaperCardDetail,
    PaperListResponse,
    PortfolioRankingResponse,
    ReportDetailResponse,
    ReportListResponse,
    RetrievalSessionListResponse,
    SkillDetailResponse,
    SkillListResponse,
)
from libs.storage import services
from libs.storage.session import get_session_factory, initialize_database


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = get_config()
    configure_logging(config.env)
    if config.auto_init_db:
        initialize_database(config)
    with get_session_factory(config)() as session:
        services.seed_dev_client_and_token(session, config)
        services.sync_skill_catalog(session, config)
    yield


app = FastAPI(title="Synthetos Phase 0 API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_db() -> Session:
    session = get_session_factory(get_config())()
    try:
        yield session
    finally:
        session.close()


def authenticate(
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    token: str | None = Query(default=None),
    session: Session = Depends(get_db),
) -> Actor:
    raw_token: str | None = None
    if authorization and authorization.startswith("Bearer "):
        raw_token = authorization.removeprefix("Bearer ").strip()
    elif token:
        raw_token = token
    if raw_token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    actor = services.authenticate_token(session, raw_token)
    if actor is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return actor


def require_scopes(*required: TokenScope):
    def dependency(actor: Actor = Depends(authenticate)) -> Actor:
        missing = [scope for scope in required if scope not in actor.scopes]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing scopes: {', '.join(scope.value for scope in missing)}",
            )
        return actor

    return dependency


@app.get("/api/v1/healthz", response_model=HealthResponse)
def healthz() -> HealthResponse:
    return HealthResponse(status="ok", timestamp=datetime.now(UTC))


@app.post("/api/v1/cycles", response_model=CycleDetailResponse)
def create_cycle(
    payload: CreateCycleRequest,
    actor: Actor = Depends(require_scopes(TokenScope.CYCLES_WRITE)),
    session: Session = Depends(get_db),
) -> CycleDetailResponse:
    cycle = services.create_cycle(session, actor, payload)
    services.record_command(
        session,
        actor=actor,
        command_name="create_cycle",
        target_resource=cycle.public_id,
        payload=payload.model_dump(mode="json"),
        result={"cycle_id": cycle.public_id},
        cycle_id=cycle.id,
    )
    enqueue_job(session, actor, cycle.id, "initialize_cycle", {"cycle_public_id": cycle.public_id})
    session.commit()
    return services.build_cycle_detail(session, cycle.public_id)


@app.get("/api/v1/cycles", response_model=CycleListResponse)
def list_cycles(
    actor: Actor = Depends(require_scopes(TokenScope.CYCLES_READ)),
    session: Session = Depends(get_db),
) -> CycleListResponse:
    return CycleListResponse(items=services.list_cycles(session))


@app.get("/api/v1/cycles/{cycle_id}", response_model=CycleDetailResponse)
def get_cycle(
    cycle_id: str,
    actor: Actor = Depends(require_scopes(TokenScope.CYCLES_READ)),
    session: Session = Depends(get_db),
) -> CycleDetailResponse:
    return services.build_cycle_detail(session, cycle_id)


@app.post("/api/v1/cycles/{cycle_id}/commands", response_model=CycleDetailResponse)
def cycle_command(
    cycle_id: str,
    payload: CycleCommandRequest,
    actor: Actor = Depends(require_scopes(TokenScope.RUNS_CONTROL)),
    session: Session = Depends(get_db),
) -> CycleDetailResponse:
    services.apply_cycle_command(session, actor, cycle_id, payload.command, payload.payload)
    services.record_command(
        session,
        actor=actor,
        command_name=f"{payload.command}_cycle",
        target_resource=cycle_id,
        payload=payload.model_dump(mode="json"),
        result={"status": "accepted"},
        cycle_public_id=cycle_id,
    )
    session.commit()
    return services.build_cycle_detail(session, cycle_id)


@app.get("/api/v1/jobs", response_model=JobListResponse)
def list_jobs(
    actor: Actor = Depends(require_scopes(TokenScope.CYCLES_READ)),
    session: Session = Depends(get_db),
) -> JobListResponse:
    return JobListResponse(items=services.list_jobs(session))


@app.get("/api/v1/jobs/{job_id}", response_model=JobDetailResponse)
def get_job(
    job_id: str,
    actor: Actor = Depends(require_scopes(TokenScope.CYCLES_READ)),
    session: Session = Depends(get_db),
) -> JobDetailResponse:
    return services.get_job_detail(session, job_id)


@app.get("/api/v1/skills", response_model=SkillListResponse)
def list_skills(
    actor: Actor = Depends(require_scopes(TokenScope.SKILLS_READ)),
    session: Session = Depends(get_db),
) -> SkillListResponse:
    return SkillListResponse(items=services.list_skills(session))


@app.get("/api/v1/skills/{skill_id}", response_model=SkillDetailResponse)
def get_skill(
    skill_id: str,
    actor: Actor = Depends(require_scopes(TokenScope.SKILLS_READ)),
    session: Session = Depends(get_db),
) -> SkillDetailResponse:
    return services.get_skill_detail(session, skill_id)


@app.get("/api/v1/reports", response_model=ReportListResponse)
def list_reports(
    actor: Actor = Depends(require_scopes(TokenScope.REPORTS_READ)),
    session: Session = Depends(get_db),
) -> ReportListResponse:
    return ReportListResponse(items=services.list_reports(session))


@app.get("/api/v1/reports/{report_id}", response_model=ReportDetailResponse)
def get_report(
    report_id: str,
    actor: Actor = Depends(require_scopes(TokenScope.REPORTS_READ)),
    session: Session = Depends(get_db),
) -> ReportDetailResponse:
    return services.get_report_detail(session, report_id)


@app.get("/api/v1/cycles/{cycle_id}/papers", response_model=PaperListResponse)
def list_papers(
    cycle_id: str,
    status: str | None = Query(default=None),
    actor: Actor = Depends(require_scopes(TokenScope.CYCLES_READ)),
    session: Session = Depends(get_db),
) -> PaperListResponse:
    items = services.list_papers_for_cycle(session, cycle_id, status_filter=status)
    return PaperListResponse(items=items, total=len(items))


@app.get("/api/v1/cycles/{cycle_id}/papers/{paper_id}", response_model=PaperCardDetail)
def get_paper(
    cycle_id: str,
    paper_id: str,
    actor: Actor = Depends(require_scopes(TokenScope.CYCLES_READ)),
    session: Session = Depends(get_db),
) -> PaperCardDetail:
    return services.get_paper_detail(session, cycle_id, paper_id)


@app.get("/api/v1/cycles/{cycle_id}/literature", response_model=LiteratureTriageResponse)
def get_literature_triage(
    cycle_id: str,
    actor: Actor = Depends(require_scopes(TokenScope.CYCLES_READ)),
    session: Session = Depends(get_db),
) -> LiteratureTriageResponse:
    return services.get_literature_summary(session, cycle_id)


@app.get(
    "/api/v1/cycles/{cycle_id}/retrieval-sessions",
    response_model=RetrievalSessionListResponse,
)
def list_retrieval_sessions(
    cycle_id: str,
    actor: Actor = Depends(require_scopes(TokenScope.CYCLES_READ)),
    session: Session = Depends(get_db),
) -> RetrievalSessionListResponse:
    items = services.list_retrieval_sessions_for_cycle(session, cycle_id)
    return RetrievalSessionListResponse(items=items)


# ---------------------------------------------------------------------------
# Phase 2 — Evidence, Hypotheses, Experiment Specs
# ---------------------------------------------------------------------------


@app.get("/api/v1/cycles/{cycle_id}/evidence", response_model=EvidenceListResponse)
def list_evidence(
    cycle_id: str,
    type: str | None = Query(default=None),
    actor: Actor = Depends(require_scopes(TokenScope.CYCLES_READ)),
    session: Session = Depends(get_db),
) -> EvidenceListResponse:
    return services.list_evidence_for_cycle_api(session, cycle_id, type_filter=type)


@app.get(
    "/api/v1/cycles/{cycle_id}/evidence/summary",
    response_model=EvidenceSummaryResponse,
)
def get_evidence_summary(
    cycle_id: str,
    actor: Actor = Depends(require_scopes(TokenScope.CYCLES_READ)),
    session: Session = Depends(get_db),
) -> EvidenceSummaryResponse:
    return services.get_evidence_summary_api(session, cycle_id)


@app.get(
    "/api/v1/cycles/{cycle_id}/evidence/{evidence_id}",
    response_model=EvidenceCardDetail,
)
def get_evidence(
    cycle_id: str,
    evidence_id: str,
    actor: Actor = Depends(require_scopes(TokenScope.CYCLES_READ)),
    session: Session = Depends(get_db),
) -> EvidenceCardDetail:
    return services.get_evidence_detail_api(session, cycle_id, evidence_id)


@app.get(
    "/api/v1/cycles/{cycle_id}/hypotheses",
    response_model=HypothesisListResponse,
)
def list_hypotheses(
    cycle_id: str,
    actor: Actor = Depends(require_scopes(TokenScope.CYCLES_READ)),
    session: Session = Depends(get_db),
) -> HypothesisListResponse:
    return services.list_hypotheses_for_cycle_api(session, cycle_id)


@app.get(
    "/api/v1/cycles/{cycle_id}/hypotheses/portfolio",
    response_model=PortfolioRankingResponse,
)
def get_portfolio(
    cycle_id: str,
    actor: Actor = Depends(require_scopes(TokenScope.CYCLES_READ)),
    session: Session = Depends(get_db),
) -> PortfolioRankingResponse:
    return services.get_portfolio_ranking_api(session, cycle_id)


@app.get(
    "/api/v1/cycles/{cycle_id}/hypotheses/{hypothesis_id}",
    response_model=HypothesisCardDetail,
)
def get_hypothesis(
    cycle_id: str,
    hypothesis_id: str,
    actor: Actor = Depends(require_scopes(TokenScope.CYCLES_READ)),
    session: Session = Depends(get_db),
) -> HypothesisCardDetail:
    return services.get_hypothesis_detail_api(session, cycle_id, hypothesis_id)


@app.get(
    "/api/v1/cycles/{cycle_id}/experiment-specs",
    response_model=ExperimentSpecListResponse,
)
def list_experiment_specs(
    cycle_id: str,
    actor: Actor = Depends(require_scopes(TokenScope.CYCLES_READ)),
    session: Session = Depends(get_db),
) -> ExperimentSpecListResponse:
    return services.list_experiment_specs_for_cycle_api(session, cycle_id)


@app.get(
    "/api/v1/cycles/{cycle_id}/experiment-specs/{spec_id}",
    response_model=ExperimentSpecDetail,
)
def get_experiment_spec(
    cycle_id: str,
    spec_id: str,
    actor: Actor = Depends(require_scopes(TokenScope.CYCLES_READ)),
    session: Session = Depends(get_db),
) -> ExperimentSpecDetail:
    return services.get_experiment_spec_detail_api(session, cycle_id, spec_id)


@app.get("/api/v1/events/stream")
async def stream_events(
    actor: Actor = Depends(require_scopes(TokenScope.EVENTS_READ)),
    cycle_id: str | None = Query(default=None),
    last_event_id: int | None = Query(default=None),
    header_last_event_id: Annotated[
        str | None, Header(alias="Last-Event-ID")
    ] = None,
):
    del actor
    checkpoint = last_event_id
    if checkpoint is None and header_last_event_id:
        try:
            checkpoint = int(header_last_event_id)
        except ValueError:
            checkpoint = None

    config = get_config()
    factory = get_session_factory(config)

    async def event_iterator():
        current = checkpoint or 0
        while True:
            with factory() as session:
                fresh = services.list_events_after(
                    session, current, cycle_id=cycle_id,
                )
            if fresh:
                for event in fresh:
                    current = event.sequence_id
                    data = json.dumps(
                        event.model_dump(mode="json"),
                    )
                    yield f"id: {event.sequence_id}\ndata: {data}\n\n"
                continue
            yield ": heartbeat\n\n"
            await asyncio.sleep(15)

    return StreamingResponse(
        event_iterator(), media_type="text/event-stream",
    )


@app.post("/api/v1/admin/worker/run-once")
def admin_run_worker_once(
    actor: Actor = Depends(require_scopes(TokenScope.ADMIN_LOCAL)),
    session: Session = Depends(get_db),
) -> dict[str, str]:
    result = run_worker_once(session, get_config(), actor)
    session.commit()
    return {"result": result}


@app.get("/api/v1/admin/models/probe")
def admin_probe_models(
    actor: Actor = Depends(require_scopes(TokenScope.ADMIN_LOCAL)),
) -> dict[str, object]:
    gateway = ModelGateway.from_config(get_config())
    return {"routes": [route.model_dump(mode="json") for route in gateway.probe_all()]}
