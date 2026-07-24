from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .client import DirectApiError, DirectReportPending
from .models import IntegrationJob, YandexDirectAccount
from .service import YandexDirectService


def schedule_due_checks(session: Session, service: YandexDirectService) -> int:
    now = datetime.now(UTC)
    scheduled = 0
    accounts = list(
        session.scalars(
            select(YandexDirectAccount).where(YandexDirectAccount.enabled.is_(True))
        )
    )
    for account in accounts:
        due_before = now - timedelta(minutes=account.monitor_interval_minutes)
        if account.last_checked_at is not None:
            last_checked = account.last_checked_at
            if last_checked.tzinfo is None:
                last_checked = last_checked.replace(tzinfo=UTC)
            if last_checked > due_before:
                continue
        bucket = int(now.timestamp()) // (account.monitor_interval_minutes * 60)
        job = service.queue_job(
            session,
            account,
            "balance_check",
            idempotency_key=f"direct:{account.id}:scheduled:{bucket}",
        )
        if job.status == "pending":
            scheduled += 1
    session.commit()
    return scheduled


def process_direct_jobs(
    session: Session,
    service: YandexDirectService,
    *,
    limit: int = 20,
) -> int:
    now = datetime.now(UTC)
    session.execute(
        update(IntegrationJob)
        .where(
            IntegrationJob.provider == "yandex_direct",
            IntegrationJob.status == "running",
            IntegrationJob.started_at < now - timedelta(minutes=15),
        )
        .values(
            status="pending",
            available_at=now,
            error="Recovered after an interrupted worker",
        )
    )
    session.commit()
    jobs = list(
        session.scalars(
            select(IntegrationJob)
            .where(
                IntegrationJob.provider == "yandex_direct",
                IntegrationJob.status == "pending",
                IntegrationJob.available_at <= now,
            )
            .order_by(IntegrationJob.created_at)
            .with_for_update(skip_locked=True)
            .limit(limit)
        )
    )
    completed = 0
    for job in jobs:
        job.status = "running"
        job.started_at = now
        session.commit()
        try:
            job.result = service.perform_job(session, job)
            job.status = "completed"
            job.executed_at = datetime.now(UTC)
            job.error = None
            completed += 1
        except DirectReportPending as exc:
            session.rollback()
            job = session.get(IntegrationJob, job.id)
            if job is None:
                continue
            job.status = "pending"
            job.attempts += 1
            job.available_at = datetime.now(UTC) + timedelta(seconds=exc.retry_after)
            job.error = "Yandex Direct report is pending"
        except DirectApiError as exc:
            session.rollback()
            job = session.get(IntegrationJob, job.id)
            if job is None:
                continue
            job.attempts += 1
            is_registration_error = str(exc.code) == "58"
            job.status = "failed" if is_registration_error or job.attempts >= 5 else "pending"
            job.available_at = datetime.now(UTC) + timedelta(
                seconds=min(3600, 2 ** min(job.attempts, 10))
            )
            job.error = f"Direct job failed: {exc}"
            if job.status == "failed":
                job.executed_at = datetime.now(UTC)
            if job.account_id:
                account = session.get(YandexDirectAccount, job.account_id)
                if account:
                    account.last_error = job.error
        except Exception as exc:
            session.rollback()
            job = session.get(IntegrationJob, job.id)
            if job is None:
                continue
            job.attempts += 1
            job.status = "failed" if job.attempts >= 5 else "pending"
            job.available_at = datetime.now(UTC) + timedelta(
                seconds=min(3600, 2 ** min(job.attempts, 10))
            )
            job.error = f"Direct job failed: {exc}"
            if job.account_id:
                account = session.get(YandexDirectAccount, job.account_id)
                if account:
                    account.last_error = job.error
        session.commit()
    return completed
