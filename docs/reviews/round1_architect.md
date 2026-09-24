# Persona review - Round 1 - Software Architect
Scope: whole repo @ 501c6cc. Honest, no flattery.

## Score: 6 / 10 (bar: 8.5)

## What is structurally sound
- Clean layering: envs / agents / experiments / repro. Packet builders are raw-byte and minimal. Evidence capture on violation events (full action sequence, broker fds, wall clock) is good design.
- Global novelty store injected per agent run - correct fix for the re-discovery flaw.
- Broker lifecycle (setsid killpg, periodic restart every 250 episodes) bounds the resource-exhaustion mode we observed.

## Weaknesses (ranked)
1. **No testable seams.** MQTTFuzzEnv.__init__ unconditionally spawns a real broker on a hardcoded port with a hardcoded /tmp config path. There is no way to inject a fake socket/broker, so the response classifier and the violation logic cannot be unit-tested. Result: zero tests.
2. **Duplicated response classifier.** env._read_resp and replay_candidates.read_resp are two hand-synced copies of the same MQTT response classification. The replay verdict and the env flag can silently diverge - the verifier could be checking a different predicate than the detector. This is the worst structural flaw because it attacks the verification gate itself.
3. **Heuristic session model with special-case accretion.** self._mqtt_connected is env-side truth that can go stale vs broker reality; each correction added a special case (CONNECT_DUP sets it, SUBSCRIBE absorbs a delayed CONNACK, CLOSED_BY_BROKER resets it). This whack-a-mole shape is what produced correction #3 and will produce #5. The right shape is a small explicit session-state machine driven solely by observed responses.
4. **replay_candidates.connected_before() is admittedly approximate** (its own comment says so), and flag-step reconstruction assumes the flagged action is last in the stored path. The verdict logic deserves regression tests with known-confirm and known-reject sequences.
5. **Observation space (8 dims) is coarse**: no recent-response history, no broker-load signal. RL cannot see the context that makes V1 fire, so "RL finds what random finds" would be confounded by representation, not learning.
6. **Magic constants undocumented**: MAX_STEPS=60, seq tail=6, epsilon=0.15, 1.5s confirm read, restart every 250 episodes. Fine choices, nowhere justified.
7. **Bare excepts** in broker kill/close paths mask real errors; acceptable in a harness, should be logged.
8. **Repro scripts are one-offs**, not wired into a single "validate results file" pipeline command; RESULTS.md still cites validate_violations.py while replay_candidates.py superseded it.

## What would move the score
- Extract a single shared classifier module used by env AND replay (kills #2), port/config parameterization + socket seam (kills #1, enables tests), session-state cleanup (#3), regression tests for the replay verdicts (#4), degradation oracle, and docs justifying constants.
