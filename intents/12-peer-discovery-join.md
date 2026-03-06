# 标题：新节点加入发现收敛
目标：验证新节点加入测试网络后能够被发现并在限定时间内建立连接
范围：6节点, network=dev, ws=true, tls=false
扰动：无
扰动参数：测试期间新增2节点
流量：HTTP 30 QPS + WS 60订阅
持续时间：15m

通过条件：
- 链高度持续增长
- RPC成功率>=99%
- peer_discovery_seconds<=120
- peer_count_after_recovery>=3

观测指标：height, peer_count, peer_discovery_seconds, rpc_success_rate, rpc_p95_ms
