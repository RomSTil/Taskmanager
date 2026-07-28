from dataclasses import asdict, dataclass
from typing import Any, Protocol


class ApplicationEvent(Protocol):
    event_type: str
    aggregate_type: str
    aggregate_id: str

    def payload(self) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class BudgetRunningLow:
    account_id: str
    account_name: str
    balance: float
    currency: str
    days_left: float | None
    threshold: float
    event_type: str = "BudgetRunningLow"
    aggregate_type: str = "yandex_direct_account"

    @property
    def aggregate_id(self) -> str:
        return self.account_id

    def payload(self) -> dict[str, Any]:
        return {
            key: value
            for key, value in asdict(self).items()
            if key not in {"event_type", "aggregate_type"}
        }


@dataclass(frozen=True, slots=True)
class DirectAnomalyDetected:
    account_id: str
    account_name: str
    metric: str
    actual: float
    baseline: float
    ratio: float
    event_type: str = "DirectAnomalyDetected"
    aggregate_type: str = "yandex_direct_account"

    @property
    def aggregate_id(self) -> str:
        return self.account_id

    def payload(self) -> dict[str, Any]:
        return {
            key: value
            for key, value in asdict(self).items()
            if key not in {"event_type", "aggregate_type"}
        }


@dataclass(frozen=True, slots=True)
class ReportGenerated:
    account_id: str
    account_name: str
    date_from: str
    date_to: str
    rows: int
    impressions: int
    clicks: int
    cost: float
    conversions: float
    event_type: str = "ReportGenerated"
    aggregate_type: str = "yandex_direct_account"

    @property
    def aggregate_id(self) -> str:
        return self.account_id

    def payload(self) -> dict[str, Any]:
        return {
            key: value
            for key, value in asdict(self).items()
            if key not in {"event_type", "aggregate_type"}
        }


@dataclass(frozen=True, slots=True)
class DirectSyncFailed:
    account_id: str
    account_name: str
    error: str
    event_type: str = "DirectSyncFailed"
    aggregate_type: str = "yandex_direct_account"

    @property
    def aggregate_id(self) -> str:
        return self.account_id

    def payload(self) -> dict[str, Any]:
        return {
            key: value
            for key, value in asdict(self).items()
            if key not in {"event_type", "aggregate_type"}
        }
