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
