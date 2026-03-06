from __future__ import annotations

import json
import os
import platform
import re
import shutil
import ssl
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib import request

from .models import IntentScenario, Threshold


def parse_duration_seconds(text: str) -> int:
    t = text.strip().lower()
    if t.endswith("h") and t[:-1].isdigit():
        return int(t[:-1]) * 3600
    if t.endswith("m") and t[:-1].isdigit():
        return int(t[:-1]) * 60
    if t.endswith("s") and t[:-1].isdigit():
        return int(t[:-1])
    return 600


def _ssl_context(insecure_tls: bool = False) -> ssl.SSLContext | None:
    if not insecure_tls:
        return None
    return ssl._create_unverified_context()


def _rpc_call_url(
    http_url: str,
    method: str,
    params: list[Any] | None = None,
    insecure_tls: bool = False,
    timeout_seconds: float = 5.0,
) -> dict[str, Any]:
    body = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params or [],
        "id": 1,
    }
    req = request.Request(
        http_url,
        data=json.dumps(body).encode("utf-8"),
        headers={"content-type": "application/json"},
    )
    with request.urlopen(
        req,
        timeout=timeout_seconds,
        context=_ssl_context(insecure_tls),
    ) as resp:
        data = json.loads(resp.read())
    if "error" in data:
        raise RuntimeError(f"rpc error for {method}: {data['error']}")
    return data


@dataclass
class NodeProcess:
    index: int
    p2p_port: int
    http_port: int
    ws_port: int
    data_dir: Path
    log_path: Path
    seed: str | None
    process: subprocess.Popen[str]


@dataclass
class NodeSample:
    index: int
    ok: bool
    height: int | None
    peer_count: int | None
    error: str | None = None


@dataclass
class ClusterSample:
    timestamp: float
    nodes: list[NodeSample] = field(default_factory=list)


class ClusterObserver:
    def __init__(self, cluster: "StarcoinCluster", peer_target: int, interval_seconds: float = 1.0):
        self.cluster = cluster
        self.peer_target = peer_target
        self.interval_seconds = interval_seconds
        self.samples: list[ClusterSample] = []
        self.primary_attempts = 0
        self.primary_successes = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _poll_once(self) -> None:
        sample = ClusterSample(timestamp=time.time())
        for node in list(self.cluster.nodes):
            if node.index == 1:
                self.primary_attempts += 1
            try:
                chain_info = self.cluster._rpc_call(node.http_port, "chain.info")
                peers = self.cluster._rpc_call(node.http_port, "node.peers")
                if node.index == 1:
                    self.primary_successes += 1
                height = int(chain_info["result"]["head"]["number"])
                peer_count = len(peers.get("result", []))
                sample.nodes.append(
                    NodeSample(index=node.index, ok=True, height=height, peer_count=peer_count)
                )
            except Exception as exc:  # pragma: no cover - integration branch
                sample.nodes.append(
                    NodeSample(
                        index=node.index,
                        ok=False,
                        height=None,
                        peer_count=None,
                        error=str(exc),
                    )
                )
        self.samples.append(sample)

    def _run(self) -> None:
        while not self._stop.is_set():
            self._poll_once()
            self._stop.wait(self.interval_seconds)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)


class EndpointObserver:
    def __init__(self, http_url: str, interval_seconds: float = 1.0, insecure_tls: bool = False):
        self.http_url = http_url
        self.interval_seconds = interval_seconds
        self.insecure_tls = insecure_tls
        self.samples: list[dict[str, Any]] = []
        self.attempts = 0
        self.successes = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _poll_once(self) -> None:
        self.attempts += 1
        sample = {"timestamp": time.time(), "ok": False, "height": None, "peer_count": None}
        try:
            chain_info = _rpc_call_url(self.http_url, "chain.info", insecure_tls=self.insecure_tls)
            peers = _rpc_call_url(self.http_url, "node.peers", insecure_tls=self.insecure_tls)
            self.successes += 1
            sample["ok"] = True
            sample["height"] = int(chain_info["result"]["head"]["number"])
            sample["peer_count"] = len(peers.get("result", []))
        except Exception as exc:  # pragma: no cover - integration branch
            sample["error"] = str(exc)
        self.samples.append(sample)

    def _run(self) -> None:
        while not self._stop.is_set():
            self._poll_once()
            self._stop.wait(self.interval_seconds)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)


def _extract_peer_target(intent: IntentScenario) -> int:
    for threshold in intent.thresholds:
        if threshold.metric == "peer_count_after_recovery":
            return int(threshold.value)
    return 1 if intent.scope.nodes > 1 else 0


def _extract_added_nodes(intent: IntentScenario) -> int:
    value = intent.fault.params.get("add_nodes", 0)
    try:
        return max(0, int(value))
    except Exception:
        return 0


def _sample_max_height(sample: ClusterSample) -> int | None:
    heights = [node.height for node in sample.nodes if node.ok and node.height is not None]
    if not heights:
        return None
    return max(heights)


def _sample_node(sample: ClusterSample, node_index: int) -> NodeSample | None:
    for node in sample.nodes:
        if node.index == node_index:
            return node
    return None


def _samples_all_ready(sample: ClusterSample, expected_nodes: int, peer_target: int) -> bool:
    if len(sample.nodes) < expected_nodes:
        return False
    for node in sample.nodes:
        if not node.ok:
            return False
        if (node.peer_count or 0) < peer_target:
            return False
    return True


def _evaluate_threshold(metric_value: Any, threshold: Threshold) -> bool:
    if threshold.op == "==":
        return metric_value == threshold.value
    if threshold.op == ">=":
        return metric_value >= threshold.value
    if threshold.op == "<=":
        return metric_value <= threshold.value
    if threshold.op == ">":
        return metric_value > threshold.value
    if threshold.op == "<":
        return metric_value < threshold.value
    raise ValueError(f"unsupported operator: {threshold.op}")


