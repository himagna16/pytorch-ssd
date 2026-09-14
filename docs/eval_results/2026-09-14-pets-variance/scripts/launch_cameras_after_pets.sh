#!/usr/bin/env bash
# bounded waiter: polls every 5 s for the pets harness to exit, then launches --cameras into OUT/cameras.
# Gives up (no camera flights) if the pets harness is still running at the deadline.
OUT=/Users/saimaruvada/Downloads/drone/pytorch_ssd/docs/eval_results/2026-09-14-pets-variance
LOCK=/private/tmp/claude-501/-Users-saimaruvada-Downloads/90541ca8-cca5-4400-9855-79d1dde551f0/scratchpad/sim.harness.lock
PETS_PID=$1; DEADLINE_EPOCH=$2
for i in $(seq 1 400); do
  if ! kill -0 "$PETS_PID" 2>/dev/null; then break; fi
  if [ "$(date +%s)" -ge "$DEADLINE_EPOCH" ]; then echo "deadline passed at $(date); cameras NOT launched" >> "$OUT/cameras_launch.txt"; exit 0; fi
  sleep 5
done
if [ "$(date +%s)" -ge "$DEADLINE_EPOCH" ]; then echo "deadline passed at $(date); cameras NOT launched" >> "$OUT/cameras_launch.txt"; exit 0; fi
mkdir -p "$OUT/cameras"
cd /Users/saimaruvada/Downloads/drone/pytorch_ssd/tools/crazysim_macos
echo "launch $(date -u +%Y-%m-%dT%H:%M:%SZ): ./run_acceptance2.sh --cameras --out $OUT/cameras --repeats 2 --lock $LOCK" >> "$OUT/cameras_launch.txt"
exec ./run_acceptance2.sh --cameras --out "$OUT/cameras" --repeats 2 --lock "$LOCK" > "$OUT/cameras/harness_stdout.log" 2>&1
