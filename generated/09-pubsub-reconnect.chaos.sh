#!/usr/bin/env bash
set -euo pipefail

# scenario: 09-pubsub-reconnect
# title: PubSub重连恢复
# fault: node_restart

# TODO: replace with your orchestration command (systemd/docker/k8s).
echo 'Inject fault: node_restart, count=1, duration=60s'
echo 'Example (docker): docker stop <node-container>'
sleep 60
echo 'Example (docker): docker start <node-container>'
