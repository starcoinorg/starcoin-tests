# 标题：TLS链路能力验证
目标：验证HTTPS/WSS链路在升级后可用且性能可接受
范围：4节点, network=dev, ws=true, tls=true
扰动：无
扰动参数：
流量：HTTPS 60 QPS + WSS 80订阅
持续时间：10m

通过条件：
- 链高度持续增长
- RPC成功率>=99%
- 订阅丢失率<=0.2%

观测指标：rpc_success_rate, rpc_p95_ms, tls_handshake_error_rate, pubsub_drop_rate
