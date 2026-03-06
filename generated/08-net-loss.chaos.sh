#!/usr/bin/env bash
set -euo pipefail

# scenario: 08-net-loss
# title: 网络丢包回归
# fault: net_loss

# TODO: replace with your orchestration command (systemd/docker/k8s).
echo 'Inject fault: net_loss, count=1, duration=90s'
echo 'Example (docker): docker stop <node-container>'
sleep 90
echo 'Example (docker): docker start <node-container>'
