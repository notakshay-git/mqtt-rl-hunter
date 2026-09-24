# Persona review - Round 2 - CTO
Scope: repo @ e3bcfbb, after round-1 fix list landed. Honest re-review.

## Score: 7.5 / 10 (bar: 8.5) - up from 6.5

## What changed my score
- 33 automated tests in ~5s, and they are the RIGHT tests: replay-verdict regression tests make the run's central finding executable (known-confirm and known-reject sequences), and the integration tests pin the spec-compliant behaviors the env must NOT flag. The four course corrections now each have a test-shaped guard.
- The detector and verifier share one classifier module. The divergence risk on the credibility gate is gone.
- The DoS/hang oracle is real: per-episode CONNECT->CONNACK RTT probe + broker fd sampling, with degraded events in the headline output. The failure mode we watched live (375+ CLOSE-WAIT fds, CPU pinned, still 'alive') is now measurable instead of invisible.
- Multi-seed is a capability now (--seeds with mean/std aggregate), not a caveat sentence.
- Port/config parameterization removes the stale-broker-poisons-the-run class that cost us 724 fake crashes.

## Remaining weaknesses (ranked)
1. **Violation coverage is still asserted, not measured.** V1-V4 are hand-picked clauses. I want a spec-coverage map: RFC  MQTT-3.x MUST clauses -> tested (how) / untested (why). Without it, "we hunted protocol violations" means "we hunted the four we thought of."
2. **Single-seed results still the only data.** The runner supports multi-seed; the headline doesn't use it yet.
3. **The env's session-state tracking is still special-case accretion** (three patches layered on patches this run). Tests now lock behavior, but the structure will invite correction #5.
4. **RL ceiling unquantified.** Obs space is 8 coarse dims with no response history; if RL ties random on MQTT we won't know if that's learning or representation.
5. **Throughput.** ~20-30 steps/s with the health probe. 100k x 3 agents ~3h. Fine once, painful per iteration.

## To 8.5
Spec-coverage map with file/line amqtt evidence refs, session-state consolidation, constants documented, one-command validation pipeline. Multi-seed headline can land with the full run.
