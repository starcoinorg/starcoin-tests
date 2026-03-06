# 标题：单节点重启恢复性
目标：验证节点重启后可重新入网并完成同步
范围：4节点, network=dev, ws=true, tls=false
扰动：重启一个节点
扰动参数：随机重启1节点, 持续120秒
流量：HTTP 80 QPS + WS 120订阅
持续时间：12m

通过条件：
- 链高度持续增长
- RPC成功率>=99%
- peer数在180秒内恢复到>=2

观测指标：height, peer_count, sync_lag, rpc_success_rate, rpc_p95_ms
