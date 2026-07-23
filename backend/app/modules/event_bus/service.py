import hashlib
import json

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .events import ApplicationEvent
from .models import DomainEvent


class EventBusService:
    """Transactional event publisher backed by the database outbox."""

    def publish(
        self,
        session: Session,
        event: ApplicationEvent,
        *,
        deduplication_key: str | None = None,
    ) -> DomainEvent:
        payload = event.payload()
        if deduplication_key is None:
            digest = hashlib.sha256(
                json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
            ).hexdigest()[:24]
            deduplication_key = (
                f"{event.event_type}:{event.aggregate_type}:{event.aggregate_id}:{digest}"
            )
        existing = session.scalar(
            select(DomainEvent).where(
                DomainEvent.deduplication_key == deduplication_key
            )
        )
        if existing:
            return existing
        stored = DomainEvent(
            event_type=event.event_type,
            aggregate_type=event.aggregate_type,
            aggregate_id=event.aggregate_id,
            payload=payload,
            deduplication_key=deduplication_key,
        )
        try:
            with session.begin_nested():
                session.add(stored)
                session.flush()
        except IntegrityError:
            existing = session.scalar(
                select(DomainEvent).where(
                    DomainEvent.deduplication_key == deduplication_key
                )
            )
            if existing is None:
                raise
            return existing
        return stored
