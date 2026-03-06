#!/usr/bin/env bash
set -euo pipefail

# scenario: 11-sync-catchup
# title: 节点恢复后同步追平
# fault: node_down

# TODO: replace with your orchestration command (systemd/docker/k8s).
echo 'Inject fault: node_down, count=1, duration=180s'
echo 'Example (docker): docker stop <node-container>'
sleep 180
echo 'Example (docker): docker start <node-container>'
