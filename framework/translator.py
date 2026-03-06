from __future__ import annotations

import re
from pathlib import Path

from .intent_parser import parse_intent_file
from .models import Fault, IntentScenario, Scope, Threshold, Traffic


def _slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")
    return text or "scenario"


def _parse_bool_token(source: str, key: str, default: bool = False) -> bool:
    m = re.search(rf"{re.escape(key)}\s*=\s*(true|false)", source, re.IGNORECASE)
    if not m:
        return default
    return m.group(1).lower() == "true"


def _parse_duration_to_seconds(text: str) -> int:
    text = text.strip().lower()
    m = re.match(r"^(\d+)\s*([smhd])$", text)
    if m:
        num = int(m.group(1))
        unit = m.group(2)
        if unit == "s":
            return num
        if unit == "m":
            return num * 60
        if unit == "h":
            return num * 3600
        return num * 86400
    m = re.search(r"(\d+)\s*秒", text)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d+)\s*分钟", text)
    if m:
        return int(m.group(1)) * 60
    return 600


def _parse_scope(scope_text: str) -> Scope:
    nodes = 4
    m = re.search(r"(\d+)\s*节点", scope_text)
    if m:
        nodes = int(m.group(1))

    network = "dev"
    m = re.search(r"network\s*=\s*([a-zA-Z0-9:_-]+)", scope_text)
    if m:
        network = m.group(1)

    ws_enabled = _parse_bool_token(scope_text, "ws", default=True)
    tls_enabled = _parse_bool_token(scope_text, "tls", default=False)

    if "启用TLS" in scope_text or "tls=true" in scope_text.lower():
        tls_enabled = True

    return Scope(nodes=nodes, network=network, tls_http=tls_enabled, tls_ws=tls_enabled and ws_enabled)


def _parse_fault(fault_text: str, params_text: str) -> Fault:
    ft = fault_text.strip()
    params = params_text.strip()

    if ft in {"无", "none", "无扰动"}:
        return Fault(type="none", selector="none", params={})

    selector = "random" if "随机" in params else "node-1"
    data: dict[str, object] = {}

    if "持续" in params:
        data["duration_seconds"] = _parse_duration_to_seconds(params)

    delay_match = re.search(r"(\d+)\s*ms", params, re.IGNORECASE)
    if delay_match:
        data["delay_ms"] = int(delay_match.group(1))

    loss_match = re.search(r"(\d+(?:\.\d+)?)\s*%", params)
    if loss_match:
        data["loss_percent"] = float(loss_match.group(1))

    count_match = re.search(r"(\d+)\s*节点", params)
    if count_match:
        data["count"] = int(count_match.group(1))
    elif "一个节点" in ft or "停1" in params or "重启1" in params:
        data["count"] = 1

    mapping = {
        "停一个节点": "node_down",
        "重启一个节点": "node_restart",
        "网络分区": "network_partition",
        "高延迟": "net_delay",
        "丢包": "net_loss",
        "限流": "rpc_rate_limit",
    }

    for k, v in mapping.items():
        if k in ft:
            return Fault(type=v, selector=selector, params=data)

    return Fault(type="custom", selector=selector, params={"raw": ft, **data})


def _parse_traffic(traffic_text: str) -> Traffic:
    transports: list[str] = []
    http_qps = 0
    ws_subscriptions = 0

    m = re.search(r"https?\s*(\d+)\s*qps", traffic_text, re.IGNORECASE)
    if m:
        http_qps = int(m.group(1))
        transports.append("http")

    m = re.search(r"wss?\s*(\d+)\s*订阅", traffic_text, re.IGNORECASE)
    if m:
        ws_subscriptions = int(m.group(1))
        transports.append("ws")

    if "https" in traffic_text.lower() and "http" not in transports:
        transports.append("http")
    if "wss" in traffic_text.lower() and "ws" not in transports:
        transports.append("ws")

    if not transports:
        transports.append("http")
        http_qps = 50

    return Traffic(transports=transports, http_qps=http_qps, ws_subscriptions=ws_subscriptions)


def _parse_thresholds(items: list[str]) -> list[Threshold]:
    out: list[Threshold] = []
    for item in items:
        s = item.strip()
        if not s:
            continue
        if "链高度持续增长" in s:
            out.append(Threshold(metric="chain_progress", op="==", value=True))
            continue
        m = re.search(r"rpc成功率\s*>=\s*([\d.]+)%", s, re.IGNORECASE)
        if m:
            out.append(Threshold(metric="rpc_success_rate", op=">=", value=float(m.group(1))))
            continue
        m = re.search(r"peer数在\s*(\d+)\s*秒内恢复到\s*>=\s*(\d+)", s)
        if m:
            out.append(Threshold(metric="peer_recovery_seconds", op="<=", value=int(m.group(1))))
            out.append(Threshold(metric="peer_count_after_recovery", op=">=", value=int(m.group(2))))
            continue
        m = re.search(r"订阅丢失率\s*<=\s*([\d.]+)%", s)
        if m:
            out.append(Threshold(metric="pubsub_drop_rate", op="<=", value=float(m.group(1))))
            continue
        m = re.search(r"([a-zA-Z0-9_]+)\s*(<=|>=|==|<|>)\s*([\d.]+)", s)
        if m:
            value: float | int = float(m.group(3))
            if value.is_integer():
                value = int(value)
            out.append(Threshold(metric=m.group(1), op=m.group(2), value=value))
    return out


def _parse_observe(text: str) -> list[str]:
    values = re.split(r"[,，\s]+", text)
    return [v for v in values if v]


def load_intent(path: str | Path) -> IntentScenario:
    source = Path(path)
    raw = parse_intent_file(source)
    title = str(raw["title"])  # type: ignore[index]
    scenario_id = _slugify(source.stem)

    return IntentScenario(
        id=scenario_id,
        title=title,
        objective=str(raw["objective"]),
        scope=_parse_scope(str(raw["scope"])),
        fault=_parse_fault(str(raw["fault"]), str(raw["fault_params"])),
        traffic=_parse_traffic(str(raw["traffic"])),
        duration=str(raw["duration"]),
        thresholds=_parse_thresholds(list(raw["thresholds"])),
        observe=_parse_observe(str(raw["observe"])),
    )
