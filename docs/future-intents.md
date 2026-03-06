# Future Intents

## P0

### 13-rpc-compat-regression

- Goal: compare common RPC behavior before and after upgrades.
- Focus:
  - response structure compatibility
  - error code compatibility
  - null/empty result semantics

### 14-pubsub-ordering

- Goal: verify `newHeads` notifications are not out-of-order, duplicated, or missing.
- Focus:
  - ordering
  - duplication
  - continuity

### 15-pubsub-reconnect-long-gap

- Goal: verify subscription recovery after a longer node outage.
- Focus:
  - reconnect success
  - event continuity after recovery
  - recovery time

### 16-rate-limit-behavior

- Goal: verify rate-limit behavior under pressure.
- Focus:
  - throttling error code
  - recovery time
  - non-throttled traffic isolation

## P1

### 17-peer-discovery-join-multi

- Goal: add multiple nodes during the test and verify discovery convergence.
- Focus:
  - discovery time
  - peer convergence
  - sync catch-up after join

### 18-network-partition-recover

- Goal: verify recovery after a real partition.
- Focus:
  - peer recovery
  - sync recovery
  - chain convergence

### 19-net-delay-readonly

- Goal: measure readonly RPC degradation under network delay.
- Focus:
  - p95/p99 latency drift
  - error rate
  - throughput stability

### 20-net-loss-pubsub

- Goal: verify pubsub behavior under packet loss.
- Focus:
  - reconnect count
  - event loss
  - subscription stability

### 21-mixed-http-ws-load

- Goal: run HTTP queries and WS subscriptions together.
- Focus:
  - mutual interference
  - latency drift
  - pubsub stability under mixed load

## P2

### 22-tls-cert-failure

- Goal: verify TLS failure behavior under bad certificates.
- Focus:
  - expired certificate
  - hostname mismatch
  - self-signed test environment handling

### 23-large-payload-boundary

- Goal: verify large request and boundary request handling.
- Focus:
  - request body limit
  - batch request behavior
  - oversized parameter handling

### 24-node-restart-storm

- Goal: verify resilience under repeated node restarts.
- Focus:
  - repeated recovery
  - peer churn
  - sync stability

### 25-soak-with-faults

- Goal: verify long-run stability with periodic fault injection.
- Focus:
  - memory drift
  - connection drift
  - error rate drift

## Immediate Priority

1. `13-rpc-compat-regression`
2. `14-pubsub-ordering`
3. `17-peer-discovery-join-multi`