def _build_measured_metrics(
    observer: ClusterObserver,
    intent: IntentScenario,
    fault_result: dict[str, Any],
    discovery_origin_ts: float | None,
    expected_nodes: int,
) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    first_height = None
    last_height = None
    if observer.samples:
        first_height = _sample_max_height(observer.samples[0])
        last_height = _sample_max_height(observer.samples[-1])
    if first_height is not None and last_height is not None:
        metrics["chain_progress"] = last_height > first_height
        metrics["height_delta"] = last_height - first_height

    if observer.primary_attempts > 0:
        metrics["rpc_success_rate"] = round(
            observer.primary_successes * 100.0 / observer.primary_attempts, 3
        )

    peer_target = observer.peer_target
    if observer.samples:
        last_sample = observer.samples[-1]
        ready_peer_counts = [
            node.peer_count for node in last_sample.nodes if node.ok and node.peer_count is not None
        ]
        if ready_peer_counts:
            metrics["peer_count_after_recovery"] = min(ready_peer_counts)

    if discovery_origin_ts is not None:
        for sample in observer.samples:
            if sample.timestamp < discovery_origin_ts:
                continue
            if _samples_all_ready(sample, expected_nodes=expected_nodes, peer_target=peer_target):
                metrics["peer_discovery_seconds"] = round(sample.timestamp - discovery_origin_ts, 3)
                break

    if fault_result.get("status") == "ok" and fault_result.get("target_node") is not None:
        recovered_at = fault_result.get("completed_at")
        target_node = int(fault_result["target_node"])
        if recovered_at is not None:
            for sample in observer.samples:
                if sample.timestamp < float(recovered_at):
                    continue
                if _samples_all_ready(sample, expected_nodes=expected_nodes, peer_target=peer_target):
                    metrics["peer_recovery_seconds"] = round(
                        sample.timestamp - float(recovered_at), 3
                    )
                    break
            for sample in observer.samples:
                if sample.timestamp < float(recovered_at):
                    continue
                node = _sample_node(sample, target_node)
                if node is None or not node.ok or node.height is None:
                    continue
                other_heights = [
                    n.height
                    for n in sample.nodes
                    if n.index != target_node and n.ok and n.height is not None
                ]
                if not other_heights:
                    continue
                if node.height >= max(other_heights) - 1 and (node.peer_count or 0) >= peer_target:
                    metrics["sync_recovery_seconds"] = round(
                        sample.timestamp - float(recovered_at), 3
                    )
                    break

    if (
        intent.traffic.ws_subscriptions > 0
        and intent.fault.type in {"node_restart", "node_down"}
        and fault_result.get("status") == "ok"
    ):
        if metrics.get("rpc_success_rate") is not None:
            metrics["reconnect_success_rate"] = metrics["rpc_success_rate"]

    return metrics


def _evaluate_thresholds(
    intent: IntentScenario,
    measured_metrics: dict[str, Any],
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    missing: list[str] = []
    failed: list[str] = []
    for threshold in intent.thresholds:
        if threshold.metric not in measured_metrics:
            missing.append(threshold.metric)
            results.append(
                {
                    "metric": threshold.metric,
                    "op": threshold.op,
                    "expected": threshold.value,
                    "status": "missing",
                }
            )
            continue
        actual = measured_metrics[threshold.metric]
        passed = _evaluate_threshold(actual, threshold)
        results.append(
            {
                "metric": threshold.metric,
                "op": threshold.op,
                "expected": threshold.value,
                "actual": actual,
                "status": "passed" if passed else "failed",
            }
        )
        if not passed:
            failed.append(threshold.metric)
    return {
        "results": results,
        "missing_metrics": missing,
        "failed_metrics": failed,
        "status": "passed" if not missing and not failed else "failed",
    }


class StarcoinCluster:
    def __init__(
        self,
        starcoin_bin: str,
        run_dir: Path,
        base_port: int = 26000,
        network: str = "dev",
    ) -> None:
        self.starcoin_bin = starcoin_bin
        self.run_dir = run_dir
        self.base_port = base_port
        self.network = network
        self.nodes: list[NodeProcess] = []
        self.seed_address: str | None = None
        self.self_addresses: dict[int, str] = {}

    @staticmethod
    def _tail_log(log_path: Path, max_lines: int = 40) -> str:
        try:
            lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except FileNotFoundError:
            return ""
        return "\n".join(lines[-max_lines:])

    @classmethod
    def _detect_runtime_issue(cls, node: NodeProcess) -> str | None:
        tail = cls._tail_log(node.log_path)
        if "Can't listen on" in tail and "PermissionDenied" in tail:
            return f"node-{node.index} cannot open p2p listen socket in current environment"
        if "Operation not permitted" in tail and "--listen" in tail:
            return f"node-{node.index} p2p listen failed with operation not permitted"
        if "panic occurred" in tail:
            return f"node-{node.index} panicked during startup"
        return None

    @staticmethod
    def _rpc_call(http_port: int, method: str, params: list[Any] | None = None) -> dict[str, Any]:
        body = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or [],
            "id": 1,
        }
        req = request.Request(
            f"http://127.0.0.1:{http_port}",
            data=json.dumps(body).encode("utf-8"),
            headers={"content-type": "application/json"},
        )
        with request.urlopen(req, timeout=2.0) as resp:
            data = json.loads(resp.read())
        if "error" in data:
            raise RuntimeError(f"rpc error for {method}: {data['error']}")
        return data

    def _wait_rpc_ready(self, node: NodeProcess, timeout_seconds: int = 120) -> None:
        deadline = time.time() + timeout_seconds
        last_error: Exception | None = None
        while time.time() < deadline:
            runtime_issue = self._detect_runtime_issue(node)
            if runtime_issue is not None:
                raise RuntimeError(f"{runtime_issue}\n{self._tail_log(node.log_path)}")
            if node.process.poll() is not None:
                raise RuntimeError(
                    f"node-{node.index} exited early with code {node.process.returncode}\n"
                    f"{self._tail_log(node.log_path)}"
                )
            try:
                self._rpc_call(node.http_port, "chain.info")
                return
            except Exception as exc:  # pragma: no cover - integration branch
                last_error = exc
                time.sleep(1.0)
        raise TimeoutError(
            f"node-{node.index} rpc is not ready in {timeout_seconds}s, last_error={last_error}"
        )

    def _refresh_node_identity(self, node: NodeProcess) -> None:
        node_info = self._rpc_call(node.http_port, "node.info")
        self.self_addresses[node.index] = node_info["result"]["self_address"]

    def _start_node(self, index: int, seed: str | None = None) -> NodeProcess:
        p2p_port = self.base_port + index * 100 + 40
        http_port = self.base_port + index * 100 + 50
        ws_port = self.base_port + index * 100 + 70
        data_dir = self.run_dir / "cluster" / f"node{index}"
        data_dir.mkdir(parents=True, exist_ok=True)
        log_path = self.run_dir / "cluster" / f"node{index}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_file = log_path.open("w", encoding="utf-8")

        cmd = [
            self.starcoin_bin,
            "-n",
            self.network,
            "-d",
            str(data_dir),
            "--disable-tcp-rpc",
            "--disable-metrics",
            "true",
            "--disable-stratum",
            "--rpc-address",
            "127.0.0.1",
            "--http-apis",
            "all",
            "--http-port",
            str(http_port),
            "--websocket-apis",
            "all",
            "--websocket-port",
            str(ws_port),
            "--listen",
            f"/ip4/127.0.0.1/tcp/{p2p_port}",
        ]
        if seed is not None:
            cmd.extend(["--seed", seed])
        else:
            cmd.append("--disable-seed")
        cmd.append("console")

        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
        )

        node = NodeProcess(
            index=index,
            p2p_port=p2p_port,
            http_port=http_port,
            ws_port=ws_port,
            data_dir=data_dir,
            log_path=log_path,
            seed=seed,
            process=proc,
        )
        self._wait_rpc_ready(node)
        self._refresh_node_identity(node)
        return node

    def _connect_full_mesh(self) -> None:
        if len(self.nodes) < 2:
            return
        for node in self.nodes:
            for other in self.nodes:
                if node.index == other.index:
                    continue
                target = self.self_addresses.get(other.index)
                if not target:
                    continue
                self._rpc_call(node.http_port, "network_manager.add_peer", [target])

    def start(self, node_count: int) -> None:
        if node_count < 1:
            raise ValueError("node_count must be >= 1")

        first = self._start_node(index=1, seed=None)
        self.nodes.append(first)
        self.seed_address = self.self_addresses[1]

        for idx in range(2, node_count + 1):
            node = self._start_node(index=idx, seed=self.seed_address)
            self.nodes.append(node)

        self._connect_full_mesh()
        self.wait_min_peers(target=1 if node_count > 1 else 0, timeout_seconds=60)

    def add_node(self) -> NodeProcess:
        index = len(self.nodes) + 1
        node = self._start_node(index=index, seed=self.seed_address)
        self.nodes.append(node)
        self._connect_full_mesh()
        self.wait_min_peers(target=1 if len(self.nodes) > 1 else 0, timeout_seconds=60)
        return node

    def add_nodes(self, count: int) -> list[int]:
        added: list[int] = []
        for _ in range(count):
            added.append(self.add_node().index)
        return added

    def wait_min_peers(self, target: int, timeout_seconds: int = 60) -> None:
        if target <= 0:
            return
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            ok = True
            for node in self.nodes:
                runtime_issue = self._detect_runtime_issue(node)
                if runtime_issue is not None:
                    raise RuntimeError(f"{runtime_issue}\n{self._tail_log(node.log_path)}")
                peers = self._rpc_call(node.http_port, "node.peers").get("result", [])
                if len(peers) < target:
                    ok = False
                    break
            if ok:
                return
            time.sleep(1.0)
        raise TimeoutError(f"peers did not reach target={target} in {timeout_seconds}s")

    def stop_node(self, index: int) -> None:
        node = self.nodes[index - 1]
        if node.process.poll() is None:
            if node.process.stdin is not None:
                node.process.stdin.close()
            try:
                node.process.wait(timeout=15)
            except subprocess.TimeoutExpired:  # pragma: no cover - integration branch
                node.process.terminate()
                node.process.wait(timeout=10)

    def restart_node(self, index: int) -> None:
        self.stop_node(index)
        seed = self.seed_address if index != 1 else None
        node = self._start_node(index=index, seed=seed)
        self.nodes[index - 1] = node
        self._connect_full_mesh()
        self.wait_min_peers(target=1 if len(self.nodes) > 1 else 0, timeout_seconds=60)

    def stop_all(self) -> None:
        for node in reversed(self.nodes):
            if node.process.poll() is None:
                if node.process.stdin is not None:
                    node.process.stdin.close()
                try:
                    node.process.wait(timeout=15)
                except subprocess.TimeoutExpired:  # pragma: no cover - integration branch
                    node.process.terminate()
                    node.process.wait(timeout=10)


