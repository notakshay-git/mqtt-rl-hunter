# Persona review - Round 1 - CTO
Scope: whole repo @ 501c6cc (code, experiment design, RESULTS.md). Honest, no flattery.

## Score: 6.5 / 10 (bar: 8.5)

## What is genuinely good
- The replay-verification gate (repro/replay_candidates.py) is the credibility backbone: no finding ships without surviving re-execution on a fresh broker. The run's own history (smoke "real" -> canonical "false positive" -> replay "real") proves why this gate matters.
- Equal-budget 3-way with a planted-bug positive control is the right experimental shape.
- Caveat headers in RESULTS.md and disclosed course corrections are the honesty culture I want.
- Checkpoint/progress discipline assumes the box can die. Correct on this infra.

## Weaknesses (ranked)
1. **Zero automated tests.** The project's entire value is "trust our findings," yet every fix this run was verified by eyeball + smoke run. The four course corrections (false crashes, timeout misreads, violation misclassification, verification-depth reversal) are exactly the bug class a test suite catches. A reviewer cannot re-verify anything without re-running brokers by hand.
2. **Crash oracle = process death only.** We watched amqtt degrade live (375+ CLOSE-WAIT fds, CPU pinned, fd climb) without dying. The most commercially interesting outcome - a broker DoS that stays "alive" - scores zero in the headline metrics. fd counts are captured on violation events but never surfaced as a metric.
3. **Violation rules are hand-picked, not spec-derived.** V1-V4 are four clauses I chose. There is no map from RFC  MQTT-3.x MUST clauses to tested/ untested, so "coverage" is asserted, not measured.
4. **Single seed.** The toy table already shows first-crash ordering flips on seed luck; the MQTT headline will inherit that variance. Multi-seed is a sentence in the caveats, not a capability.
5. **"PufferLib" in the name, custom shim in the loop.** The PPO shim has no correctness tests (GAE math, value-loss behavior). A silent training bug would read as "RL isn't better" and we'd draw a scientific conclusion from an engineering defect.
6. **Fixed ports and /tmp config paths.** Already bit us once (724 fake crashes from a leaked broker). One stale process poisons a 2.5h run.
7. **Throughput ~30-40 steps/s** makes 100k x 3 agents ~2.5h wall. Acceptable, but it caps iteration speed; the 1.5s confirmation reads are the cost of correctness and I would not trade them back.

## What would move the score
- A real test suite incl. replay-validator regression tests (locks in the context-dependent finding), shared classifier between env and replay, hang/DoS degradation oracle in headline metrics, multi-seed runner with aggregate stats.
