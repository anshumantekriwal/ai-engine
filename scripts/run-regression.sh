#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "[ai-engine] Running Python compile checks"
python3 -m py_compile \
  server.py \
  strategy_spec_schema.py \
  strategy_spec_generator.py \
  spec_prompts.py \
  backtest_spec_schema.py \
  backtest_spec_generator.py \
  backtest_spec_prompts.py \
  code_generator.py

echo "[ai-engine] Running unit tests"
python3 -m unittest discover -s tests -p 'test_*.py'
