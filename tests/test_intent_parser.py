import unittest

from framework.intent_parser import parse_intent_text


class IntentParserTest(unittest.TestCase):
    def test_parse_minimal_text(self) -> None:
        text = """
# 标题：单节点失效网络可用性
目标：验证节点失效后网络正常运行
范围：4节点, network=dev, ws=true, tls=false
扰动：停一个节点
扰动参数：随机停1节点, 持续300秒
流量：HTTP 100 QPS + WS 200订阅
持续时间：15m
通过条件：
- 链高度持续增长
- RPC成功率>=99%
观测指标：height, peer_count
"""
        parsed = parse_intent_text(text)
        self.assertEqual(parsed["title"], "单节点失效网络可用性")
        self.assertEqual(parsed["objective"], "验证节点失效后网络正常运行")
        self.assertEqual(parsed["duration"], "15m")
        self.assertEqual(len(parsed["thresholds"]), 2)

    def test_parse_delay_and_loss_params_text(self) -> None:
        text = """
# 标题：网络高延迟回归
目标：验证高延迟下网络与RPC稳定性
范围：4节点, network=dev, ws=true, tls=false
扰动：高延迟
扰动参数：注入延迟120ms, 持续90秒
流量：HTTP 30 QPS + WS 20订阅
持续时间：5m
通过条件：
- 链高度持续增长
观测指标：height, rpc_p95_ms
"""
        parsed = parse_intent_text(text)
        self.assertEqual(parsed["fault"], "高延迟")
        self.assertIn("120ms", str(parsed["fault_params"]))


if __name__ == "__main__":
    unittest.main()
