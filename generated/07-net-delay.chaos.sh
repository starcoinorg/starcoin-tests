#!/usr/bin/env bash
set -euo pipefail

# scenario: 07-net-delay
# title: 网络高延迟回归
# fault: net_delay

# TODO: replace with your orchestration command (systemd/docker/k8s).
echo 'Inject fault: net_delay, count=1, duration=90s'
echo 'Example (docker): docker stop <node-container>'
sleep 90
echo 'Example (docker): docker start <node-container>'