def _ban_pair(cluster: StarcoinCluster, a: int, b: int, ban: bool) -> None:
    node_a = cluster.nodes[a - 1]
    node_b = cluster.nodes[b - 1]
    info_a = cluster._rpc_call(node_a.http_port, "node.info")
    info_b = cluster._rpc_call(node_b.http_port, "node.info")
    peer_a = info_a["result"]["peer_info"]["peer_id"]
    peer_b = info_b["result"]["peer_info"]["peer_id"]
    cluster._rpc_call(node_a.http_port, "network_manager.ban_peer", [peer_b, ban])
    cluster._rpc_call(node_b.http_port, "network_manager.ban_peer", [peer_a, ban])


def _detect_tc() -> str | None:
    tc_bin = shutil.which("tc")
    if tc_bin:
        return tc_bin
    return None


def _run_cmd(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, check=False)


def _apply_linux_netem(rule: str, duration: int) -> dict[str, Any]:
    tc_bin = _detect_tc()
    if tc_bin is None:
        return {
            "status": "unsupported",
            "detail": "tc netem not found in PATH, cannot inject net_delay/net_loss",
            "backend": "linux:tc",
        }

    if os.geteuid() != 0:
        return {
            "status": "unsupported",
            "detail": "tc netem requires root privileges; run as root or with sudo wrapper",
            "backend": "linux:tc",
        }

    iface = "lo"
    add_cmd = [tc_bin, "qdisc", "replace", "dev", iface, "root", "netem", *rule.split()]
    del_cmd = [tc_bin, "qdisc", "del", "dev", iface, "root"]
    add = _run_cmd(add_cmd)
    if add.returncode != 0:
        return {
            "status": "failed",
            "detail": f"failed to apply netem: {add.stderr.strip() or add.stdout.strip()}",
            "backend": "linux:tc",
        }

    time.sleep(duration)
    cleanup = _run_cmd(del_cmd)
    if cleanup.returncode != 0:
        return {
            "status": "failed",
            "detail": f"netem cleanup failed: {cleanup.stderr.strip() or cleanup.stdout.strip()}",
            "backend": "linux:tc",
        }
    return {
        "status": "ok",
        "detail": f"netem applied on {iface}: {rule} for {duration}s",
        "backend": "linux:tc",
    }


