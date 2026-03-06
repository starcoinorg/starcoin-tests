# 标题：单节点失效网络可用性
目标：验证1个节点失效后网络仍正常运行
范围：4节点, network=dev, ws=true, tls=false
扰动：停一个节点
扰动参数：随机停1节点, 持续300秒
流量：HTTP 100 QPS + WS 200订阅
持续时间：15m

通过条件：
- 链高度持续增长
- RPC成功率>=99%
- peer数在120秒内恢复到>=2
- 订阅丢失率<=0.1%

观测指标：height, peer_count, sync_lag, rpc_success_rate, rpc_p95_ms, rpc_p99_ms, pubsub_drop_rate
