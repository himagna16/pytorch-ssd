#!/bin/sh
# Full safety-simulator run for the C controller (what tests/results/ holds).
# Runs the sections in parallel; each writes tests/results/<section>.txt.
# Usage (from tools/stm32_follow_app):  make libs && cd tests && ./run_sim_all.sh
set -e
cd "$(dirname "$0")"
PY="${PY:-python3}"
mkdir -p results
pids=""
run() { "$PY" safety_sim_review6_c.py "$@" > "results/$1.txt" 2>&1 & pids="$pids $!"; }
run checks
run timelines 200
run wraptimelines 200
run groundstep 200
for k in 0 1 2 3 4; do run mc$k 200 500; done
for k in 0 1 2 3 4; do run wrapmc$k 200 200; done
fail=0
for p in $pids; do wait "$p" || fail=1; done
echo "done (fail=$fail); summary:"
"$PY" summarize_results.py results
exit $fail