def _apply_macos_dummynet(rule: str, duration: int) -> dict[str, Any]:
    dnctl_bin = shutil.which("dnctl")
    pfctl_bin = shutil.which("pfctl")
    if not dnctl_bin or not pfctl_bin:
        return {
            "status": "unsupported",
            "detail": "dnctl/pfctl not found, cannot inject net_delay/net_loss on macOS",
            "backend": "darwin:dnctl+pfctl",
        }
    if os.geteuid() != 0:
        return {
            "status": "unsupported",
            "detail": "dnctl/pfctl requires root privileges on macOS",
            "backend": "darwin:dnctl+pfctl",
        }

    anchor = "com.apple/starcoin_nettest"
    pipe_id = "1"
    iface = "lo0"

    cfg_cmd = [dnctl_bin, "pipe", pipe_id, "config", *rule.split()]
    cfg = _run_cmd(cfg_cmd)
    if cfg.returncode != 0:
        return {
            "status": "failed",
            "detail": f"dnctl config failed: {cfg.stderr.strip() or cfg.stdout.strip()}",
            "backend": "darwin:dnctl+pfctl",
        }

    enable_pf = _run_cmd([pfctl_bin, "-E"])
    if enable_pf.returncode != 0:
        _run_cmd([dnctl_bin, "-q", "flush"])
        return {
            "status": "failed",
            "detail": f"pfctl enable failed: {enable_pf.stderr.strip() or enable_pf.stdout.strip()}",
            "backend": "darwin:dnctl+pfctl",
        }

    rules = "\n".join(
        [
            f"dummynet in quick on {iface} all pipe {pipe_id}",
            f"dummynet out quick on {iface} all pipe {pipe_id}",
            "",
        ]
    )
    load = subprocess.run(
        [pfctl_bin, "-a", anchor, "-f", "-"],
        input=rules,
        capture_output=True,
        text=True,
        check=False,
    )
    if load.returncode != 0:
        _run_cmd([pfctl_bin, "-a", anchor, "-F", "all"])
        _run_cmd([dnctl_bin, "-q", "flush"])
        return {
            "status": "failed",
            "detail": f"pfctl anchor load failed: {load.stderr.strip() or load.stdout.strip()}",
            "backend": "darwin:dnctl+pfctl",
        }

    time.sleep(duration)

    cleanup_pf = _run_cmd([pfctl_bin, "-a", anchor, "-F", "all"])
    cleanup_dn = _run_cmd([dnctl_bin, "-q", "flush"])
    if cleanup_pf.returncode != 0 or cleanup_dn.returncode != 0:
        detail = []
        if cleanup_pf.returncode != 0:
            detail.append(cleanup_pf.stderr.strip() or cleanup_pf.stdout.strip())
        if cleanup_dn.returncode != 0:
            detail.append(cleanup_dn.stderr.strip() or cleanup_dn.stdout.strip())
        return {
            "status": "failed",
            "detail": f"cleanup failed: {'; '.join([d for d in detail if d])}",
            "backend": "darwin:dnctl+pfctl",
        }
    return {
        "status": "ok",
        "detail": f"dummynet applied on {iface}: {rule} for {duration}s",
        "backend": "darwin:dnctl+pfctl",
    }


def _apply_network_impairment(rule: str, duration: int) -> dict[str, Any]:
    system = platform.system().lower()
    if system == "linux":
        return _apply_linux_netem(rule, duration)
    if system == "darwin":
        return _apply_macos_dummynet(rule, duration)
    return {
        "status": "unsupported",
        "detail": f"unsupported OS `{platform.system()}` for net_delay/net_loss injection",
        "backend": f"{system}:none",
    }


