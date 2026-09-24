# Persona review - Round 2 - Software Architect
Scope: repo @ e3bcfbb, after round-1 fix list landed. Honest re-review.

## Score: 7 / 10 (bar: 8.5) - up from 6

## What changed my score
- The classifier duplication is dead: envs/mqtt_classify.py is the single source of truth, unit-tested with fake sockets including the timeout-vs-close distinction that caused correction #2.
- Testable seams exist now: port/config injection let the integration and replay tests run real brokers on dedicated ports without touching production defaults.
- compute_gae is a pure function with hand-computed test vectors; PPO determinism and finiteness are pinned.
- Replay verdicts have regression tests capturing exactly the depth-reversal lesson: canonical reject, context confirm, post-valid reject.
- The health probe is the right shape for the DoS class: observation (RTT + fds) separated from verdict (threshold), metrics surfaced in results.

## Remaining weaknesses (ranked)
1. **Session-state model still heuristic.** _mqtt_connected/_subscribed are mutated in six places across step() with special cases (delayed CONNACK absorb, CONNECT_DUP, CLOSED_BY_BROKER reset). Tests pin current behavior; they don't prevent the next special case. Consolidate transitions into one method driven solely by observed responses, documented as an env-side estimate.
2. **Magic constants still undocumented.** MAX_STEPS=60, seq tail=6, epsilon=0.15, 1.5s confirm, 2.0s degrade threshold, restart every 250 episodes, 0.3s replay mid-read. Rationale belongs in one table.
3. **connected_before() in replay is still approximate** (its own comment admits it) and currently unused by any verdict - dead code or unfinished logic, pick one.
4. **Validation pipeline is still two commands plus tribal knowledge.** One entry point: validate a results file -> replay verdicts + summary. RESULTS.md still references validate_violations.py, which the replay gate superseded.
5. **Bare excepts** in broker kill paths remain silent.
6. No CI wiring: tests exist, nothing runs them but me.

## To 8.5
Session-state consolidation (1), constants table (2), resolve connected_before (3), one-command validate + doc cleanup (4). 5-6 are cheap: log, don't silence; add run_tests.sh.
