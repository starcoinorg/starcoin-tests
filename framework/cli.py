from __future__ import annotations

import argparse
import json
from pathlib import Path
from datetime import datetime

from .compiler import write_compiled_outputs
from .runtime import infer_compose_published_targets
from .runtime import run_docker_scenario
from .runtime import run_integrated_scenario
from .runtime import run_remote_scenario
from .translator import load_intent


def _cmd_list(args: argparse.Namespace) -> int:
    paths = sorted(Path(args.intent_dir).glob("*.md"))
    for p in paths:
        print(p)
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    rc = 0
    for raw in args.intent_files:
        path = Path(raw)
        try:
            intent = load_intent(path)
            print(f"OK {path} -> id={intent.id}, fault={intent.fault.type}, transports={intent.traffic.transports}")
        except Exception as exc:
            rc = 1
            print(f"ERR {path}: {exc}")
    return rc


def _compile_one(path: Path, args: argparse.Namespace) -> None:
    intent = load_intent(path)
    out = write_compiled_outputs(
        out_dir=args.out_dir,
        intent=intent,
        http_target=args.http_target,
        ws_target=args.ws_target,
    )
    print(f"COMPILED {path} ->")
    print(f"  - {out['canonical']}")
    print(f"  - {out['artillery']}")
    print(f"  - {out['chaos']}")


def _cmd_compile(args: argparse.Namespace) -> int:
    _compile_one(Path(args.intent_file), args)
    return 0


def _cmd_compile_all(args: argparse.Namespace) -> int:
    paths = sorted(Path(args.intent_dir).glob("*.md"))
    for p in paths:
        _compile_one(p, args)
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    intent_path = Path(args.intent_file)
    intent = load_intent(intent_path)
    if args.fault_duration is not None:
        intent.fault.params["duration_seconds"] = int(args.fault_duration)
    node_count = int(args.node_count or intent.scope.nodes)

    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = Path(args.run_dir) / f"{run_id}-{intent.id}"
    generated_dir = run_dir / "generated"
    generated_dir.mkdir(parents=True, exist_ok=True)

    base_port = int(args.base_port)
    node1_http = base_port + 150
    node1_ws = base_port + 170
    remote_mode = bool(args.http_target or args.ws_target)
    if (intent.scope.tls_http or intent.scope.tls_ws) and not remote_mode:
        print(
            "ERR TLS intent requires --http-target and --ws-target because the local Starcoin binary runner does not expose HTTPS/WSS endpoints."
        )
        return 1

    http_target = args.http_target or f"http://127.0.0.1:{node1_http}"
    ws_target = args.ws_target or f"ws://127.0.0.1:{node1_ws}"

    out = write_compiled_outputs(
        out_dir=generated_dir,
        intent=intent,
        http_target=http_target,
        ws_target=ws_target,
    )

    if remote_mode:
        summary = run_remote_scenario(
            intent=intent,
            run_dir=run_dir,
            http_target=http_target,
            ws_target=ws_target,
            artillery_config_path=out["artillery"],
            skip_artillery=bool(args.skip_artillery),
            duration_override_seconds=args.duration_override,
            insecure_tls=bool(args.tls_insecure),
        )
    else:
        summary = run_integrated_scenario(
            intent=intent,
            starcoin_bin=args.starcoin_bin,
            run_dir=run_dir,
            node_count=node_count,
            base_port=base_port,
            artillery_config_path=out["artillery"],
            skip_artillery=bool(args.skip_artillery),
            duration_override_seconds=args.duration_override,
        )

    summary_path = run_dir / "run-summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(f"RUN_DIR {run_dir}")
    print(f"SUMMARY {summary_path}")
    print(f"STATUS {summary.get('status')}")
    if summary.get("status") != "ok":
        return 1
    return 0


