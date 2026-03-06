import unittest
from pathlib import Path

from framework.translator import load_intent
from framework.translator import _parse_fault


class TranslatorTest(unittest.TestCase):
    def test_load_node_down_intent(self) -> None:
        path = Path(__file__).resolve().parents[1] / "intents" / "02-node-down.md"
        scenario = load_intent(path)
        self.assertEqual(scenario.fault.type, "node_down")
        self.assertIn("http", scenario.traffic.transports)
        self.assertIn("ws", scenario.traffic.transports)
        self.assertGreaterEqual(len(scenario.thresholds), 3)

    def test_load_tls_intent_https_wss(self) -> None:
        path = Path(__file__).resolve().parents[1] / "intents" / "05-tls-rpc.md"
        scenario = load_intent(path)
        self.assertEqual(scenario.traffic.http_qps, 60)
        self.assertEqual(scenario.traffic.ws_subscriptions, 80)
        self.assertIn("http", scenario.traffic.transports)
        self.assertIn("ws", scenario.traffic.transports)

    def test_parse_fault_delay_loss_params(self) -> None:
        delay = _parse_fault("高延迟", "注入延迟120ms, 持续90秒")
        self.assertEqual(delay.type, "net_delay")
        self.assertEqual(delay.params.get("delay_ms"), 120)
        self.assertEqual(delay.params.get("duration_seconds"), 90)

        loss = _parse_fault("丢包", "丢包5%, 持续60秒")
        self.assertEqual(loss.type, "net_loss")
        self.assertEqual(loss.params.get("loss_percent"), 5.0)
        self.assertEqual(loss.params.get("duration_seconds"), 60)

    def test_parse_fault_none_keeps_scale_out_params(self) -> None:
        fault = _parse_fault("无", "测试期间新增2节点")
        self.assertEqual(fault.type, "none")
        self.assertEqual(fault.params.get("add_nodes"), 2)


if __name__ == "__main__":
    unittest.main()
