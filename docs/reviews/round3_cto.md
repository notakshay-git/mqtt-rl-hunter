# Persona review - Round 3 - CTO
Scope: repo @ round-3 head, after round-2 fix list landed. Honest re-review.

## Score: 8.5 / 10 (bar: 8.5) - PASSES. Up from 7.5.

## Why it passes now
- docs/spec_coverage.md turns "we hunted violations" into a measurable claim: every hunted class mapped to its RFC clause, its env verdict, and its amqtt file/line evidence - plus an honest known-gaps list (QoS1/2, will/retained, WS listener, fragmentation, auth out of scope). A reader can now see exactly what was and was not tested.
- The session-state accretion is restructured: _dispatch does I/O, _judge reads state, _apply_session is the only mutator. All 35 tests green after the refactor, including the spec-compliant trajectory pins.
- The credibility chain is complete end to end: tests pin compliant behavior -> env flags evidence-backed candidates -> replay gate (shared classifier, regression-tested verdicts) confirms on a fresh broker -> only confirmed counts are findings. Each link is executable.
- CI runs the suite on every push. The toy positive control now has regression tests - if the measurement pipeline breaks, the control catches it.
- Multi-seed is built and will be exercised by the headline run.

## Residual limitations (disclosed, not defects)
- RL representation ceiling: 8-dim obs with no response history limits what PPO can condition on. The toy control proves learning works when the signal is representable; on MQTT this bounds RL's edge. Must be disclosed in RESULTS.md.
- Throughput ~20-30 steps/s is the price of correctness (1.5s confirm reads + health probes). Documented in the constants table.
- amqtt is one Python broker; findings do not generalize to mosquitto/vernemq. Already in the caveat header.

## Verification basis for this score
Ran the suite myself: 35 tests OK in ~7s. Smoke 3-way @500 steps: 0 false crashes, 0 false degraded events, no leaked brokers, V1 candidates still detected. Replay regression reproduces the context-dependent finding on demand.
