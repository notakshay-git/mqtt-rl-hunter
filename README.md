# mqtt-rl-hunter

RL vs coverage-guided vs random hunting of protocol state-machine bugs,
on PufferLib-style vectorizable gymnasium envs. Built to run on a 2-core /
2GB box (no GPU, no LLM).

## Targets
1. `envs/toy_protocol.py` - warm-up toy protocol (CONNECT/AUTH/INIT/DATA/
   CLOSE) with a hidden graph and one planted vuln:
   AUTH -> INIT -> RESET -> DATA -> CRASH. Positive control.
2. `envs/mqtt_env.py` - LIVE amqtt broker over raw TCP. 12 MQTT-flavored
   actions (valid/malformed CONNECT, dup CONNECT, v5 AUTH on v3 conn,
   subscribe pre/post auth, oversized publish, garbage bytes, ...).
   Hunts spec violations (V1-V4) and broker crashes.

## Design directives (owner-specified)
- GLOBAL novelty history (seen states/edges persist across episodes;
  per-episode reset teaches re-discovery, not discovery).
- NO timeout reward (reward-hacking bait).
- Three-way comparison on equal budget (Random vs Coverage-guided vs
  RL-PPO): unique states/edges/sequences, crashes, time-to-first-crash.
- Sparse terminal rewards, fixed seeds, checkpointing, incremental
  metrics writes (sandbox restarts lose <5k steps).

## PPO
Custom torch shim (`agents/policies.py`). pufferlib 3.0.0 pip sdist does
not build on this box (pyproject build hangs >20min on 2 cores);
git main is C/CUDA. The shim is self-contained.

## Run
    ./run.sh            # toy 3-way, 100k steps each
    ./run.sh mqtt       # MQTT 3-way, 100k steps each

Results land in `results/`, checkpoints in `checkpoints/`.

## Constants and why (round-2 architect review: magic numbers now have rationale)

| Constant | Value | Why |
|---|---|---|
| `MAX_STEPS` (episode length) | 60 | Long enough for multi-stage protocol sequences (open -> connect -> subscribe -> fuzz), short enough that a wedged episode cannot eat the budget |
| sequence novelty tail | 6 actions | Captures the planted-bug depth (toy CRASH path is 5) with one action of slack; longer tails explode the sequence space without adding signal |
| coverage epsilon | 0.15 | AFL-flavored: mostly least-tried, enough uniform random to escape count-table blind spots |
| violation confirm read | 1.5 s | amqtt under load answers in well under 1s when healthy; 0.1s was misreading slow-but-compliant as silent (course correction #2) |
| replay flag-step read | 3.0 s | Double the env's confirm read: the verifier must be strictly more patient than the detector |
| replay mid-sequence read | 0.3 s | Fresh broker answers in ms; only the flag step deserves patience |
| degradation threshold | 2.0 s RTT | Healthy probe is ~3-5 ms; 2s is ~500x healthy, far above load noise |
| broker restart | every 250 episodes | Bounds the resource-exhaustion mode (375+ CLOSE-WAIT fds observed) while keeping restart cost (~1s) under 1% of wall time |
| PPO batch | 2048 steps | ~34 episodes: enough GAE signal per update on a 60-step episode |
