from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Scope:
    nodes: int = 4
    network: str = "dev"
    tls_http: bool = False
    tls_ws: bool = False


@dataclass
class Fault:
    type: str = "none"
    selector: str = "none"
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class Traffic:
    transports: list[str] = field(default_factory=list)
    http_qps: int = 0
    ws_subscriptions: int = 0


@dataclass
class Threshold:
    metric: str
    op: str
    value: Any


@dataclass
class IntentScenario:
    id: str
    title: str
    objective: str
    scope: Scope
    fault: Fault
    traffic: Traffic
    duration: str
    thresholds: list[Threshold] = field(default_factory=list)
    observe: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["thresholds"] = [asdict(t) for t in self.thresholds]
        return data
