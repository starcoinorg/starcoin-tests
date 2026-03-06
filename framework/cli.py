from __future__ import annotations

import argparse
from pathlib import Path

from .compiler import write_compiled_outputs
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

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
