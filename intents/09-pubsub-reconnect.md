# 标题：PubSub重连恢复
目标：验证 websocket 连接中断并恢复后订阅能够重新建立且事件链路正常
范围：4节点, network=dev, ws=true, tls=false
扰动：重启一个节点
扰动参数：随机重启1节点, 持续60秒
流量：HTTP 40 QPS + WS 300订阅
持续时间：12m

通过条件：
- 链高度持续增长
- RPC成功率>=99%
- 订阅丢失率<=0.5%
- reconnect_success_rate>=99

观测指标：height, rpc_success_rate, pubsub_drop_rate, reconnect_success_rate, rpc_p95_ms, rpc_p99_ms
