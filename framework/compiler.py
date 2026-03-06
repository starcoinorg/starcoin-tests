from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .models import IntentScenario


def _duration_seconds(duration_text: str) -> int:
    t = duration_text.strip().lower()
    if t.endswith("m") and t[:-1].isdigit():
        return int(t[:-1]) * 60
    if t.endswith("h") and t[:-1].isdigit():
        return int(t[:-1]) * 3600
    if t.endswith("s") and t[:-1].isdigit():
        return int(t[:-1])
    return 600


def build_canonical_scenario(intent: IntentScenario) -> dict:
    data = intent.to_dict()
    data["schema_version"] = "v1"
    return data


def build_artillery_scenario(
    intent: IntentScenario,
    http_target: str = "http://127.0.0.1:9850",
    ws_target: str = "ws://127.0.0.1:9870",
) -> dict:
    seconds = _duration_seconds(intent.duration)

    phases = [
        {
            "name": "warmup",
            "duration": min(60, max(10, seconds // 6)),
            "arrivalRate": max(1, intent.traffic.http_qps // 10 or 1),
        },
        {
            "name": "steady",
            "duration": max(30, seconds - min(60, max(10, seconds // 6))),
            "arrivalRate": max(1, intent.traffic.http_qps),
        },
    ]

    scenarios = []

    if "http" in intent.traffic.transports:
        scenarios.append(
            {
                "name": "rpc_http_chain_info",
                "flow": [
                    {
                        "post": {
                            "url": "/",
                            "json": {
                                "jsonrpc": "2.0",
                                "method": "chain.info",
                                "params": [],
                                "id": 1,
                            },
                        }
                    }
                ],
            }
        )

    if "ws" in intent.traffic.transports:
        scenarios.append(
            {
                "name": "rpc_ws_subscribe",
                "engine": "ws",
                "flow": [
                    {"connect": ws_target},
                    {
                        "send": '{"jsonrpc":"2.0","id":1,"method":"starcoin_subscribe","params":[["newHeads"]]}'
                    },
                    {"think": 5},
                    {
                        "send": '{"jsonrpc":"2.0","id":2,"method":"starcoin_unsubscribe","params":[1]}'
                    },
                ],
            }
        )

    return {
        "config": {
            "target": http_target,
            "phases": phases,
            "defaults": {"headers": {"content-type": "application/json"}},
        },
        "scenarios": scenarios,
    }


def build_chaos_plan(intent: IntentScenario) -> str:
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        f"# scenario: {intent.id}",
        f"# title: {intent.title}",
        f"# fault: {intent.fault.type}",
        "",
    ]

    if intent.fault.type == "none":
        lines.append("echo 'No fault injection in this scenario.'")
        return "\n".join(lines) + "\n"

    duration = int(intent.fault.params.get("duration_seconds", 60))
    count = int(intent.fault.params.get("count", 1))

    lines.extend(
        [
            "# TODO: replace with your orchestration command (systemd/docker/k8s).",
            f"echo 'Inject fault: {intent.fault.type}, count={count}, duration={duration}s'",
            "echo 'Example (docker): docker stop <node-container>'",
            f"sleep {duration}",
            "echo 'Example (docker): docker start <node-container>'",
        ]
    )
    return "\n".join(lines) + "\n"


def write_compiled_outputs(
    out_dir: str | Path,
    intent: IntentScenario,
    http_target: str,
    ws_target: str,
) -> dict[str, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    canonical = out / f"{intent.id}.scenario.json"
    artillery = out / f"{intent.id}.artillery.json"
    chaos = out / f"{intent.id}.chaos.sh"

    canonical.write_text(
        json.dumps(build_canonical_scenario(intent), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    artillery.write_text(
        json.dumps(
            build_artillery_scenario(intent, http_target=http_target, ws_target=ws_target),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    chaos.write_text(build_chaos_plan(intent), encoding="utf-8")
    chaos.chmod(0o755)

    return {
        "canonical": canonical,
        "artillery": artillery,
        "chaos": chaos,
    }
