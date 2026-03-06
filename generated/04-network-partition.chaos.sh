#!/usr/bin/env bash
set -euo pipefail

# scenario: 04-network-partition
# title: 网络分区恢复
# fault: network_partition

# TODO: replace with your orchestration command (systemd/docker/k8s).
echo 'Inject fault: network_partition, count=1, duration=180s'
echo 'Example (docker): docker stop <node-container>'
sleep 180
echo 'Example (docker): docker start <node-container>'
