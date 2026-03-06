# 标题：网络高延迟回归
目标：验证网络高延迟情况下功能和性能退化在可控范围
范围：4节点, network=dev, ws=true, tls=false
扰动：高延迟
扰动参数：注入延迟120ms, 持续90秒
流量：HTTP 80 QPS + WS 120订阅
持续时间：12m

通过条件：
- 链高度持续增长
- RPC成功率>=98%

观测指标：height, peer_count, rpc_success_rate, rpc_p95_ms, rpc_p99_ms
