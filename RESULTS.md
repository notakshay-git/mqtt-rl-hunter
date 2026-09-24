# RESULTS - RL vs Random vs Coverage-Guided Protocol State-Machine Hunting

> ## Caveats (read first)
> - **Single seed (0).** All numbers below are one run per agent. Time-to-first-crash in particular is high-variance: on the toy, random got lucky and found the first crash *earlier* than RL this seed. Treat ordering as suggestive, not settled. Multi-seed runs are the follow-up.
> - **Toy env = positive control only.** The toy protocol has a *planted* bug (AUTH -> INIT -> RESET -> DATA -> CRASH). It proves the pipeline learns and the measurement works. It says nothing by itself about real protocols.
> - **MQTT target is amqtt** (pure-Python broker), not mosquitto. It is a real broker speaking real MQTT 3.1.1 over TCP, but Python brokers are more forgiving than C implementations; absence of crashes is weak evidence of absence.
> - **No GPU, shared 2-core/2GB box.** PPO is a small custom torch shim (pufferlib 3.0.0's pip sdist build hangs >20 min on this hardware - documented in README). Wall-clock numbers are not comparable across machines.
> - **Budget = env steps (100k), equal across agents.** RL pays its training compute inside the same step budget.

## Toy protocol (positive control) - 100k steps, seed 0

| Agent | Crashes | First crash (step) | Unique states | Unique edges | Unique sequences | Episodes | Wall (s) |
|---|---|---|---|---|---|---|---|
| Random | 250 | 47 | 10/10 | 42/42 | 36,990 | 6,687 | 0.6 |
| Coverage-guided | 241 | 303 | 10/10 | 42/42 | 35,370 | 6,762 | 2.8 |
| **RL (PPO shim)** | **1,003** | 83 | 10/10 | 42/42 | 26,227 | 2,662 | 33.0 |

Reading: the toy graph is small enough that all three agents saturate states/edges quickly, so coverage metrics cannot discriminate. On the metric that matters for bug hunting - **crash yield on equal budget** - RL is ~4x both baselines (1,003 vs 250/241). RL's *fewer* episodes (2,662 vs ~6,700) with *more* crashes shows it learned to walk the planted AUTH -> INIT -> RESET -> DATA -> CRASH path deliberately rather than stumbling on it. Random's lower first-crash step (47 vs 83) is luck on a single seed, exactly the variance the caveat header warns about; RL's advantage is *sustained yield*, not first-hit luck.

Raw data: `results/toy_comparison_seed0.json` (+ per-agent `.progress.json` every 5k steps, PPO checkpoints in `checkpoints/toy/rl/`).

## MQTT broker (live amqtt over raw TCP) - 100k steps, seed 0

_Run in progress - table lands when the run completes._

## Environment design notes

- **Global novelty history** (not per-episode): seen-states/edges/sequences persist across episodes, so novelty bonuses reward discovery, not re-discovery. One-time novelty at most.
- **No timeout reward.** Timeouts end episodes silently; nothing is paid for them, removing the reward-hacking incentive to farm cheap timeouts.
- **MQTT action space (12 ops):** valid/malformed CONNECT, duplicate AUTH, SUBSCRIBE before AUTH, oversized PUBLISH, disconnect-during-op, reconnect with old session, and friends. Violation classes V1-V4 (privileged state without auth, use-after-session, protocol-error tolerance, crash) are scored from raw broker responses, not from agent-internal state.
