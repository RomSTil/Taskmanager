import hashlib
import hmac
import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...config import Settings
from ...models import Task, new_id
from ..event_bus.models import DomainEvent
from ...security import hash_token
from .models import (
    AgentApproval,
    AgentEvent,
    AgentRole,
    AgentRun,
    AgentRunStatus,
    AgentRunStep,
    AgentRunner,
    ApprovalAction,
)
from .schemas import AgentRunCreate


LEASE_MINUTES = 2
ACTIVE_RUN_STATUSES = {
    AgentRunStatus.planning,
    AgentRunStatus.running,
    AgentRunStatus.internal_review,
    AgentRunStatus.revision,
}


class AgentOperationsService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def assignment_token(self, run: AgentRun, runner: AgentRunner) -> str:
        if run.lease_expires_at is None:
            raise ValueError("Run has no active lease")
        payload = {
            "run_id": run.id,
            "runner_id": runner.id,
            "role": run.role.value,
            "lease": int(run.lease_expires_at.timestamp()),
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        signature = hmac.new(
            self.settings.effective_jwt_secret.encode("utf-8"),
            encoded.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return f"{encoded}.{signature}"

    def verify_assignment(self, token: str, run: AgentRun, runner: AgentRunner) -> None:
        encoded, separator, signature = token.rpartition(".")
        if not separator:
            raise PermissionError("Malformed assignment token")
        expected = hmac.new(
            self.settings.effective_jwt_secret.encode("utf-8"),
            encoded.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise PermissionError("Invalid assignment signature")
        try:
            payload = json.loads(encoded)
        except json.JSONDecodeError as exc:
            raise PermissionError("Malformed assignment payload") from exc
        if (
            payload.get("run_id") != run.id
            or payload.get("runner_id") != runner.id
            or payload.get("role") != run.role.value
            or run.lease_expires_at is None
            or run.lease_expires_at < datetime.now(UTC)
        ):
            raise PermissionError("Expired or mismatched assignment")

    def create_run(self, session: Session, payload: AgentRunCreate, *, user_id: str | None) -> AgentRun:
        task = session.get(Task, payload.task_id)
        if not task or task.archived_at:
            raise LookupError("Task not found")
        if payload.parent_run_id and not session.get(AgentRun, payload.parent_run_id):
            raise LookupError("Parent agent run not found")
        run = AgentRun(
            task_id=payload.task_id,
            parent_run_id=payload.parent_run_id,
            goal=payload.goal,
            mode=payload.mode,
            allowed_actions=list(payload.allowed_actions),
            approval_policy_id=payload.approval_policy_id,
            created_by_user_id=user_id,
        )
        session.add(run)
        session.flush()
        session.add(
            AgentRunStep(
                run_id=run.id,
                role=AgentRole.coordinator,
                input_context={"task_id": task.id, "task_title": task.title, "goal": run.goal},
            )
        )
        self.event(
            session,
            run,
            "run_queued",
            "Поручение поставлено в очередь.",
            actor_type="owner",
            actor_id=user_id,
        )
        session.commit()
        return run

    def event(
        self,
        session: Session,
        run: AgentRun,
        event_type: str,
        summary: str,
        *,
        payload: dict[str, Any] | None = None,
        step_id: str | None = None,
        actor_type: str = "system",
        actor_id: str | None = None,
    ) -> AgentEvent:
        event_id = new_id()
        event = AgentEvent(
            id=event_id,
            run_id=run.id,
            step_id=step_id,
            event_type=event_type,
            summary=summary,
            payload=payload or {},
            actor_type=actor_type,
            actor_id=actor_id,
        )
        session.add(event)
        if event_type in {
            "run_queued",
            "approval_requested",
            "run_completed",
            "run_cancelled",
            "runner_lease_expired",
            "failed",
            "blocked",
        }:
            session.add(
                DomainEvent(
                    event_type="AgentRunChanged",
                    aggregate_type="agent_run",
                    aggregate_id=run.id,
                    payload={
                        "run_id": run.id,
                        "task_id": run.task_id,
                        "status": run.status.value,
                        "role": run.role.value,
                        "summary": summary[:1_000],
                    },
                    deduplication_key=f"agent-run:{event_id}",
                )
            )
        return event

    def runner_from_token(self, session: Session, raw_token: str) -> AgentRunner:
        runner = session.scalar(
            select(AgentRunner).where(AgentRunner.token_hash == hash_token(raw_token))
        )
        if not runner or not runner.enabled:
            raise PermissionError("Invalid runner token")
        return runner

    def register_runner(
        self,
        session: Session,
        *,
        name: str,
        public_key: str | None,
        version: str,
        capabilities: list[str],
        max_concurrency: int,
    ) -> tuple[AgentRunner, str]:
        if session.scalar(select(AgentRunner.id).where(AgentRunner.name == name)):
            raise ValueError("A runner with this name already exists")
        raw_token = "tmr_" + secrets.token_urlsafe(36)
        runner = AgentRunner(
            name=name,
            public_key=public_key,
            token_hash=hash_token(raw_token),
            version=version,
            capabilities=list(capabilities),
            max_concurrency=max_concurrency,
            last_heartbeat_at=datetime.now(UTC),
        )
        session.add(runner)
        session.commit()
        return runner, raw_token

    def claim(self, session: Session, runner: AgentRunner) -> AgentRun | None:
        now = datetime.now(UTC)
        active_count = session.scalar(
            select(func.count(AgentRun.id)).where(
                AgentRun.runner_id == runner.id,
                AgentRun.status.in_(ACTIVE_RUN_STATUSES),
                AgentRun.lease_expires_at.is_not(None),
                AgentRun.lease_expires_at > now,
            )
        ) or 0
        if active_count >= runner.max_concurrency:
            return None
        run = session.scalar(
            select(AgentRun)
            .where(AgentRun.status == AgentRunStatus.queued)
            .order_by(AgentRun.created_at)
            .with_for_update(skip_locked=True)
        )
        if run is None:
            return None
        step = session.scalar(
            select(AgentRunStep)
            .where(AgentRunStep.run_id == run.id, AgentRunStep.status == AgentRunStatus.queued)
            .order_by(AgentRunStep.created_at, AgentRunStep.id)
            .with_for_update()
        )
        if step is None:
            raise RuntimeError("Queued run has no queued step")
        lease = now + timedelta(minutes=LEASE_MINUTES)
        run.runner_id = runner.id
        run.status = AgentRunStatus.planning
        run.role = step.role
        run.started_at = run.started_at or now
        run.lease_expires_at = lease
        step.status = AgentRunStatus.planning
        step.executor = runner.name
        step.attempts += 1
        step.started_at = now
        self.event(
            session,
            run,
            "run_claimed",
            f"Runner {runner.name} начал работу.",
            step_id=step.id,
            actor_type="runner",
            actor_id=runner.id,
        )
        session.commit()
        return run

    def heartbeat(self, session: Session, runner: AgentRunner, **changes: Any) -> None:
        runner.last_heartbeat_at = datetime.now(UTC)
        for key, value in changes.items():
            if value is not None:
                setattr(runner, key, value)
        session.execute(
            select(AgentRun)
            .where(
                AgentRun.runner_id == runner.id,
                AgentRun.status.in_(ACTIVE_RUN_STATUSES),
            )
            .with_for_update()
        )
        for run in session.scalars(
            select(AgentRun).where(
                AgentRun.runner_id == runner.id,
                AgentRun.status.in_(ACTIVE_RUN_STATUSES),
            )
        ):
            run.lease_expires_at = datetime.now(UTC) + timedelta(minutes=LEASE_MINUTES)
        session.commit()

    def request_approval(
        self,
        session: Session,
        run: AgentRun,
        *,
        step_id: str | None,
        payload: dict[str, Any],
        runner_id: str,
    ) -> AgentApproval:
        try:
            action = ApprovalAction(str(payload["action"]))
            explanation = str(payload["explanation"]).strip()
            idempotency_key = str(payload["idempotency_key"]).strip()
        except (KeyError, ValueError) as exc:
            raise ValueError("Approval request needs action, explanation and idempotency_key") from exc
        if not explanation or not idempotency_key:
            raise ValueError("Approval request needs action, explanation and idempotency_key")
        approval = session.scalar(
            select(AgentApproval).where(AgentApproval.idempotency_key == idempotency_key)
        )
        if approval:
            if approval.run_id != run.id:
                raise ValueError("Approval idempotency key belongs to another run")
            return approval
        details = payload.get("details")
        if not isinstance(details, dict):
            raise ValueError("Approval details must be an object")
        approval = AgentApproval(
            run_id=run.id,
            action=action,
            explanation=explanation,
            details=details,
            idempotency_key=idempotency_key,
            requested_by_step_id=step_id,
        )
        run.status = AgentRunStatus.waiting_approval
        run.lease_expires_at = None
        session.add(approval)
        self.event(
            session,
            run,
            "approval_requested",
            explanation,
            payload={"approval_action": action.value, "approval_idempotency_key": idempotency_key},
            step_id=step_id,
            actor_type="runner",
            actor_id=runner_id,
        )
        return approval

    def return_for_feedback(
        self,
        session: Session,
        run: AgentRun,
        *,
        message: str,
        labels: list[str],
        actor_type: str,
        actor_id: str,
    ) -> None:
        if run.status not in {AgentRunStatus.waiting_owner_review, AgentRunStatus.accepted}:
            raise ValueError("Feedback is available after owner review")
        run.status = AgentRunStatus.queued
        run.role = AgentRole.coordinator
        run.runner_id = None
        run.lease_expires_at = None
        run.error_code = None
        run.error_message = None
        step = AgentRunStep(
            run_id=run.id,
            role=AgentRole.coordinator,
            input_context={"owner_feedback": message, "labels": labels},
        )
        session.add(step)
        session.flush()
        self.event(
            session,
            run,
            "owner_feedback",
            "Владелец вернул результат на доработку.",
            payload={"message": message, "labels": labels},
            step_id=step.id,
            actor_type=actor_type,
            actor_id=actor_id,
        )

    def accept(
        self,
        session: Session,
        run: AgentRun,
        *,
        actor_type: str,
        actor_id: str,
    ) -> None:
        if run.status != AgentRunStatus.waiting_owner_review:
            raise ValueError("Only a result awaiting owner review can be accepted")
        run.status = AgentRunStatus.accepted
        self.event(
            session,
            run,
            "owner_accepted",
            "Владелец принял результат.",
            actor_type=actor_type,
            actor_id=actor_id,
        )

    def expire_stale_leases(self, session: Session) -> int:
        now = datetime.now(UTC)
        runs = list(
            session.scalars(
                select(AgentRun).where(
                    AgentRun.status.in_(ACTIVE_RUN_STATUSES),
                    AgentRun.lease_expires_at.is_not(None),
                    AgentRun.lease_expires_at < now,
                )
            )
        )
        for run in runs:
            run.status = AgentRunStatus.blocked
            run.lease_expires_at = None
            run.error_code = "runner_lease_expired"
            run.error_message = "Локальный runner перестал отвечать; запуск можно повторить."
            self.event(session, run, "runner_lease_expired", run.error_message)
        if runs:
            session.commit()
        return len(runs)
