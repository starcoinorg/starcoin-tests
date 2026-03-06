# starcoin-nettest

Text intent driven test framework for Starcoin network validation after `libp2p` and `jsonrpsee` upgrades.

## Goal

Allow R&D, QA, and users to add tests in readable text, for example:

`测试一个节点失效，网络正常运行`

The framework parses this intent and generates:

1. Canonical scenario JSON (for audit and review).
2. Artillery load scenario JSON (HTTP/WS).
3. Chaos execution plan shell script.

## Repository Layout

- `intents/`: human readable test cases.
- `framework/`: parser, translator, and compiler.
- `generated/`: compiled artifacts.
- `docs/`: templates and conventions.
- `tests/`: unit tests.

## Quick Start

```bash
cd starcoin-nettest
python3 -m framework.cli validate intents/*.md
python3 -m framework.cli compile-all --intent-dir intents --out-dir generated
```

## Commands

```bash
python3 -m framework.cli list --intent-dir intents
python3 -m framework.cli validate intents/02-node-down.md
python3 -m framework.cli compile intents/02-node-down.md --out-dir generated \
  --http-target http://127.0.0.1:9850 --ws-target ws://127.0.0.1:9870
```

## Notes

1. Generated Artillery config is scaffold-level and can be extended by QA.
2. Chaos script is a plan template; adapt stop/start commands to your node orchestration.
3. Keep `intents/*.md` as source of truth for test evolution.
