#!/bin/bash
set -euo pipefail

TOKEN=$(grep TERATTS_BEARER_TOKEN /etc/teratts/teratts.env | cut -d= -f2)
export TERATTS_TOKEN="$TOKEN"
export BENCH_PORT=8089

run_profile_block() {
  local profile_name="$1"
  local spinning="$2"
  local window_policy="$3"
  local block_id="$4"
  local count="${5:-25}"

  echo "=========================================================="
  echo "Setting up Profile $profile_name (Block $block_id): spinning=$spinning, window_policy=$window_policy"
  echo "=========================================================="

  cat > /etc/systemd/system/teratts-benchmark.service.d/profile.conf << EOF
[Service]
Environment=TERATTS_ORT_ALLOW_SPINNING=$spinning
Environment=TERATTS_VOCODER_WINDOW_POLICY=$window_policy
EOF

  systemctl daemon-reload
  systemctl restart teratts-benchmark.service

  # Wait for health ready
  echo "Waiting for teratts-benchmark.service to be ready..."
  for i in $(seq 1 30); do
    if curl -s http://127.0.0.1:8089/health | grep -q '"status":"ready"'; then
      break
    fi
    sleep 1
  done

  # Clear journal cursor mark or record timestamp
  local start_time
  start_time=$(date -u +"%Y-%m-%d %H:%M:%S")

  export BENCH_OUT="/tmp/bench_${profile_name}_block${block_id}.json"
  python3 /root/bench_profile.py "$count"

  # Collect server logs for this block
  journalctl -u teratts-benchmark.service --since "$start_time" --no-pager > "/tmp/logs_${profile_name}_block${block_id}.txt"
  echo "Completed Profile $profile_name Block $block_id."
}

mkdir -p /etc/systemd/system/teratts-benchmark.service.d

echo "Starting Series 1: A* -> B -> C -> D (25 requests each)"
run_profile_block "A" "1" "fixed16" "1" 25
run_profile_block "B" "0" "fixed16" "1" 25
run_profile_block "C" "1" "first16_then32" "1" 25
run_profile_block "D" "0" "first16_then32" "1" 25

echo "Starting Series 2: D -> C -> B -> A* (25 requests each, reversed order)"
run_profile_block "D" "0" "first16_then32" "2" 25
run_profile_block "C" "1" "first16_then32" "2" 25
run_profile_block "B" "0" "fixed16" "2" 25
run_profile_block "A" "1" "fixed16" "2" 25

echo "Stopping benchmark service..."
systemctl stop teratts-benchmark.service
echo "All blocks finished successfully."
