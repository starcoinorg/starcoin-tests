# 标题：长稳运行回归
目标：验证长时间运行下资源和错误率无异常漂移
范围：4节点, network=dev, ws=true, tls=false
扰动：无
扰动参数：
流量：HTTP 50 QPS + WS 80订阅
持续时间：6h

通过条件：
- 链高度持续增长
- RPC成功率>=99%
- error_rate<=1

观测指标：height, memory_rss_mb, fd_count, peer_count, rpc_success_rate, rpc_p95_ms, rpc_p99_ms
