# 标题：TLS下订阅链路验证
目标：验证 HTTPS 查询与 WSS 订阅在 TLS 场景下同时可用且稳定
范围：4节点, network=dev, ws=true, tls=true
扰动：无
扰动参数：
流量：HTTPS 50 QPS + WSS 200订阅
持续时间：10m

通过条件：
- 链高度持续增长
- RPC成功率>=99%
- 订阅丢失率<=0.2%
- tls_handshake_error_rate<=1

观测指标：rpc_success_rate, pubsub_drop_rate, tls_handshake_error_rate, rpc_p95_ms, rpc_p99_ms
