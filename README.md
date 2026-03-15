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
./scripts/prepare_env.sh --check-only
python3 -m framework.cli validate intents/*.md
python3 -m framework.cli compile-all --intent-dir intents --out-dir generated
```

## Environment Preparation (Linux/macOS)

Use the built-in script to check or install prerequisites:

```bash
# check only (safe default)
./scripts/prepare_env.sh --check-only

# auto install missing packages where possible
./scripts/prepare_env.sh --install --yes
```

The script detects OS and prepares:

1. Common tools: `python3`, `node`, `npm`, `artillery`, `docker`
2. Network fault backend:
   - Linux: `tc` (`iproute2`)
   - macOS: `dnctl + pfctl`
3. Docker compose availability (`docker compose` or `docker-compose`)
4. Starcoin binary existence (`--starcoin-bin` optional)

## Commands

```bash
python3 -m framework.cli list --intent-dir intents
python3 -m framework.cli validate intents/02-node-down.md
python3 -m framework.cli compile intents/02-node-down.md --out-dir generated \
  --http-target http://127.0.0.1:9850 --ws-target ws://127.0.0.1:9870
python3 -m framework.cli run intents/02-node-down.md \
  --starcoin-bin /Users/simon/starcoin-projects/starcoin/target/debug/starcoin \
  --base-port 26000 \
  --duration-override 60 \
  --fault-duration 30

python3 -m framework.cli run intents/10-tls-pubsub.md \
  --http-target https://rpc.example.com \
  --ws-target wss://rpc.example.com/ws \
  --duration-override 60

python3 -m framework.cli run-docker intents/01-baseline.md \
  --compose-file docker/starcoin-4node.compose.yml \
  --project-name starcoin-nettest \
  --duration-override 60

# wrapper script
./scripts/run_docker_intent.sh intents/01-baseline.md \
  --compose-file docker/starcoin-4node.compose.yml \
  --duration-override 60

# wrapper script
./scripts/run_intent.sh intents/02-node-down.md --node-count 2 --fault-duration 20
```

## Integrated Run (with starcoin binary)

`run` command does:

1. Start local Starcoin multi-node cluster with dedicated ports.
2. Compile intent into scenario/artillery/chaos artifacts under run folder.
3. Run fault injection (`node_down` / `node_restart` / `network_partition`).
4. Run Artillery load test (if installed).
5. Collect pre/post snapshots through both JSON-RPC and `starcoin` CLI commands.
6. Run a dedicated PubSub probe for event delivery, disconnect, and reconnect metrics.

For TLS scenarios, use remote target mode instead of the local binary runner:

1. The local Starcoin binary runner does not expose HTTPS/WSS endpoints.
2. Pass `--http-target` and `--ws-target` to run against an existing TLS-enabled deployment.
3. Add `--tls-insecure` only when you intentionally want to bypass certificate validation in a test environment.

Useful for faster local iteration:

```bash
python3 -m framework.cli run intents/09-pubsub-reconnect.md \
  --starcoin-bin /Users/simon/starcoin-projects/starcoin/target/debug/starcoin \
  --base-port 48000 \
  --node-count 2 \
  --fault-duration 8 \
  --duration-override 30 \
  --skip-artillery
```

Run outputs:

- `runs/<timestamp>-<intent-id>/generated/*.json`
- `runs/<timestamp>-<intent-id>/snapshots/pre/*`
- `runs/<timestamp>-<intent-id>/snapshots/post/*`
- `runs/<timestamp>-<intent-id>/pubsub-probe.json`
- `runs/<timestamp>-<intent-id>/run-summary.json`

## Docker Compose Run

`run-docker` does:

1. Start a docker compose cluster.
2. Wait for all configured HTTP RPC endpoints to answer `chain.info`.
3. Reuse the existing remote runner for intent compilation, Artillery, PubSub probe, and threshold evaluation.
4. Capture docker-cluster snapshots for every configured node before and after the run.
5. Tear the compose stack down by default.

Defaults:

1. If `--http-target` or `--ws-target` are omitted, the command infers local endpoints from the compose file's published `9850` / `9870` ports.
2. First endpoint is used as the primary target for load and PubSub execution.
3. All configured HTTP endpoints are included in docker pre/post snapshots.
4. The inferred endpoint count must match `--node-count` or the intent's `scope.nodes`; otherwise `run-docker` fails fast with a topology mismatch error.

Useful options:

1. `--keep-running`: leave the compose stack up after the run.
2. `--remove-volumes`: delete compose volumes on teardown.
3. `--http-target` / `--ws-target`: override inferred endpoints for custom compose files.
4. Use `docker/starcoin-4node.compose.yml` for the default 4-node intents; keep `docker/starcoin-3node.compose.yml` for explicit 3-node runs with `--node-count 3`.

## Notes

1. Generated Artillery config is scaffold-level and can be extended by QA.
2. Chaos script is a plan template; adapt stop/start commands to your node orchestration.
3. Keep `intents/*.md` as source of truth for test evolution.
4. `net_delay`/`net_loss` in integrated runner are OS-aware:
   - Linux uses `tc netem`
   - macOS uses `dnctl + pfctl`
   Both require root privileges.
5. PubSub metrics prefer `pubsub-probe.json` over Artillery summary heuristics when available.
6. `pubsub-probe.json` separates transient reconnect noise from unexpected probe errors so restart scenarios stay readable.
7. Remote target mode requires the target chain itself to progress; otherwise `chain_progress` will fail even if transport setup is healthy.