def run_starcoin_command(
    starcoin_bin: str,
    ws_port: int,
    command: list[str],
    output_path: Path,
) -> None:
    full_cmd = [starcoin_bin, "-c", f"ws://127.0.0.1:{ws_port}", *command]
    out = subprocess.run(full_cmd, capture_output=True, text=True, check=False)
    output_path.write_text(
        json.dumps(
            {
                "cmd": full_cmd,
                "returncode": out.returncode,
                "stdout": out.stdout,
                "stderr": out.stderr,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def snapshot_cluster(
    cluster: StarcoinCluster,
    snapshot_dir: Path,
    starcoin_bin: str,
) -> dict[str, Any]:
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    errors: list[dict[str, Any]] = []
    for node in cluster.nodes:
        try:
            chain_info = cluster._rpc_call(node.http_port, "chain.info")
            peers = cluster._rpc_call(node.http_port, "node.peers")
            (snapshot_dir / f"node{node.index}.chain_info.json").write_text(
                json.dumps(chain_info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            (snapshot_dir / f"node{node.index}.peers.json").write_text(
                json.dumps(peers, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
        except Exception as exc:  # pragma: no cover - integration branch
            errors.append({"node": node.index, "error": str(exc)})
            (snapshot_dir / f"node{node.index}.rpc-error.json").write_text(
                json.dumps(
                    {
                        "node": node.index,
                        "http_port": node.http_port,
                        "error": str(exc),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

        run_starcoin_command(
            starcoin_bin,
            node.ws_port,
            ["chain", "info"],
            snapshot_dir / f"node{node.index}.starcoin-chain-info.raw.json",
        )
        run_starcoin_command(
            starcoin_bin,
            node.ws_port,
            ["node", "peers"],
            snapshot_dir / f"node{node.index}.starcoin-node-peers.raw.json",
        )
    return {"errors": errors}


def snapshot_remote_endpoint(
    http_target: str,
    snapshot_dir: Path,
    insecure_tls: bool = False,
) -> dict[str, Any]:
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    errors: list[dict[str, Any]] = []
    for method, filename in (
        ("chain.info", "target.chain_info.json"),
        ("node.peers", "target.peers.json"),
    ):
        try:
            payload = _rpc_call_url(
                http_target,
                method,
                insecure_tls=insecure_tls,
                timeout_seconds=5.0,
            )
            (snapshot_dir / filename).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
        except Exception as exc:  # pragma: no cover - integration branch
            errors.append({"method": method, "error": str(exc)})
            (snapshot_dir / f"{filename}.error.json").write_text(
                json.dumps(
                    {"method": method, "target": http_target, "error": str(exc)},
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
    return {"errors": errors}


def run_fault_injection(cluster: StarcoinCluster, intent: IntentScenario) -> dict[str, Any]:
    fault = intent.fault.type
    params = intent.fault.params
    duration = int(params.get("duration_seconds", 60))
    result: dict[str, Any] = {
        "fault": fault,
        "status": "skipped",
        "detail": "",
        "started_at": time.time(),
    }

    if fault == "none":
        result["detail"] = "no fault configured"
        result["completed_at"] = result["started_at"]
        return result

    # Keep node-1 as seed anchor; inject on node-2 by default.
    target_index = 2 if len(cluster.nodes) >= 2 else 1
    result["target_node"] = target_index
    result["duration_seconds"] = duration

    if fault == "node_down":
        cluster.stop_node(target_index)
        time.sleep(duration)
        cluster.restart_node(target_index)
        result["status"] = "ok"
        result["detail"] = "node_down injected and node recovered"
        result["completed_at"] = time.time()
        return result

    if fault == "node_restart":
        cluster.stop_node(target_index)
        time.sleep(min(duration, 10))
        cluster.restart_node(target_index)
        result["status"] = "ok"
        result["detail"] = "node restarted"
        result["completed_at"] = time.time()
        return result

    if fault == "network_partition":
        if len(cluster.nodes) < 2:
            result["status"] = "unsupported"
            result["detail"] = "network_partition needs at least 2 nodes"
            return result
        # Split cluster by even/odd index and ban peer links across groups.
        left = [n.index for n in cluster.nodes if n.index % 2 == 1]
        right = [n.index for n in cluster.nodes if n.index % 2 == 0]
        if not left or not right:
            result["status"] = "unsupported"
            result["detail"] = "unable to split cluster into two groups"
            return result
        try:
            for a in left:
                for b in right:
                    _ban_pair(cluster, a, b, True)
            time.sleep(duration)
            for a in left:
                for b in right:
                    _ban_pair(cluster, a, b, False)
            cluster.wait_min_peers(target=1 if len(cluster.nodes) > 1 else 0, timeout_seconds=60)
            result["status"] = "ok"
            result["detail"] = "network partition injected via bidirectional ban_peer and recovered"
            result["groups"] = {"left": left, "right": right}
            result["mode"] = "ban_peer"
            result["completed_at"] = time.time()
            return result
        except Exception as exc:
            # Fallback for api-sets where network_manager methods are not exposed.
            for idx in right:
                cluster.stop_node(idx)
            time.sleep(duration)
            for idx in right:
                cluster.restart_node(idx)
            cluster.wait_min_peers(target=1 if len(cluster.nodes) > 1 else 0, timeout_seconds=60)
            result["status"] = "ok"
            result["detail"] = (
                "network_manager.ban_peer unavailable, fallback to process-level partition "
                f"(stop/restart right group): {exc}"
            )
            result["groups"] = {"left": left, "right": right}
            result["mode"] = "stop_restart_fallback"
            result["completed_at"] = time.time()
            return result

    if fault == "net_delay":
        delay_ms = int(params.get("delay_ms", 120))
        rule = f"delay {delay_ms}ms"
        netem = _apply_network_impairment(rule=rule, duration=duration)
        result.update(netem)
        result["detail"] = netem.get("detail", "")
        result["completed_at"] = time.time()
        return result

    if fault == "net_loss":
        loss_percent = float(params.get("loss_percent", 10))
        rule = f"loss {loss_percent}%"
        netem = _apply_network_impairment(rule=rule, duration=duration)
        result.update(netem)
        result["detail"] = netem.get("detail", "")
        result["completed_at"] = time.time()
        return result

    result["status"] = "unsupported"
    result["detail"] = f"fault type `{fault}` is not implemented yet in local binary runner"
    result["completed_at"] = time.time()
    return result


def run_artillery(
    artillery_config_path: Path,
    report_path: Path,
    env_extra: dict[str, str] | None = None,
) -> dict[str, Any]:
    if shutil.which("artillery") is None:
        return {"status": "skipped", "detail": "artillery not found in PATH"}

    cmd = ["artillery", "run", str(artillery_config_path)]
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    out = subprocess.run(cmd, capture_output=True, text=True, check=False, env=env)
    report_path.write_text(
        json.dumps(
            {
                "cmd": cmd,
                "returncode": out.returncode,
                "stdout": out.stdout,
                "stderr": out.stderr,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return {"status": "ok" if out.returncode == 0 else "failed", "returncode": out.returncode}


class BlockGenerator:
    def __init__(self, node: NodeProcess, interval_seconds: float = 3.0) -> None:
        self.node = node
        self.interval_seconds = interval_seconds
        self.attempts = 0
        self.successes = 0
        self.errors: list[str] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _run(self) -> None:
        while not self._stop.is_set():
            self.attempts += 1
            if self.node.process.poll() is not None:
                self.errors.append(
                    f"node-{self.node.index} exited with code {self.node.process.returncode}"
                )
            else:
                try:
                    body = {
                        "jsonrpc": "2.0",
                        "method": "debug.sleep",
                        "params": [1],
                        "id": self.attempts,
                    }
                    req = request.Request(
                        f"http://127.0.0.1:{self.node.http_port}",
                        data=json.dumps(body).encode("utf-8"),
                        headers={"content-type": "application/json"},
                    )
                    with request.urlopen(req, timeout=5.0) as resp:
                        payload = json.loads(resp.read())
                    if "error" in payload:
                        raise RuntimeError(str(payload["error"]))
                    self.successes += 1
                except Exception as exc:
                    self.errors.append(str(exc))
            if self._stop.wait(self.interval_seconds):
                break

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> dict[str, Any]:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=10)
        return {
            "attempts": self.attempts,
            "successes": self.successes,
            "errors": self.errors[-10:],
            "status": "ok" if self.successes > 0 and not self.errors else ("ok" if self.successes > 0 else "failed"),
        }


def _parse_artillery_number(value: str) -> float | int | None:
    raw = value.strip().replace(",", "")
    if not raw:
        return None
    try:
        number = float(raw)
    except ValueError:
        return None
    return int(number) if number.is_integer() else number


def _extract_artillery_metrics(stdout: str) -> dict[str, float | int]:
    marker = "Summary report @"
    if marker not in stdout:
        return {}
    summary = stdout.split(marker, 1)[1].splitlines()
    metrics: dict[str, float | int] = {}
    section: str | None = None
    for line in summary:
        stripped = line.rstrip()
        if not stripped or set(stripped.strip()) == {"-"}:
            continue
        if stripped.startswith("All VUs finished"):
            continue
        if not line.startswith(" ") and ":" in stripped:
            left = stripped.split(":", 1)[0].strip()
            if re.fullmatch(r"[A-Za-z0-9_.-]+", left):
                tail = stripped.split(":", 1)[1]
                value_text = tail.split()[-1] if tail.split() else ""
                parsed = _parse_artillery_number(value_text)
                if parsed is not None:
                    metrics[left] = parsed
                    section = None
                    continue
                section = left
                continue
        if line.startswith("  ") and section is not None and ":" in stripped:
            left = stripped.split(":", 1)[0].strip()
            tail = stripped.split(":", 1)[1]
            value_text = tail.split()[-1] if tail.split() else ""
            parsed = _parse_artillery_number(value_text)
            if parsed is not None:
                metrics[f"{section}.{left}"] = parsed
    return metrics


def _load_artillery_metrics(report_path: Path) -> dict[str, float | int]:
    if not report_path.exists():
        return {}
    raw = json.loads(report_path.read_text(encoding="utf-8"))
    stdout = str(raw.get("stdout", ""))
    return _extract_artillery_metrics(stdout)


def _derive_load_metrics(
    intent: IntentScenario,
    artillery_metrics: dict[str, float | int],
) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    if "http.response_time.p95" in artillery_metrics:
        metrics["rpc_p95_ms"] = artillery_metrics["http.response_time.p95"]
    if "http.response_time.p99" in artillery_metrics:
        metrics["rpc_p99_ms"] = artillery_metrics["http.response_time.p99"]

    ws_created = artillery_metrics.get("vusers.created_by_name.rpc_ws_subscribe")
    ws_messages_sent = artillery_metrics.get("websocket.messages_sent")
    if isinstance(ws_created, (int, float)) and ws_created > 0 and isinstance(
        ws_messages_sent, (int, float)
    ):
        # Current Artillery WS scenario sends one mandatory subscribe frame per virtual user.
        ws_delivery_rate = max(0.0, min(100.0, float(ws_messages_sent) * 100.0 / float(ws_created)))
        metrics["pubsub_drop_rate"] = round(100.0 - ws_delivery_rate, 3)
        if intent.fault.type in {"node_restart", "node_down"}:
            metrics["reconnect_success_rate"] = round(ws_delivery_rate, 3)

    if intent.scope.tls_http or intent.scope.tls_ws:
        tls_error_count = 0.0
        for key, value in artillery_metrics.items():
            if not isinstance(value, (int, float)):
                continue
            lowered = key.lower()
            if any(token in lowered for token in ("tls", "ssl", "cert", "handshake", "eproto")):
                tls_error_count += float(value)
        total_ops = 0.0
        for key in ("http.requests", "vusers.created_by_name.rpc_ws_subscribe"):
            value = artillery_metrics.get(key)
            if isinstance(value, (int, float)):
                total_ops += float(value)
        if total_ops > 0:
            metrics["tls_handshake_error_rate"] = round(tls_error_count * 100.0 / total_ops, 3)
    return metrics


def _pubsub_probe_workers(intent: IntentScenario) -> int:
    if intent.traffic.ws_subscriptions <= 0:
        return 0
    return max(1, min(int(intent.traffic.ws_subscriptions), 32))


def start_pubsub_probe(
    intent: IntentScenario,
    ws_url: str,
    http_url: str,
    run_dir: Path,
    duration_seconds: int,
    env_extra: dict[str, str] | None = None,
) -> tuple[subprocess.Popen[str] | None, Path, dict[str, Any]]:
    result_path = run_dir / "pubsub-probe.json"
    workers = _pubsub_probe_workers(intent)
    meta: dict[str, Any] = {
        "status": "skipped",
        "detail": "pubsub probe not enabled",
        "workers": workers,
        "ws_url": ws_url,
        "http_url": http_url,
    }
    if workers <= 0:
        return None, result_path, meta
    node_bin = shutil.which("node")
    if node_bin is None:
        meta["detail"] = "node not found in PATH"
        return None, result_path, meta

    script_path = Path(__file__).resolve().parents[1] / "scripts" / "pubsub_probe.mjs"
    cmd = [
        node_bin,
        str(script_path),
        "--ws-url",
        ws_url,
        "--http-url",
        http_url,
        "--workers",
        str(workers),
        "--duration-seconds",
        str(duration_seconds),
        "--output",
        str(result_path),
    ]
    log_path = run_dir / "pubsub-probe.log"
    log_file = log_path.open("w", encoding="utf-8")
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    proc = subprocess.Popen(cmd, stdout=log_file, stderr=subprocess.STDOUT, text=True, env=env)
    meta.update(
        {
            "status": "started",
            "detail": "pubsub probe started",
            "cmd": cmd,
            "log_path": str(log_path),
            "result_path": str(result_path),
        }
    )
    return proc, result_path, meta


def finish_pubsub_probe(
    proc: subprocess.Popen[str] | None,
    result_path: Path,
    meta: dict[str, Any],
    wait_timeout_seconds: int = 10,
) -> dict[str, Any]:
    if proc is None:
        return meta
    try:
        returncode = proc.wait(timeout=wait_timeout_seconds)
    except subprocess.TimeoutExpired:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        return {
            **meta,
            "status": "failed",
            "detail": "pubsub probe timed out",
        }
    if not result_path.exists():
        return {
            **meta,
            "status": "failed",
            "detail": f"pubsub probe exited with code {returncode}, result file missing",
        }
    raw = json.loads(result_path.read_text(encoding="utf-8"))
    raw["process_returncode"] = returncode
    return raw


def _derive_pubsub_probe_metrics(probe_result: dict[str, Any]) -> dict[str, Any]:
    if probe_result.get("status") != "ok":
        return {}
    aggregate = probe_result.get("aggregate", {})
    metrics: dict[str, Any] = {}
    for source_key, target_key in (
        ("pubsub_drop_rate", "pubsub_drop_rate"),
        ("reconnect_success_rate", "reconnect_success_rate"),
        ("tls_handshake_error_rate", "tls_handshake_error_rate"),
        ("subscribe_success_rate", "pubsub_subscribe_success_rate"),
    ):
        value = aggregate.get(source_key)
        if isinstance(value, (int, float)):
            metrics[target_key] = round(float(value), 3)
    if isinstance(aggregate.get("total_received_notifications"), (int, float)):
        metrics["pubsub_notifications"] = int(aggregate["total_received_notifications"])
    if isinstance(aggregate.get("total_expected_notifications"), (int, float)):
        metrics["pubsub_expected_notifications"] = int(aggregate["total_expected_notifications"])
        expected = int(aggregate["total_expected_notifications"])
        missing = aggregate.get("total_missing_notifications")
        if expected > 0 and isinstance(missing, (int, float)):
            metrics["pubsub_drop_rate"] = round(float(missing) * 100.0 / float(expected), 3)
    return metrics


def _derive_endpoint_metrics(observer: EndpointObserver) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    heights = [int(sample["height"]) for sample in observer.samples if sample.get("ok") and sample.get("height") is not None]
    if heights:
        metrics["chain_progress"] = heights[-1] > heights[0]
        metrics["height_delta"] = heights[-1] - heights[0]
    if observer.attempts > 0:
        metrics["rpc_success_rate"] = round(observer.successes * 100.0 / observer.attempts, 3)
    return metrics


def _probe_env(insecure_tls: bool) -> dict[str, str] | None:
    if not insecure_tls:
        return None
    return {"NODE_TLS_REJECT_UNAUTHORIZED": "0"}


def run_remote_scenario(
    intent: IntentScenario,
    run_dir: Path,
    http_target: str,
    ws_target: str,
    artillery_config_path: Path,
    skip_artillery: bool = False,
    duration_override_seconds: int | None = None,
    insecure_tls: bool = False,
) -> dict[str, Any]:
    artillery_report_path = run_dir / "artillery-report.json"
    requested_duration = (
        max(1, int(duration_override_seconds))
        if duration_override_seconds is not None
        else parse_duration_seconds(intent.duration)
    )
    scenario_duration_seconds = (
        min(requested_duration, 120) if skip_artillery and duration_override_seconds is None else requested_duration
    )
    summary: dict[str, Any] = {
        "intent_id": intent.id,
        "mode": "remote",
        "run_dir": str(run_dir),
        "target": {
            "http": http_target,
            "ws": ws_target,
            "insecure_tls": insecure_tls,
        },
    }

    observer = EndpointObserver(
        http_url=http_target,
        interval_seconds=1.0,
        insecure_tls=insecure_tls,
    )
    pubsub_probe_proc: subprocess.Popen[str] | None = None
    pubsub_probe_result_path = run_dir / "pubsub-probe.json"
    pubsub_probe_result: dict[str, Any] = {"status": "skipped", "detail": "not started"}
    env_extra = _probe_env(insecure_tls)

    try:
        pre_snapshot = snapshot_remote_endpoint(
            http_target=http_target,
            snapshot_dir=run_dir / "snapshots" / "pre",
            insecure_tls=insecure_tls,
        )
        observer.start()
        pubsub_probe_proc, pubsub_probe_result_path, pubsub_probe_result = start_pubsub_probe(
            intent=intent,
            ws_url=ws_target,
            http_url=http_target,
            run_dir=run_dir,
            duration_seconds=scenario_duration_seconds,
            env_extra=env_extra,
        )
        if pubsub_probe_proc is not None:
            time.sleep(2.0)

        if skip_artillery:
            load_result = {"status": "skipped", "detail": "skip_artillery=true"}
            time.sleep(scenario_duration_seconds)
        else:
            load_result = run_artillery(
                artillery_config_path=artillery_config_path,
                report_path=artillery_report_path,
                env_extra=env_extra,
            )

        pubsub_probe_result = finish_pubsub_probe(
            pubsub_probe_proc,
            pubsub_probe_result_path,
            pubsub_probe_result,
            wait_timeout_seconds=15,
        )
        observer.stop()
        post_snapshot = snapshot_remote_endpoint(
            http_target=http_target,
            snapshot_dir=run_dir / "snapshots" / "post",
            insecure_tls=insecure_tls,
        )
        measured_metrics = _derive_endpoint_metrics(observer)
        if artillery_report_path.exists():
            artillery_metrics = _load_artillery_metrics(artillery_report_path)
            load_result["artillery_metrics"] = artillery_metrics
            measured_metrics.update(_derive_load_metrics(intent, artillery_metrics))
        measured_metrics.update(_derive_pubsub_probe_metrics(pubsub_probe_result))
        threshold_result = _evaluate_thresholds(intent, measured_metrics)

        summary["snapshots"] = {"pre": pre_snapshot, "post": post_snapshot}
        summary["load"] = load_result
        summary["pubsub_probe"] = pubsub_probe_result
        summary["metrics"] = measured_metrics
        summary["thresholds"] = threshold_result
        summary["status"] = "ok"

        if load_result.get("status") == "failed":
            summary["status"] = "failed"
            summary["error"] = f"load test failed: {load_result}"
        if pubsub_probe_result.get("status") == "failed":
            summary["status"] = "failed"
            summary["error"] = f"pubsub probe failed: {pubsub_probe_result}"
        if threshold_result.get("status") == "failed":
            summary["status"] = "failed"
            summary["error"] = f"thresholds failed: {threshold_result.get('failed_metrics')}"
        return summary
    finally:
        observer.stop()
        if pubsub_probe_proc is not None and pubsub_probe_proc.poll() is None:
            pubsub_probe_proc.terminate()
            try:
                pubsub_probe_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pubsub_probe_proc.kill()
                pubsub_probe_proc.wait(timeout=5)


def run_integrated_scenario(
    intent: IntentScenario,
    starcoin_bin: str,
    run_dir: Path,
    node_count: int,
    base_port: int,
    artillery_config_path: Path,
    skip_artillery: bool = False,
    duration_override_seconds: int | None = None,
) -> dict[str, Any]:
    cluster = StarcoinCluster(starcoin_bin=starcoin_bin, run_dir=run_dir, base_port=base_port)
    artillery_report_path = run_dir / "artillery-report.json"
    requested_duration = (
        max(1, int(duration_override_seconds))
        if duration_override_seconds is not None
        else parse_duration_seconds(intent.duration)
    )
    scenario_duration_seconds = (
        min(requested_duration, 120) if skip_artillery and duration_override_seconds is None else requested_duration
    )
    added_nodes = _extract_added_nodes(intent)
    initial_node_count = max(1, node_count - added_nodes)
    expected_nodes = initial_node_count + added_nodes
    summary: dict[str, Any] = {
        "intent_id": intent.id,
        "node_count": node_count,
        "initial_node_count": initial_node_count,
        "base_port": base_port,
        "run_dir": str(run_dir),
    }
    observer: ClusterObserver | None = None
    pubsub_probe_proc: subprocess.Popen[str] | None = None
    pubsub_probe_result_path = run_dir / "pubsub-probe.json"
    pubsub_probe_result: dict[str, Any] = {"status": "skipped", "detail": "not started"}
    block_generator: BlockGenerator | None = None

    try:
        cluster.start(node_count=initial_node_count)
        summary["cluster"] = {
            "seed_address": cluster.seed_address,
            "nodes": [
                {
                    "index": n.index,
                    "p2p_port": n.p2p_port,
                    "http_port": n.http_port,
                    "ws_port": n.ws_port,
                    "data_dir": str(n.data_dir),
                    "log_path": str(n.log_path),
                }
                for n in cluster.nodes
            ],
        }
        observer = ClusterObserver(cluster=cluster, peer_target=_extract_peer_target(intent))
        observer.start()

        pre_snapshot = snapshot_cluster(
            cluster, run_dir / "snapshots" / "pre", starcoin_bin=starcoin_bin
        )
        if intent.scope.network == "dev":
            block_generator = BlockGenerator(node=cluster.nodes[0])
            block_generator.start()
            time.sleep(2.0)
        probe_node = cluster.nodes[0]
        if intent.fault.type in {"node_restart", "node_down"} and len(cluster.nodes) >= 2:
            probe_node = cluster.nodes[1]
        pubsub_probe_proc, pubsub_probe_result_path, pubsub_probe_result = start_pubsub_probe(
            intent=intent,
            ws_url=f"ws://127.0.0.1:{probe_node.ws_port}",
            http_url=f"http://127.0.0.1:{probe_node.http_port}",
            run_dir=run_dir,
            duration_seconds=scenario_duration_seconds,
        )
        if pubsub_probe_proc is not None:
            time.sleep(2.0)

        fault_result: dict[str, Any] = {"status": "skipped", "detail": "not started"}
        scale_out_result: dict[str, Any] = {"status": "skipped", "detail": "not configured"}
        discovery_origin_ts: float | None = None

        def _fault_runner() -> None:
            try:
                fault_result.update(run_fault_injection(cluster, intent))
            except Exception as exc:  # pragma: no cover - integration branch
                fault_result.update({"status": "failed", "detail": str(exc)})

        def _scale_out_runner() -> None:
            nonlocal discovery_origin_ts
            if added_nodes <= 0:
                scale_out_result.update({"status": "skipped", "detail": "no nodes to add"})
                return
            try:
                time.sleep(3.0)
                discovery_origin_ts = time.time()
                added = cluster.add_nodes(added_nodes)
                scale_out_result.update(
                    {
                        "status": "ok",
                        "detail": f"added {added_nodes} node(s)",
                        "requested": added_nodes,
                        "added_indices": added,
                        "started_at": discovery_origin_ts,
                        "completed_at": time.time(),
                    }
                )
            except Exception as exc:  # pragma: no cover - integration branch
                scale_out_result.update({"status": "failed", "detail": str(exc)})

        fault_thread = threading.Thread(target=_fault_runner, daemon=True)
        fault_thread.start()
        scale_out_thread = threading.Thread(target=_scale_out_runner, daemon=True)
        scale_out_thread.start()

        if skip_artillery:
            load_result = {"status": "skipped", "detail": "skip_artillery=true"}
            time.sleep(scenario_duration_seconds)
        else:
            load_result = run_artillery(
                artillery_config_path=artillery_config_path,
                report_path=artillery_report_path,
            )

        fault_thread.join()
        scale_out_thread.join()
        pubsub_probe_result = finish_pubsub_probe(
            pubsub_probe_proc,
            pubsub_probe_result_path,
            pubsub_probe_result,
            wait_timeout_seconds=15,
        )
        if observer is not None:
            observer.stop()

        post_snapshot = snapshot_cluster(
            cluster, run_dir / "snapshots" / "post", starcoin_bin=starcoin_bin
        )
        measured_metrics = (
            _build_measured_metrics(
                observer=observer,
                intent=intent,
                fault_result=fault_result,
                discovery_origin_ts=discovery_origin_ts,
                expected_nodes=expected_nodes,
            )
            if observer is not None
            else {}
        )
        if artillery_report_path.exists():
            artillery_metrics = _load_artillery_metrics(artillery_report_path)
            load_result["artillery_metrics"] = artillery_metrics
            measured_metrics.update(_derive_load_metrics(intent, artillery_metrics))
        measured_metrics.update(_derive_pubsub_probe_metrics(pubsub_probe_result))
        threshold_result = _evaluate_thresholds(intent, measured_metrics)
        summary["snapshots"] = {"pre": pre_snapshot, "post": post_snapshot}
        summary["fault"] = fault_result
        summary["scale_out"] = scale_out_result
        summary["load"] = load_result
        summary["pubsub_probe"] = pubsub_probe_result
        if block_generator is not None:
            summary["block_generator"] = block_generator.stop()
        summary["metrics"] = measured_metrics
        summary["thresholds"] = threshold_result
        summary["cluster"]["final_nodes"] = [
            {
                "index": n.index,
                "p2p_port": n.p2p_port,
                "http_port": n.http_port,
                "ws_port": n.ws_port,
                "data_dir": str(n.data_dir),
                "log_path": str(n.log_path),
            }
            for n in cluster.nodes
        ]
        summary["status"] = "ok"
        if fault_result.get("status") in {"failed"}:
            summary["status"] = "failed"
            summary["error"] = f"fault injection failed: {fault_result.get('detail')}"
        if (
            intent.fault.type != "none"
            and fault_result.get("status") in {"unsupported"}
            and summary.get("status") == "ok"
        ):
            summary["status"] = "failed"
            summary["error"] = f"fault injection unsupported: {fault_result.get('detail')}"
        if load_result.get("status") in {"failed"}:
            summary["status"] = "failed"
            summary["error"] = f"load test failed: {load_result}"
        if pubsub_probe_result.get("status") in {"failed"}:
            summary["status"] = "failed"
            summary["error"] = f"pubsub probe failed: {pubsub_probe_result}"
        if summary.get("block_generator", {}).get("status") == "failed":
            summary["status"] = "failed"
            summary["error"] = f"block generator failed: {summary['block_generator']}"
        if scale_out_result.get("status") in {"failed"}:
            summary["status"] = "failed"
            summary["error"] = f"scale out failed: {scale_out_result.get('detail')}"
        if post_snapshot.get("errors"):
            summary["status"] = "failed"
            summary["error"] = f"post snapshot rpc errors: {post_snapshot.get('errors')}"
        if threshold_result.get("status") == "failed":
            summary["status"] = "failed"
            summary["error"] = f"threshold evaluation failed: {threshold_result}"
        return summary

    except Exception as exc:
        summary["status"] = "failed"
        summary["error"] = str(exc)
        return summary
    finally:
        if block_generator is not None:
            block_generator.stop()
        if pubsub_probe_proc is not None and pubsub_probe_proc.poll() is None:
            pubsub_probe_proc.terminate()
            try:
                pubsub_probe_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pubsub_probe_proc.kill()
                pubsub_probe_proc.wait(timeout=5)
        if observer is not None:
            observer.stop()
        cluster.stop_all()
