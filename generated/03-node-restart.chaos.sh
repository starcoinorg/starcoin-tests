#!/usr/bin/env bash
set -euo pipefail

# scenario: 03-node-restart
# title: 单节点重启恢复性
# fault: node_restart

# TODO: replace with your orchestration command (systemd/docker/k8s).
echo 'Inject fault: node_restart, count=1, duration=120s'
echo 'Example (docker): docker stop <node-container>'
sleep 120
echo 'Example (docker): docker start <node-container>'
