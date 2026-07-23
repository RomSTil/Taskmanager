from abc import ABC
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, TypeVar

from fastapi import APIRouter, FastAPI

from ..config import Settings


ServiceT = TypeVar("ServiceT")


class ServiceContainer:
    """Small typed container for application-scoped services."""

    def __init__(self) -> None:
        self._services: dict[type[Any], Any] = {}

    def add(self, service_type: type[ServiceT], service: ServiceT) -> None:
        if service_type in self._services:
            raise ValueError(f"Service is already registered: {service_type.__name__}")
        self._services[service_type] = service

    def get(self, service_type: type[ServiceT]) -> ServiceT:
        try:
            return self._services[service_type]
        except KeyError as exc:
            raise RuntimeError(f"Service is not registered: {service_type.__name__}") from exc


@dataclass(slots=True)
class ModuleContext:
    settings: Settings
    services: ServiceContainer = field(default_factory=ServiceContainer)


class ApplicationModule(ABC):
    """Extension point for a cohesive backend feature."""

    name: str
    dependencies: tuple[str, ...] = ()
    routers: Sequence[APIRouter] = ()

    def configure(self, _: ModuleContext) -> None:
        """Register module services before its routes become available."""

    async def startup(self, _: ModuleContext) -> None:
        """Allocate module resources."""

    async def shutdown(self, _: ModuleContext) -> None:
        """Release module resources."""


class RouterModule(ApplicationModule):
    def __init__(
        self,
        name: str,
        *routers: APIRouter,
        dependencies: tuple[str, ...] = (),
    ) -> None:
        self.name = name
        self.routers = routers
        self.dependencies = dependencies


class ModuleRegistry:
    """Validates, orders and installs independent Taskman modules."""

    def __init__(self, modules: Iterable[ApplicationModule]) -> None:
        self._modules: dict[str, ApplicationModule] = {}
        for module in modules:
            if not module.name or module.name in self._modules:
                raise ValueError(f"Duplicate or empty module name: {module.name!r}")
            self._modules[module.name] = module
        self._ordered = self._resolve_dependencies()

    @property
    def modules(self) -> tuple[ApplicationModule, ...]:
        return tuple(self._ordered)

    def _resolve_dependencies(self) -> list[ApplicationModule]:
        ordered: list[ApplicationModule] = []
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(name: str) -> None:
            if name in visited:
                return
            if name in visiting:
                raise ValueError(f"Cyclic module dependency detected at {name!r}")
            try:
                module = self._modules[name]
            except KeyError as exc:
                raise ValueError(f"Unknown module dependency: {name!r}") from exc
            visiting.add(name)
            for dependency in module.dependencies:
                visit(dependency)
            visiting.remove(name)
            visited.add(name)
            ordered.append(module)

        for module_name in self._modules:
            visit(module_name)
        return ordered

    def configure(self, context: ModuleContext) -> None:
        for module in self._ordered:
            module.configure(context)

    def install_routes(self, application: FastAPI, *, prefix: str) -> None:
        for module in self._ordered:
            for router in module.routers:
                application.include_router(router, prefix=prefix)

    async def startup(self, context: ModuleContext) -> None:
        for module in self._ordered:
            await module.startup(context)

    async def shutdown(self, context: ModuleContext) -> None:
        for module in reversed(self._ordered):
            await module.shutdown(context)
