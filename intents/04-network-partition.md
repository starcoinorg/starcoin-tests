# 标题：网络分区恢复
目标：验证网络分区后能够重新收敛并持续出块
范围：6节点, network=dev, ws=true, tls=false
扰动：网络分区
扰动参数：随机分成两组, 持续180秒
流量：HTTP 120 QPS + WS 150订阅
持续时间：20m

通过条件：
- 链高度持续增长
- RPC成功率>=98%
- peer数在300秒内恢复到>=3

观测指标：height, fork_depth, peer_count, sync_lag, rpc_success_rate, rpc_p95_ms
