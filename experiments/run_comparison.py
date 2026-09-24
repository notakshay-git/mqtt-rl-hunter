"""Three-way comparison runner: Random vs Coverage-guided vs RL (PPO).

Equal step budget per agent. Metrics (the headline result):
  unique states, unique edges, unique 6-action sequences, crashes,
  time-to-first-crash (env steps).
Writes metrics.json incrementally every 5k steps (checkpoint convention -
the sandbox can die at any time) plus PPO weight checkpoints.
"""
import argparse, json, os, sys, time
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from envs.toy_protocol import ToyProtocolEnv, STATE_NAMES
from envs.mqtt_env import MQTTFuzzEnv


def states_seen_names(store, env_name):
    if env_name == "toy":
        return [STATE_NAMES[s] for s in sorted(store["states"])]
    return [str(s) for s in sorted(store["states"], key=str)]
from agents.policies import RandomPolicy, CoverageGuidedPolicy, PPOPolicy


def run_agent(agent, make_env, budget, seed, progress_path, ckpt_dir=None):
    # Shared global novelty store across episodes for THIS agent run
    store = {"states": set(), "edges": set(), "seqs": set(),
             "crashes": [], "violations": []}
    env = make_env(store)
    obs, _ = env.reset(seed=seed)
    steps = 0
    episodes = 0
    first_crash_step = None
    t0 = time.time()
    ep_ret = 0.0
    recent_returns = []
    while steps < budget:
        if isinstance(agent, CoverageGuidedPolicy):
            a = agent.act(obs, state=env.state)
        else:
            a = agent.act(obs)
        obs, r, term, trunc, info = env.step(a)
        steps += 1
        ep_ret += r
        if isinstance(agent, CoverageGuidedPolicy):
            agent.observe(info["edge"][0], a)
        elif isinstance(agent, PPOPolicy):
            agent.observe(r, term or trunc)
        if info.get("crash") and first_crash_step is None:
            first_crash_step = steps
        if term or trunc:
            episodes += 1
            recent_returns.append(ep_ret)
            ep_ret = 0.0
            obs, _ = env.reset()
        if steps % 5000 == 0 or steps == budget:
            payload = {
                "agent": agent.name, "seed": seed, "steps": steps,
                "budget": budget, "episodes": episodes,
                "unique_states": len(store["states"]),
                "unique_edges": len(store["edges"]),
                "unique_seqs": len(store["seqs"]),
                "crashes": len(store["crashes"]),
                "first_crash_step": first_crash_step,
                "mean_ep_return_last20":
                    float(np.mean(recent_returns[-20:])) if recent_returns else 0.0,
                "wall_s": round(time.time() - t0, 1),
            }
            with open(progress_path, "w") as f:
                json.dump(payload, f, indent=2)
            if ckpt_dir and isinstance(agent, PPOPolicy):
                os.makedirs(ckpt_dir, exist_ok=True)
                agent.save(os.path.join(ckpt_dir, f"ppo_{steps}.pt"))
    return {
        "agent": agent.name, "seed": seed, "steps": steps,
        "episodes": episodes,
        "unique_states": len(store["states"]),
        "states_seen": states_seen_names(store, args.env),
        "violations": list(store["violations"]),
        "unique_edges": len(store["edges"]),
        "unique_seqs": len(store["seqs"]),
        "crashes": len(store["crashes"]),
        "first_crash_step": first_crash_step,
        "crash_sequences": [c["sequence"] for c in store["crashes"][:5]],
        "wall_s": round(time.time() - t0, 1),
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--budget", type=int, default=100_000)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--out", default="results/toy_comparison.json")
    p.add_argument("--agents", default="random,coverage,rl")
    p.add_argument("--env", choices=["toy", "mqtt"], default="toy")
    args = p.parse_args()

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    results = []
    for name in args.agents.split(","):
        if args.env == "toy":
            make_env = lambda store: ToyProtocolEnv(novelty_reward=True,
                                                    novelty_store=store)
        else:
            make_env = lambda store: MQTTFuzzEnv(novelty_reward=True,
                                                 novelty_store=store)
        probe = make_env({"states": set(), "edges": set(), "seqs": set(),
                          "crashes": [], "violations": []})
        if name == "random":
            agent = RandomPolicy(probe.action_space, seed=args.seed)
        elif name == "coverage":
            agent = CoverageGuidedPolicy(probe.action_space, seed=args.seed)
        elif name == "rl":
            agent = PPOPolicy(probe.action_space,
                              probe.observation_space.shape[0], seed=args.seed)
        else:
            raise ValueError(name)
        progress = args.out.replace(".json", f".{name}.progress.json")
        ckpt = f"checkpoints/{args.env}/{name}" if name == "rl" else None
        print(f"[{name}] budget={args.budget} seed={args.seed}", flush=True)
        results.append(run_agent(agent, make_env, args.budget, args.seed,
                                 progress, ckpt))
        print(f"[{name}] -> {json.dumps({k: v for k, v in results[-1].items() if k != 'crash_sequences'})}",
              flush=True)
    with open(args.out, "w") as f:
        json.dump({"budget": args.budget, "seed": args.seed,
                   "results": results}, f, indent=2)
    print("wrote", args.out)


if __name__ == "__main__":
    main()
