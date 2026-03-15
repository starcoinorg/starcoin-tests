# Starcoin Command Integration

This framework integrates with Starcoin in three ways:

1. Binary runner during `run`:
   - starts a local multi-node Starcoin cluster from a compiled `starcoin` binary
2. Docker compose runner during `run-docker`:
   - starts a compose-managed Starcoin cluster
   - waits for configured HTTP RPC endpoints
   - reuses the same intent compilation, Artillery, and PubSub probe flow
3. JSON-RPC calls over HTTP for machine-readable checks:
   - `chain.info`
   - `node.info`
   - `node.peers`
4. Raw `starcoin` CLI command snapshots for operator audit:
   - `starcoin -c ws://127.0.0.1:<port> chain info`
   - `starcoin -c ws://127.0.0.1:<port> node peers`

Generated files:

- `snapshots/pre/nodeX.chain_info.json`
- `snapshots/pre/nodeX.peers.json`
- `snapshots/pre/nodeX.starcoin-chain-info.raw.json`
- `snapshots/pre/nodeX.starcoin-node-peers.raw.json`
- `snapshots/post/...` (same set)

Notes:

1. Current local runner supports `none`, `node_down`, `node_restart`, `network_partition`.
2. `network_partition` prefers `network_manager.ban_peer`; if api is unavailable, fallback to stop/restart half cluster.
3. `net_delay`/`net_loss` select backend by OS:
   - Linux: `tc netem` on `lo`.
   - macOS: `dnctl + pfctl` (dummynet) on `lo0`.
4. Both Linux/macOS backends require root privileges.
5. `rpc_rate_limit` is not implemented yet in local runner.
6. For CI/local dev, prefer binary mode with explicit port range (`--base-port`).
7. Use `./scripts/prepare_env.sh` to check/install Linux/macOS prerequisites before running scenarios.
8. TLS scenarios use remote target mode:
   - `python3 -m framework.cli run intents/10-tls-pubsub.md --http-target https://... --ws-target wss://...`
   - local binary mode cannot expose HTTPS/WSS directly
   - add `--tls-insecure` only for self-signed test environments
9. Docker smoke path example:
   - `python3 -m framework.cli run-docker intents/01-baseline.md --compose-file docker/starcoin-4node.compose.yml --duration-override 60`
   - default inferred endpoints come from the compose file's published `9850`/`9870` host ports
   - use `--keep-running` when you want to inspect the cluster after the scenario
