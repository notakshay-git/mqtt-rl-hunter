#!/bin/bash
# Lane runner: sequentially runs seeds on one MQTT port. After each seed:
# replay-validate (serialized via flock) then commit+push results (serialized via flock).
# usage: run_lane.sh <port> <wait_pid|0> <seed1> [seed2 ...]
set -u
PORT=$1; WAITPID=$2; shift 2
cd /home/sandbox/mqtt-rl-hunter
if [ "$WAITPID" != "0" ]; then
  echo "[lane $PORT] waiting for pid $WAITPID (seed 0) to exit"
  while kill -0 "$WAITPID" 2>/dev/null; do sleep 60; done
fi
for SEED in "$@"; do
  echo "[lane $PORT] seed $SEED START $(date -Is)"
  python3 experiments/run_comparison.py --env mqtt --budget 100000 --seed "$SEED" --port "$PORT" \
    --agents random,coverage,rl --out "results/mqtt_comparison_seed${SEED}.json"
  echo "[lane $PORT] seed $SEED RUN DONE $(date -Is) - validating"
  flock /tmp/mqtt_validate.lock python3 repro/validate_run.py "results/mqtt_comparison_seed${SEED}.json" \
    || echo "[lane $PORT] VALIDATE FAILED seed $SEED"
  flock /tmp/mqtt_git.lock bash -c "
    cd /home/sandbox/mqtt-rl-hunter
    git add results/
    git commit -m 'MQTT 3-way seed $SEED results + replay validation (lane port $PORT)' || true
    GIT_SSH_COMMAND='ssh -i /home/sandbox/.ssh/id_ed25519 -o IdentitiesOnly=yes' \
      git push git@github.com:notakshay-git/mqtt-rl-hunter.git master:main || echo '[lane $PORT] PUSH FAILED seed $SEED'
  "
  echo "[lane $PORT] seed $SEED COMMITTED $(date -Is)"
done
echo "[lane $PORT] ALL SEEDS DONE $(date -Is)"
