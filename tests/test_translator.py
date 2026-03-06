import unittest
from pathlib import Path

from framework.translator import load_intent


class TranslatorTest(unittest.TestCase):
    def test_load_node_down_intent(self) -> None:
        path = Path(__file__).resolve().parents[1] / "intents" / "02-node-down.md"
        scenario = load_intent(path)
        self.assertEqual(scenario.fault.type, "node_down")
        self.assertIn("http", scenario.traffic.transports)
        self.assertIn("ws", scenario.traffic.transports)
        self.assertGreaterEqual(len(scenario.thresholds), 3)


if __name__ == "__main__":
    unittest.main()
