# 标题：节点恢复后同步追平
目标：验证节点长时间离线后恢复，能够在限定时间内重新追平区块高度
范围：4节点, network=dev, ws=true, tls=false
扰动：停一个节点
扰动参数：随机停1节点, 持续180秒
流量：HTTP 60 QPS + WS 80订阅
持续时间：20m

通过条件：
- 链高度持续增长
- RPC成功率>=99%
- peer数在180秒内恢复到>=2
- sync_recovery_seconds<=300

观测指标：height, peer_count, sync_lag, sync_recovery_seconds, rpc_success_rate, rpc_p95_ms, rpc_p99_ms
