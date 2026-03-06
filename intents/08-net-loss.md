# 标题：网络丢包回归
目标：验证网络丢包情况下节点连通和RPC能力
范围：4节点, network=dev, ws=true, tls=false
扰动：丢包
扰动参数：丢包10%, 持续90秒
流量：HTTP 80 QPS + WS 120订阅
持续时间：12m

通过条件：
- 链高度持续增长
- RPC成功率>=97%

观测指标：height, peer_count, rpc_success_rate, rpc_p95_ms, rpc_p99_ms
