from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Security, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...database import get_session
from ...dependencies import Principal, get_principal
from .models import (
    AgentApproval,
    AgentEvent,
    AgentRole,
    AgentRun,
    AgentRunStatus,
    AgentRunStep,
    AgentRunner,
    ApprovalStatus,
)
from .schemas import (
    AgentApprovalRead,
    AgentAssignment,
    AgentEventCreate,
    AgentEventRead,
    AgentRunComplete,
    AgentRunCreate,
    AgentRunFeedback,
    AgentRunRead,
    AgentRunStepRead,
    AgentRunnerHeartbeat,
    AgentRunnerControl,
    AgentRunnerRead,
    AgentRunnerRegister,
    AgentRunnerRegistered,
    ApprovalDecision,
)
from .service import ACTIVE_RUN_STATUSES, AgentOperationsService


router = APIRouter(tags=["agent operations"])


def get_agent_service(request: Request) -> AgentOperationsService:
    return request.app.state.module_context.services.get(AgentOperationsService)


def _run_or_404(session: Session, run_id: str, *, for_update: bool = False) -> AgentRun:
    query = select(AgentRun).where(AgentRun.id == run_id)
    if for_update:
        query = query.with_for_update()
    run = session.scalar(query)
    if not run:
        raise HTTPException(status_code=404, detail="Agent run not found")
    return run


def _read_run(session: Session, run: AgentRun) -> AgentRunRead:
    steps = list(
        session.scalars(
            select(AgentRunStep)
            .where(AgentRunStep.run_id == run.id)
            .order_by(AgentRunStep.created_at, AgentRunStep.id)
        )
    )
    events = list(
        session.scalars(
            select(AgentEvent)
            .where(AgentEvent.run_id == run.id)
            .order_by(AgentEvent.created_at, AgentEvent.id)
        )
    )
    approvals = list(
        session.scalars(
            select(AgentApproval)
            .where(AgentApproval.run_id == run.id)
            .order_by(AgentApproval.created_at, AgentApproval.id)
        )
    )
    return AgentRunRead(
        **{
            key: getattr(run, key)
            for key in AgentRunRead.model_fields
            if key not in {"steps", "events", "approvals"}
        },
        steps=[AgentRunStepRead.model_validate(step) for step in steps],
        events=[AgentEventRead.model_validate(event) for event in events],
        approvals=[AgentApprovalRead.model_validate(approval) for approval in approvals],
    )


def _read_runner(runner: AgentRunner) -> AgentRunnerRead:
    now = datetime.now(UTC)
    heartbeat = runner.last_heartbeat_at
    if heartbeat and heartbeat.tzinfo is None:
        heartbeat = heartbeat.replace(tzinfo=UTC)
    online = bool(
        runner.enabled
        and heartbeat
        and (now - heartbeat).total_seconds() <= 60
    )
    return AgentRunnerRead(
        id=runner.id,
        name=runner.name,
        version=runner.version,
        capabilities=runner.capabilities,
        max_concurrency=runner.max_concurrency,
        enabled=runner.enabled,
        online=online,
        last_heartbeat_at=runner.last_heartbeat_at,
        last_error=runner.last_error,
        created_at=runner.created_at,
        updated_at=runner.updated_at,
    )


def _runner(
    session: Session,
    service: AgentOperationsService,
    runner_id: str,
    raw_token: str | None,
) -> AgentRunner:
    if not raw_token:
        raise HTTPException(status_code=401, detail="Runner token is required")
    try:
        runner = service.runner_from_token(session, raw_token)
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail="Invalid runner token") from exc
    if runner.id != runner_id:
        raise HTTPException(status_code=403, detail="Runner token does not match path")
    return runner


