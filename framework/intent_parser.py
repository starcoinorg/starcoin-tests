from __future__ import annotations

import re
from pathlib import Path

FIELD_ALIASES = {
    "标题": "title",
    "目标": "objective",
    "范围": "scope",
    "扰动": "fault",
    "扰动参数": "fault_params",
    "流量": "traffic",
    "持续时间": "duration",
    "通过条件": "thresholds",
    "观测指标": "observe",
}


class IntentParseError(ValueError):
    pass


def _strip_prefix_title(line: str) -> str:
    line = line.strip()
    if line.startswith("#"):
        line = line.lstrip("#").strip()
    if line.startswith("标题"):
        parts = re.split(r"[:：]", line, maxsplit=1)
        if len(parts) == 2:
            return parts[1].strip()
    return line.strip()


def parse_intent_text(text: str) -> dict[str, object]:
    lines = [ln.rstrip() for ln in text.splitlines()]
    result: dict[str, object] = {}

    idx = 0
    while idx < len(lines):
        line = lines[idx].strip()
        if not line:
            idx += 1
            continue

        if line.startswith("#"):
            result.setdefault("title", _strip_prefix_title(line))
            idx += 1
            continue

        matched = False
        for cn, key in FIELD_ALIASES.items():
            if re.match(rf"^{re.escape(cn)}\s*[:：]", line):
                value = re.split(r"[:：]", line, maxsplit=1)[1].strip()
                if key == "thresholds":
                    thresholds: list[str] = []
                    idx += 1
                    while idx < len(lines):
                        next_line = lines[idx].strip()
                        if not next_line:
                            idx += 1
                            continue
                        if re.match(r"^[-*]\s+", next_line):
                            thresholds.append(re.sub(r"^[-*]\s+", "", next_line))
                            idx += 1
                            continue
                        if any(
                            re.match(rf"^{re.escape(label)}\s*[:：]", next_line)
                            for label in FIELD_ALIASES
                        ):
                            break
                        thresholds.append(next_line)
                        idx += 1
                    result[key] = thresholds
                    matched = True
                    break
                result[key] = value
                idx += 1
                matched = True
                break

        if matched:
            continue

        idx += 1

    if "title" not in result:
        raise IntentParseError("intent missing title")
    if "objective" not in result:
        raise IntentParseError("intent missing objective")

    result.setdefault("scope", "4节点, network=dev, ws=true, tls=false")
    result.setdefault("fault", "无")
    result.setdefault("fault_params", "")
    result.setdefault("traffic", "HTTP 50 QPS")
    result.setdefault("duration", "10m")
    result.setdefault("thresholds", [])
    result.setdefault("observe", "height,peer_count,rpc_success_rate")
    return result


def parse_intent_file(path: str | Path) -> dict[str, object]:
    text = Path(path).read_text(encoding="utf-8")
    return parse_intent_text(text)
