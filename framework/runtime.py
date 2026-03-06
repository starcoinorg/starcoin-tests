from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import request

from .models import IntentScenario


def parse_duration_seconds(text: str) -> int:
    t = text.strip().lower()
    if t.endswith("h") and t[:-1].isdigit():
        return int(t[:-1]) * 3600
    if t.endswith("m") and t[:-1].isdigit():
        return int(t[:-1]) * 60
    if t.endswith("s") and t[:-1].isdigit():
        return int(t[:-1])
    return 600


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
            try:
                self._rpc_call(node.http_port, "chain.info")
                return
            except Exception as exc:  # pragma: no cover - integration branch
                last_error = exc
                time.sleep(1.0)
        raise TimeoutError(
            f"node-{node.index} rpc is not ready in {timeout_seconds}s, last_error={last_error}"
        )

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
            "--http-port",
            str(http_port),
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
        return node

    def start(self, node_count: int) -> None:
        if node_count < 1:
            raise ValueError("node_count must be >= 1")

        first = self._start_node(index=1, seed=None)
        self.nodes.append(first)
        node_info = self._rpc_call(first.http_port, "node.info")
        self.seed_address = node_info["result"]["self_address"]

        for idx in range(2, node_count + 1):
            node = self._start_node(index=idx, seed=self.seed_address)
            self.nodes.append(node)

        self.wait_min_peers(target=1 if node_count > 1 else 0, timeout_seconds=60)

    def wait_min_peers(self, target: int, timeout_seconds: int = 60) -> None:
        if target <= 0:
            return
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            ok = True
            for node in self.nodes:
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


def _run_tc_cmd(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, check=False)


def _apply_netem(rule: str, duration: int) -> dict[str, Any]:
    tc_bin = _detect_tc()
    if tc_bin is None:
        return {
            "status": "unsupported",
            "detail": "tc netem not found in PATH, cannot inject net_delay/net_loss",
        }

    if os.geteuid() != 0:
        return {
            "status": "unsupported",
            "detail": "tc netem requires root privileges; run as root or with sudo wrapper",
        }

    iface = "lo"
    add_cmd = [tc_bin, "qdisc", "replace", "dev", iface, "root", "netem", *rule.split()]
    del_cmd = [tc_bin, "qdisc", "del", "dev", iface, "root"]
    add = _run_tc_cmd(add_cmd)
    if add.returncode != 0:
        return {
            "status": "failed",
            "detail": f"failed to apply netem: {add.stderr.strip() or add.stdout.strip()}",
        }

    time.sleep(duration)
    cleanup = _run_tc_cmd(del_cmd)
    if cleanup.returncode != 0:
        return {
            "status": "failed",
            "detail": f"netem cleanup failed: {cleanup.stderr.strip() or cleanup.stdout.strip()}",
        }
    return {"status": "ok", "detail": f"netem applied on {iface}: {rule} for {duration}s"}


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


def run_fault_injection(cluster: StarcoinCluster, intent: IntentScenario) -> dict[str, Any]:
    fault = intent.fault.type
    params = intent.fault.params
    duration = int(params.get("duration_seconds", 60))
    result: dict[str, Any] = {"fault": fault, "status": "skipped", "detail": ""}

    if fault == "none":
        result["detail"] = "no fault configured"
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
        return result

    if fault == "node_restart":
        cluster.stop_node(target_index)
        time.sleep(min(duration, 10))
        cluster.restart_node(target_index)
        result["status"] = "ok"
        result["detail"] = "node restarted"
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
            return result

    if fault == "net_delay":
        delay_ms = int(params.get("delay_ms", 120))
        rule = f"delay {delay_ms}ms"
        netem = _apply_netem(rule=rule, duration=duration)
        result.update(netem)
        result["detail"] = netem.get("detail", "")
        return result

    if fault == "net_loss":
        loss_percent = float(params.get("loss_percent", 10))
        rule = f"loss {loss_percent}%"
        netem = _apply_netem(rule=rule, duration=duration)
        result.update(netem)
        result["detail"] = netem.get("detail", "")
        return result

    result["status"] = "unsupported"
    result["detail"] = f"fault type `{fault}` is not implemented yet in local binary runner"
    return result


def run_artillery(artillery_config_path: Path, report_path: Path) -> dict[str, Any]:
    if shutil.which("artillery") is None:
        return {"status": "skipped", "detail": "artillery not found in PATH"}

    cmd = ["artillery", "run", str(artillery_config_path)]
    out = subprocess.run(cmd, capture_output=True, text=True, check=False)
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


def run_integrated_scenario(
    intent: IntentScenario,
    starcoin_bin: str,
    run_dir: Path,
    node_count: int,
    base_port: int,
    artillery_config_path: Path,
    skip_artillery: bool = False,
) -> dict[str, Any]:
    cluster = StarcoinCluster(starcoin_bin=starcoin_bin, run_dir=run_dir, base_port=base_port)
    summary: dict[str, Any] = {
        "intent_id": intent.id,
        "node_count": node_count,
        "base_port": base_port,
        "run_dir": str(run_dir),
    }

    try:
        cluster.start(node_count=node_count)
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

        pre_snapshot = snapshot_cluster(
            cluster, run_dir / "snapshots" / "pre", starcoin_bin=starcoin_bin
        )

        fault_result: dict[str, Any] = {"status": "skipped", "detail": "not started"}

        def _fault_runner() -> None:
            try:
                fault_result.update(run_fault_injection(cluster, intent))
            except Exception as exc:  # pragma: no cover - integration branch
                fault_result.update({"status": "failed", "detail": str(exc)})

        fault_thread = threading.Thread(target=_fault_runner, daemon=True)
        fault_thread.start()

        if skip_artillery:
            load_result = {"status": "skipped", "detail": "skip_artillery=true"}
            time.sleep(min(parse_duration_seconds(intent.duration), 120))
        else:
            load_result = run_artillery(
                artillery_config_path=artillery_config_path,
                report_path=run_dir / "artillery-report.json",
            )

        fault_thread.join()

        post_snapshot = snapshot_cluster(
            cluster, run_dir / "snapshots" / "post", starcoin_bin=starcoin_bin
        )
        summary["snapshots"] = {"pre": pre_snapshot, "post": post_snapshot}
        summary["fault"] = fault_result
        summary["load"] = load_result
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
        if post_snapshot.get("errors"):
            summary["status"] = "failed"
            summary["error"] = f"post snapshot rpc errors: {post_snapshot.get('errors')}"
        return summary

    except Exception as exc:
        summary["status"] = "failed"
        summary["error"] = str(exc)
        return summary
    finally:
        cluster.stop_all()