def _runner_owns_active_run(
    run: AgentRun,
    runner: AgentRunner,
    service: AgentOperationsService,
    assignment_token: str | None,
) -> None:
    if run.runner_id != runner.id or run.status not in ACTIVE_RUN_STATUSES:
        raise HTTPException(status_code=409, detail="Runner does not own an active lease for this run")
    if not assignment_token:
        raise HTTPException(status_code=401, detail="Signed assignment token is required")
    try:
        service.verify_assignment(assignment_token, run, runner)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="Invalid or expired assignment token") from exc


@router.post("/agent-runs", response_model=AgentRunRead, status_code=status.HTTP_201_CREATED)
def create_run(
    payload: AgentRunCreate,
    principal: Annotated[Principal, Security(get_principal, scopes=["agent_operations:write"])],
    session: Annotated[Session, Depends(get_session)],
    service: Annotated[AgentOperationsService, Depends(get_agent_service)],
) -> AgentRunRead:
    try:
        run = service.create_run(session, payload, user_id=principal.user.id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _read_run(session, run)


@router.get("/agent-runs", response_model=list[AgentRunRead])
def list_runs(
    _: Annotated[Principal, Security(get_principal, scopes=["agent_operations:read"])],
    session: Annotated[Session, Depends(get_session)],
    task_id: str | None = None,
    run_status: AgentRunStatus | None = None,
    limit: int = 100,
) -> list[AgentRunRead]:
    query = select(AgentRun).order_by(AgentRun.created_at.desc()).limit(min(max(limit, 1), 250))
    if task_id:
        query = query.where(AgentRun.task_id == task_id)
    if run_status:
        query = query.where(AgentRun.status == run_status)
    return [_read_run(session, run) for run in session.scalars(query)]


@router.get("/agent-runs/{run_id}", response_model=AgentRunRead)
def get_run(
    run_id: str,
    _: Annotated[Principal, Security(get_principal, scopes=["agent_operations:read"])],
    session: Annotated[Session, Depends(get_session)],
) -> AgentRunRead:
    return _read_run(session, _run_or_404(session, run_id))


@router.post("/agent-runs/{run_id}/cancel", response_model=AgentRunRead)
def cancel_run(
    run_id: str,
    principal: Annotated[Principal, Security(get_principal, scopes=["agent_operations:write"])],
    session: Annotated[Session, Depends(get_session)],
    service: Annotated[AgentOperationsService, Depends(get_agent_service)],
) -> AgentRunRead:
    run = _run_or_404(session, run_id, for_update=True)
    if run.status in {AgentRunStatus.completed, AgentRunStatus.cancelled}:
        raise HTTPException(status_code=409, detail="This run cannot be cancelled")
    run.status = AgentRunStatus.cancelled
    run.lease_expires_at = None
    run.finished_at = datetime.now(UTC)
    service.event(
        session,
        run,
        "run_cancelled",
        "Владелец отменил запуск.",
        actor_type="owner",
        actor_id=principal.user.id,
    )
    session.commit()
    return _read_run(session, run)


@router.post("/agent-runs/{run_id}/feedback", response_model=AgentRunRead)
def feedback_run(
    run_id: str,
    payload: AgentRunFeedback,
    principal: Annotated[Principal, Security(get_principal, scopes=["agent_operations:write"])],
    session: Annotated[Session, Depends(get_session)],
    service: Annotated[AgentOperationsService, Depends(get_agent_service)],
) -> AgentRunRead:
    run = _run_or_404(session, run_id, for_update=True)
    try:
        service.return_for_feedback(
            session,
            run,
            message=payload.message,
            labels=payload.labels,
            actor_type="owner",
            actor_id=principal.user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    session.commit()
    return _read_run(session, run)


@router.post("/agent-runs/{run_id}/approvals/{approval_id}/decision", response_model=AgentRunRead)
def decide_approval(
    run_id: str,
    approval_id: str,
    payload: ApprovalDecision,
    principal: Annotated[Principal, Security(get_principal, scopes=["agent_operations:write"])],
    session: Annotated[Session, Depends(get_session)],
    service: Annotated[AgentOperationsService, Depends(get_agent_service)],
) -> AgentRunRead:
    run = _run_or_404(session, run_id, for_update=True)
    approval = session.get(AgentApproval, approval_id)
    if not approval or approval.run_id != run.id:
        raise HTTPException(status_code=404, detail="Approval not found")
    if approval.status != ApprovalStatus.pending:
        raise HTTPException(status_code=409, detail="Approval was already decided")
    approval.status = ApprovalStatus(payload.decision)
    approval.decided_by_user_id = principal.user.id
    approval.decided_at = datetime.now(UTC)
    step = session.get(AgentRunStep, approval.requested_by_step_id) if approval.requested_by_step_id else None
    if approval.status == ApprovalStatus.approved:
        run.status = AgentRunStatus.queued
        run.runner_id = None
        run.lease_expires_at = None
        if step:
            step.status = AgentRunStatus.queued
            step.executor = None
        summary = "Владелец разрешил действие; работа возвращена в очередь."
    else:
        run.status = AgentRunStatus.blocked
        run.lease_expires_at = None
        run.error_code = "approval_rejected"
        run.error_message = "Владелец отклонил действие, требующее согласования."
        if step:
            step.status = AgentRunStatus.blocked
            step.finished_at = datetime.now(UTC)
        summary = run.error_message
    service.event(
        session,
        run,
        f"approval_{payload.decision}",
        summary,
        payload={"approval_id": approval.id},
        actor_type="owner",
        actor_id=principal.user.id,
    )
    session.commit()
    return _read_run(session, run)


@router.post("/agent-runs/{run_id}/accept", response_model=AgentRunRead)
def accept_run(
    run_id: str,
    principal: Annotated[Principal, Security(get_principal, scopes=["agent_operations:write"])],
    session: Annotated[Session, Depends(get_session)],
    service: Annotated[AgentOperationsService, Depends(get_agent_service)],
) -> AgentRunRead:
    run = _run_or_404(session, run_id, for_update=True)
    try:
        service.accept(session, run, actor_type="owner", actor_id=principal.user.id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    session.commit()
    return _read_run(session, run)


@router.post("/agent-runners/register", response_model=AgentRunnerRegistered, status_code=201)
def register_runner(
    payload: AgentRunnerRegister,
    _: Annotated[Principal, Security(get_principal, scopes=["agent_operations:write"])],
    session: Annotated[Session, Depends(get_session)],
    service: Annotated[AgentOperationsService, Depends(get_agent_service)],
) -> AgentRunnerRegistered:
    try:
        runner, token = service.register_runner(session, **payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return AgentRunnerRegistered(**_read_runner(runner).model_dump(), runner_token=token)


@router.get("/agent-runners", response_model=list[AgentRunnerRead])
def list_runners(
    _: Annotated[Principal, Security(get_principal, scopes=["agent_operations:read"])],
    session: Annotated[Session, Depends(get_session)],
) -> list[AgentRunnerRead]:
    return [_read_runner(runner) for runner in session.scalars(select(AgentRunner).order_by(AgentRunner.name))]


@router.post("/agent-runners/{runner_id}/heartbeat", response_model=AgentRunnerRead)
def heartbeat_runner(
    runner_id: str,
    payload: AgentRunnerHeartbeat,
    session: Annotated[Session, Depends(get_session)],
    service: Annotated[AgentOperationsService, Depends(get_agent_service)],
    runner_token: Annotated[str | None, Header(alias="X-Taskman-Runner-Token")] = None,
) -> AgentRunnerRead:
    runner = _runner(session, service, runner_id, runner_token)
    service.heartbeat(session, runner, **payload.model_dump(exclude_unset=True))
    return _read_runner(runner)


@router.get("/agent-runners/{runner_id}/control", response_model=AgentRunnerControl)
def runner_control(
    runner_id: str,
    session: Annotated[Session, Depends(get_session)],
    service: Annotated[AgentOperationsService, Depends(get_agent_service)],
    runner_token: Annotated[str | None, Header(alias="X-Taskman-Runner-Token")] = None,
) -> AgentRunnerControl:
    runner = _runner(session, service, runner_id, runner_token)
    cancelled = list(
        session.scalars(
            select(AgentRun.id).where(
                AgentRun.runner_id == runner.id,
                AgentRun.status == AgentRunStatus.cancelled,
            )
        )
    )
    return AgentRunnerControl(cancelled_run_ids=cancelled)


@router.post("/agent-runners/{runner_id}/claim", response_model=AgentAssignment | None)
def claim_run(
    runner_id: str,
    session: Annotated[Session, Depends(get_session)],
    service: Annotated[AgentOperationsService, Depends(get_agent_service)],
    runner_token: Annotated[str | None, Header(alias="X-Taskman-Runner-Token")] = None,
) -> AgentAssignment | None:
    runner = _runner(session, service, runner_id, runner_token)
    service.expire_stale_leases(session)
    run = service.claim(session, runner)
    if run is None:
        return None
    return AgentAssignment(
        run=_read_run(session, run),
        assignment_token=service.assignment_token(run, runner),
        lease_expires_at=run.lease_expires_at,
    )


@router.post("/agent-runs/{run_id}/events", response_model=AgentEventRead, status_code=201)
def add_runner_event(
    run_id: str,
    payload: AgentEventCreate,
    session: Annotated[Session, Depends(get_session)],
    service: Annotated[AgentOperationsService, Depends(get_agent_service)],
    runner_token: Annotated[str | None, Header(alias="X-Taskman-Runner-Token")] = None,
    assignment_token: Annotated[str | None, Header(alias="X-Taskman-Assignment")] = None,
) -> AgentEventRead:
    run = _run_or_404(session, run_id, for_update=True)
    if not run.runner_id:
        raise HTTPException(status_code=409, detail="This run has no active runner")
    runner = _runner(session, service, run.runner_id, runner_token)
    _runner_owns_active_run(run, runner, service, assignment_token)
    step = session.get(AgentRunStep, payload.step_id) if payload.step_id else session.scalar(
        select(AgentRunStep)
        .where(AgentRunStep.run_id == run.id, AgentRunStep.status.in_([AgentRunStatus.planning, AgentRunStatus.running]))
        .order_by(AgentRunStep.created_at.desc())
    )
    if payload.step_id and (not step or step.run_id != run.id):
        raise HTTPException(status_code=422, detail="Step does not belong to this run")
    if payload.event_type == "progress" and run.status == AgentRunStatus.planning:
        run.status = AgentRunStatus.running
        if step:
            step.status = AgentRunStatus.running
    if payload.event_type == "progress":
        model = payload.payload.get("model")
        effort = payload.payload.get("effort")
        if isinstance(model, str) and model:
            run.selected_model = model[:120]
        if isinstance(effort, str) and effort:
            run.selected_effort = effort[:24]
        for field in ("input_tokens", "output_tokens", "reasoning_tokens"):
            value = payload.payload.get(field)
            if isinstance(value, int) and value >= 0:
                setattr(run, f"usage_{field}", max(getattr(run, f"usage_{field}"), value))
    elif payload.event_type == "role_started":
        run.status = AgentRunStatus.running
        if step:
            step.status = AgentRunStatus.running
    elif payload.event_type == "role_completed":
        if not step:
            raise HTTPException(status_code=422, detail="A role completion requires a run step")
        step.status = AgentRunStatus.completed
        step.finished_at = datetime.now(UTC)
        next_role = payload.payload.get("next_role")
        if next_role:
            try:
                role = AgentRole(str(next_role))
            except ValueError as exc:
                raise HTTPException(status_code=422, detail="Unknown next role") from exc
            next_context = payload.payload.get("next_context", {})
            if not isinstance(next_context, dict):
                raise HTTPException(status_code=422, detail="next_context must be an object")
            session.add(AgentRunStep(run_id=run.id, role=role, input_context=next_context))
            run.role = role
            run.status = AgentRunStatus.queued
            run.runner_id = None
            run.lease_expires_at = None
        else:
            run.status = AgentRunStatus.internal_review
    elif payload.event_type == "clarification_requested":
        run.status = AgentRunStatus.waiting_owner_review
        run.lease_expires_at = None
        if step:
            step.status = AgentRunStatus.waiting_owner_review
            step.finished_at = datetime.now(UTC)
    elif payload.event_type == "blocked":
        run.status = AgentRunStatus.blocked
        run.lease_expires_at = None
        run.error_code = str(payload.payload.get("error_code") or "runner_blocked")[:80]
        run.error_message = payload.summary or "Работа заблокирована."
        if step:
            step.status = AgentRunStatus.blocked
            step.finished_at = datetime.now(UTC)
    elif payload.event_type == "failed":
        run.status = AgentRunStatus.failed
        run.lease_expires_at = None
        run.finished_at = datetime.now(UTC)
        run.error_code = str(payload.payload.get("error_code") or "runner_failed")[:80]
        run.error_message = payload.summary or "Runner сообщил об ошибке."
        if step:
            step.status = AgentRunStatus.failed
            step.finished_at = datetime.now(UTC)
    if payload.event_type == "approval_requested":
        try:
            service.request_approval(
                session, run, step_id=step.id if step else None, payload=payload.payload, runner_id=runner.id
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    event = service.event(
        session,
        run,
        payload.event_type,
        payload.summary,
        payload=payload.payload,
        step_id=step.id if step else None,
        actor_type="runner",
        actor_id=runner.id,
    )
    session.commit()
    session.refresh(event)
    return AgentEventRead.model_validate(event)


@router.post("/agent-runs/{run_id}/complete", response_model=AgentRunRead)
def complete_run(
    run_id: str,
    payload: AgentRunComplete,
    session: Annotated[Session, Depends(get_session)],
    service: Annotated[AgentOperationsService, Depends(get_agent_service)],
    runner_token: Annotated[str | None, Header(alias="X-Taskman-Runner-Token")] = None,
    assignment_token: Annotated[str | None, Header(alias="X-Taskman-Assignment")] = None,
) -> AgentRunRead:
    run = _run_or_404(session, run_id, for_update=True)
    if not run.runner_id:
        raise HTTPException(status_code=409, detail="This run has no active runner")
    runner = _runner(session, service, run.runner_id, runner_token)
    _runner_owns_active_run(run, runner, service, assignment_token)
    outcome_status = {
        "owner_review": AgentRunStatus.waiting_owner_review,
        "internal_review": AgentRunStatus.internal_review,
        "completed": AgentRunStatus.completed,
        "blocked": AgentRunStatus.blocked,
        "failed": AgentRunStatus.failed,
    }[payload.outcome]
    run.status = outcome_status
    run.result_summary = payload.summary or run.result_summary
    run.result_note_id = payload.result_note_id or run.result_note_id
    run.preview_url = str(payload.preview_url) if payload.preview_url else run.preview_url
    run.error_code = payload.error_code
    run.error_message = payload.error_message
    run.lease_expires_at = None
    run.finished_at = datetime.now(UTC) if outcome_status in {AgentRunStatus.completed, AgentRunStatus.failed, AgentRunStatus.blocked} else None
    step = session.scalar(
        select(AgentRunStep)
        .where(AgentRunStep.run_id == run.id, AgentRunStep.status.in_([AgentRunStatus.planning, AgentRunStatus.running]))
        .order_by(AgentRunStep.created_at.desc())
    )
    if step:
        step.status = outcome_status
        step.finished_at = datetime.now(UTC)
    service.event(
        session,
        run,
        "run_completed",
        payload.summary or "Runner завершил этап работы.",
        payload={"outcome": payload.outcome},
        step_id=step.id if step else None,
        actor_type="runner",
        actor_id=runner.id,
    )
    session.commit()
    return _read_run(session, run)
