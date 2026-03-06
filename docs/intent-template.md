# 标题：<一句话描述>
目标：<验证目标>
范围：<例如 4节点, network=dev, ws=true, tls=false>
扰动：<无/停一个节点/重启一个节点/网络分区/高延迟/丢包/限流>
扰动参数：<例如 随机停1节点, 持续300秒>
流量：<例如 HTTP 100 QPS + WS 200订阅>
持续时间：<例如 15m>

通过条件：
- 链高度持续增长
- RPC成功率>=99%
- peer数在120秒内恢复到>=2
- 订阅丢失率<=0.1%

观测指标：height, peer_count, sync_lag, rpc_success_rate, rpc_p95_ms, rpc_p99_ms, pubsub_drop_rate
