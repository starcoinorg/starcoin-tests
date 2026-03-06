# Starcoin Command Integration

This framework integrates with Starcoin in two ways during `run`:

1. JSON-RPC calls over HTTP for machine-readable checks:
   - `chain.info`
   - `node.info`
   - `node.peers`
2. Raw `starcoin` CLI command snapshots for operator audit:
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
3. `net_delay`/`net_loss` try `tc netem` on `lo`; requires Linux + root privileges.
4. `rpc_rate_limit` is not implemented yet in local runner.
5. For CI/local dev, prefer binary mode with explicit port range (`--base-port`).
