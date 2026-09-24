#!/usr/bin/env bash
# Full test suite: units (fake sockets, packet bytes, GAE math) +
# real-broker integration (port 18895) + replay-verdict regression (18893).
set -euo pipefail
cd "$(dirname "$0")"
python3 -m unittest discover -s tests -v