def _cmd_run_docker(args: argparse.Namespace) -> int:
    intent_path = Path(args.intent_file)
    intent = load_intent(intent_path)
    if args.fault_duration is not None:
        intent.fault.params["duration_seconds"] = int(args.fault_duration)

    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = Path(args.run_dir) / f"{run_id}-{intent.id}"
    generated_dir = run_dir / "generated"
    generated_dir.mkdir(parents=True, exist_ok=True)

    expected_node_count = int(args.node_count or intent.scope.nodes)
    compose_file = Path(args.compose_file)

    if bool(args.http_target) != bool(args.ws_target):
        print("ERR docker run requires both --http-target and --ws-target when overriding endpoints.")
        return 1

    if args.http_target:
        http_targets = list(args.http_target)
        ws_targets = list(args.ws_target)
    else:
        http_targets, ws_targets = infer_compose_published_targets(compose_file)
        if not http_targets or not ws_targets:
            print(
                "ERR failed to infer docker targets from compose file; "
                "pass explicit --http-target/--ws-target or expose 9850/9870 host ports."
            )
            return 1

    if len(http_targets) != len(ws_targets):
        print(
            "ERR docker compose target mismatch: "
            f"http_targets={len(http_targets)} ws_targets={len(ws_targets)}"
        )
        return 1

    if len(http_targets) != expected_node_count:
        print(
            "ERR docker compose topology does not match intent scope: "
            f"expected_nodes={expected_node_count} inferred_http_targets={len(http_targets)} "
            f"compose_file={compose_file}. "
            "Use a matching compose file (for example docker/starcoin-4node.compose.yml for 4-node intents) "
            "or override with --node-count plus matching --http-target/--ws-target."
        )
        return 1

    out = write_compiled_outputs(
        out_dir=generated_dir,
        intent=intent,
        http_target=http_targets[0],
        ws_target=ws_targets[0],
    )

    summary = run_docker_scenario(
        intent=intent,
        run_dir=run_dir,
        compose_file=compose_file,
        project_name=args.project_name,
        http_targets=http_targets,
        ws_targets=ws_targets,
        artillery_config_path=out["artillery"],
        skip_artillery=bool(args.skip_artillery),
        duration_override_seconds=args.duration_override,
        insecure_tls=bool(args.tls_insecure),
        keep_running=bool(args.keep_running),
        remove_volumes=bool(args.remove_volumes),
    )

    summary_path = run_dir / "run-summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"RUN_DIR {run_dir}")
    print(f"SUMMARY {summary_path}")
    print(f"STATUS {summary.get('status')}")
    if summary.get("status") != "ok":
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="starcoin nettest intent framework")
    sub = parser.add_subparsers(dest="command", required=True)

    list_cmd = sub.add_parser("list", help="list intent files")
    list_cmd.add_argument("--intent-dir", default="intents")
    list_cmd.set_defaults(func=_cmd_list)

    validate_cmd = sub.add_parser("validate", help="validate intent files")
    validate_cmd.add_argument("intent_files", nargs="+")
    validate_cmd.set_defaults(func=_cmd_validate)

    compile_cmd = sub.add_parser("compile", help="compile one intent file")
    compile_cmd.add_argument("intent_file")
    compile_cmd.add_argument("--out-dir", default="generated")
    compile_cmd.add_argument("--http-target", default="http://127.0.0.1:9850")
    compile_cmd.add_argument("--ws-target", default="ws://127.0.0.1:9870")
    compile_cmd.set_defaults(func=_cmd_compile)

    compile_all_cmd = sub.add_parser("compile-all", help="compile all intents in a dir")
    compile_all_cmd.add_argument("--intent-dir", default="intents")
    compile_all_cmd.add_argument("--out-dir", default="generated")
    compile_all_cmd.add_argument("--http-target", default="http://127.0.0.1:9850")
    compile_all_cmd.add_argument("--ws-target", default="ws://127.0.0.1:9870")
    compile_all_cmd.set_defaults(func=_cmd_compile_all)

    run_cmd = sub.add_parser(
        "run",
        help="run one intent end-to-end with local starcoin binary cluster",
    )
    run_cmd.add_argument("intent_file")
    run_cmd.add_argument(
        "--starcoin-bin",
        default="/Users/simon/starcoin-projects/starcoin/target/debug/starcoin",
    )
    run_cmd.add_argument("--run-dir", default="runs")
    run_cmd.add_argument("--base-port", type=int, default=26000)
    run_cmd.add_argument("--node-count", type=int, default=None)
    run_cmd.add_argument("--fault-duration", type=int, default=None)
    run_cmd.add_argument("--duration-override", type=int, default=None)
    run_cmd.add_argument("--http-target", default=None)
    run_cmd.add_argument("--ws-target", default=None)
    run_cmd.add_argument("--tls-insecure", action="store_true")
    run_cmd.add_argument("--skip-artillery", action="store_true")
    run_cmd.set_defaults(func=_cmd_run)

    docker_cmd = sub.add_parser(
        "run-docker",
        help="run one intent end-to-end against a docker compose managed cluster",
    )
    docker_cmd.add_argument("intent_file")
    docker_cmd.add_argument("--compose-file", required=True)
    docker_cmd.add_argument("--project-name", default="starcoin-nettest")
    docker_cmd.add_argument("--run-dir", default="runs")
    docker_cmd.add_argument("--node-count", type=int, default=None)
    docker_cmd.add_argument("--fault-duration", type=int, default=None)
    docker_cmd.add_argument("--duration-override", type=int, default=None)
    docker_cmd.add_argument("--http-target", action="append", default=[])
    docker_cmd.add_argument("--ws-target", action="append", default=[])
    docker_cmd.add_argument("--tls-insecure", action="store_true")
    docker_cmd.add_argument("--skip-artillery", action="store_true")
    docker_cmd.add_argument("--keep-running", action="store_true")
    docker_cmd.add_argument("--remove-volumes", action="store_true")
    docker_cmd.set_defaults(func=_cmd_run_docker)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
