#!/usr/bin/env bash
set -euo pipefail
ENV="${1:-toy}"
BUDGET="${2:-100000}"
SEED="${3:-0}"
python3 experiments/run_comparison.py --env "$ENV" --budget "$BUDGET" \
  --seed "$SEED" --agents random,coverage,rl \
  --out "results/${ENV}_comparison_seed${SEED}.json"
