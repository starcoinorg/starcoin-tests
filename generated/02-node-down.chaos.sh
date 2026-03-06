#!/usr/bin/env bash
set -euo pipefail

# scenario: 02-node-down
# title: 单节点失效网络可用性
# fault: node_down

# TODO: replace with your orchestration command (systemd/docker/k8s).
echo 'Inject fault: node_down, count=1, duration=300s'
echo 'Example (docker): docker stop <node-container>'
sleep 300
echo 'Example (docker): docker start <node-container>'
