import unittest

from framework.models import Fault, IntentScenario, Scope, Traffic
from framework.runtime import EndpointObserver
from framework.runtime import _default_docker_http_targets
from framework.runtime import _default_docker_ws_targets
from framework.runtime import _derive_cluster_snapshot_metrics
from framework.runtime import _derive_endpoint_metrics
from framework.runtime import _derive_load_metrics
from framework.runtime import _derive_pubsub_probe_metrics
from framework.runtime import _extract_artillery_metrics


class RuntimeMetricsTest(unittest.TestCase):
    def test_extract_artillery_summary_metrics(self) -> None:
        stdout = """
Summary report @ 10:36:51(+0800)
--------------------------------

errors.ECONNRESET: ............................................................. 10
http.requests: ................................................................. 264
http.response_time:
  min: ......................................................................... 0
  p95: ......................................................................... 12
  p99: ......................................................................... 21
vusers.created_by_name.rpc_ws_subscribe: ....................................... 100
websocket.messages_sent: ....................................................... 97
"""
        metrics = _extract_artillery_metrics(stdout)
        self.assertEqual(metrics["errors.ECONNRESET"], 10)
        self.assertEqual(metrics["http.requests"], 264)
        self.assertEqual(metrics["http.response_time.p95"], 12)
        self.assertEqual(metrics["http.response_time.p99"], 21)
        self.assertEqual(metrics["vusers.created_by_name.rpc_ws_subscribe"], 100)
        self.assertEqual(metrics["websocket.messages_sent"], 97)

    def test_derive_load_metrics_for_pubsub_and_tls(self) -> None:
        intent = IntentScenario(
            id="tls-pubsub",
            title="tls pubsub",
            objective="test",
            scope=Scope(nodes=4, network="dev", tls_http=True, tls_ws=True),
            fault=Fault(type="node_restart", selector="random", params={}),
            traffic=Traffic(transports=["http", "ws"], http_qps=50, ws_subscriptions=100),
            duration="10m",
        )
        metrics = _derive_load_metrics(
            intent,
            {
                "http.requests": 200,
                "http.response_time.p95": 9,
                "http.response_time.p99": 18,
                "vusers.created_by_name.rpc_ws_subscribe": 100,
                "websocket.messages_sent": 97,
                "errors.ERR_TLS_CERT_ALTNAME_INVALID": 2,
            },
        )
        self.assertEqual(metrics["rpc_p95_ms"], 9)
        self.assertEqual(metrics["rpc_p99_ms"], 18)
        self.assertEqual(metrics["pubsub_drop_rate"], 3.0)
        self.assertEqual(metrics["reconnect_success_rate"], 97.0)
        self.assertAlmostEqual(metrics["tls_handshake_error_rate"], 0.667, places=3)

    def test_derive_pubsub_probe_metrics(self) -> None:
        metrics = _derive_pubsub_probe_metrics(
            {
                "status": "ok",
                "aggregate": {
                    "pubsub_drop_rate": 1.25,
                    "reconnect_success_rate": 98.5,
                    "tls_handshake_error_rate": 0.0,
                    "subscribe_success_rate": 100.0,
                    "total_received_notifications": 320,
                    "total_expected_notifications": 324,
                },
            }
        )
        self.assertEqual(metrics["pubsub_drop_rate"], 1.25)
        self.assertEqual(metrics["reconnect_success_rate"], 98.5)
        self.assertEqual(metrics["tls_handshake_error_rate"], 0.0)
        self.assertEqual(metrics["pubsub_subscribe_success_rate"], 100.0)
        self.assertEqual(metrics["pubsub_notifications"], 320)
        self.assertEqual(metrics["pubsub_expected_notifications"], 324)

    def test_derive_endpoint_metrics(self) -> None:
        observer = EndpointObserver(http_url="http://127.0.0.1:9850")
        observer.attempts = 10
        observer.successes = 9
        observer.samples = [
            {"timestamp": 1.0, "ok": True, "height": 8, "peer_count": 1},
            {"timestamp": 2.0, "ok": False, "height": None, "peer_count": None},
            {"timestamp": 3.0, "ok": True, "height": 12, "peer_count": 1},
        ]
        metrics = _derive_endpoint_metrics(observer)
        self.assertEqual(metrics["chain_progress"], True)
        self.assertEqual(metrics["height_delta"], 4)
        self.assertEqual(metrics["rpc_success_rate"], 90.0)

    def test_default_docker_targets(self) -> None:
        self.assertEqual(
            _default_docker_http_targets(3),
            [
                "http://127.0.0.1:19850",
                "http://127.0.0.1:19851",
                "http://127.0.0.1:19852",
            ],
        )
        self.assertEqual(
            _default_docker_ws_targets(3),
            [
                "ws://127.0.0.1:19870",
                "ws://127.0.0.1:19871",
                "ws://127.0.0.1:19872",
            ],
        )

    def test_derive_cluster_snapshot_metrics(self) -> None:
        metrics = _derive_cluster_snapshot_metrics(
            pre_snapshot={
                "nodes": [
                    {"status": "ok", "height": 4, "peer_count": 2},
                    {"status": "ok", "height": 5, "peer_count": 1},
                    {"status": "failed", "height": None, "peer_count": None},
                ]
            },
            post_snapshot={
                "nodes": [
                    {"status": "ok", "height": 8, "peer_count": 2},
                    {"status": "ok", "height": 9, "peer_count": 2},
                    {"status": "ok", "height": 8, "peer_count": 2},
                ]
            },
        )
        self.assertEqual(metrics["cluster_min_peer_count_pre"], 1)
        self.assertEqual(metrics["cluster_ready_nodes_pre"], 2)
        self.assertEqual(metrics["cluster_min_peer_count_post"], 2)
        self.assertEqual(metrics["cluster_ready_nodes_post"], 3)
        self.assertEqual(metrics["cluster_chain_progress"], True)
        self.assertEqual(metrics["cluster_height_delta"], 4)


if __name__ == "__main__":
    unittest.main()
