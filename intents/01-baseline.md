# 标题：多节点基线可用性
目标：验证无扰动场景下网络与RPC基础能力稳定
范围：4节点, network=dev, ws=true, tls=false
扰动：无
扰动参数：
流量：HTTP 80 QPS + WS 100订阅
持续时间：10m

通过条件：
- 链高度持续增长
- RPC成功率>=99%
- 订阅丢失率<=0.1%

观测指标：height, peer_count, rpc_success_rate, rpc_p95_ms, pubsub_drop_rate
