"""Toy protocol state-machine environment (warm-up target).

Per the project spec: hidden state graph, tiny discrete action space, one
planted vulnerability reachable via AUTH -> INIT -> RESET -> DATA -> CRASH.

Design directives (set by the project owner via the coordinating agent):
  1. GLOBAL novelty history: seen_states / seen_edges persist across episodes
     (per-episode reset teaches re-discovery, not discovery).
  2. NO timeout reward (reward-hacking bait: agent farms cheap timeouts).
"""
import gymnasium as gym
from gymnasium import spaces
import numpy as np

ACTIONS = ["CONNECT", "AUTH", "INIT", "DATA", "RESET", "CLOSE"]
CONNECT, AUTH, INIT, DATA, RESET, CLOSE = range(6)

# States
(IDLE, CONNECTED, AUTHED, READY, DATA_MODE, CLOSED, LIMBO, SUSPECT,
 CRASHED, DONE) = range(10)
STATE_NAMES = ["IDLE", "CONNECTED", "AUTHED", "READY", "DATA_MODE", "CLOSED",
               "LIMBO", "SUSPECT", "CRASHED", "DONE"]
TERMINAL = {CRASHED, DONE, CLOSED}

MAX_STEPS = 100


class ToyProtocolEnv(gym.Env):
    metadata = {"name": "toy-protocol-v1"}

    def __init__(self, novelty_reward=True, novelty_store=None):
        super().__init__()
        self.action_space = spaces.Discrete(6)
        # obs: [state_id/10, last_response/3, connected_flag, steps/max]
        self.observation_space = spaces.Box(low=0.0, high=1.0, shape=(4,),
                                            dtype=np.float32)
        self.novelty_reward = novelty_reward
        # Global novelty store: shared across episodes (and across vector envs)
        self.store = novelty_store if novelty_store is not None else {
            "states": set(), "edges": set(), "seqs": set(),
            "crashes": [], "violations": [],
        }

    def _obs(self):
        return np.array([self.state / 10.0, self.last_resp / 3.0,
                         float(self.state in (CONNECTED, AUTHED, READY,
                                              DATA_MODE, SUSPECT)),
                         self.steps / MAX_STEPS], dtype=np.float32)

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        self.state = IDLE
        self.last_resp = 0
        self.steps = 0
        self.path = []  # (state, action) history this episode
        return self._obs(), {"state": self.state}

    def _transition(self, a):
        """Returns (next_state, response, valid)."""
        s = self.state
        # Happy path
        if s == IDLE and a == CONNECT: return CONNECTED, 0, True
        if s == CONNECTED and a == AUTH: return AUTHED, 0, True
        if s == AUTHED and a == INIT: return READY, 0, True
        if s == READY and a == DATA: return DATA_MODE, 0, True
        if s == DATA_MODE and a == DATA: return DATA_MODE, 0, True
        if s == DATA_MODE and a == CLOSE: return DONE, 0, True
        # Weird-but-legal edges (discoverable)
        if s == AUTHED and a == AUTH: return AUTHED, 1, True          # re-auth
        if s == READY and a == AUTH: return AUTHED, 1, True           # downgrade
        if s == CLOSED:  # unreachable (terminal) - kept for completeness
            return LIMBO, 1, True
        if s == DATA_MODE and a == INIT: return LIMBO, 1, True        # confusion
        if s == LIMBO and a == DATA: return LIMBO, 1, True
        if s == LIMBO and a == CLOSE: return CLOSED, 0, True
        # Planted vulnerability: AUTH -> INIT -> RESET -> DATA -> CRASH
        if s == READY and a == RESET: return SUSPECT, 2, True
        if s == SUSPECT and a == DATA: return CRASHED, 2, True
        # RESET elsewhere: CONNECTED->IDLE only
        if s == CONNECTED and a == RESET: return IDLE, 0, True
        # CLOSE from mid-handshake states
        if s in (CONNECTED, AUTHED, READY, SUSPECT) and a == CLOSE:
            return CLOSED, 0, True
        return s, 1, False  # invalid: stay

    def step(self, action):
        a = int(action)
        prev = self.state
        nxt, resp, valid = self._transition(a)
        self.state = nxt
        self.steps += 1
        self.path.append((prev, a))

        reward = 0.0
        info = {"state": nxt, "valid": valid, "edge": (prev, a, nxt)}

        if not valid:
            reward -= 0.2

        # Global novelty bonuses (FIX #1: store persists across episodes)
        if self.novelty_reward:
            if nxt not in self.store["states"]:
                reward += 2.0
            edge = (prev, a, nxt)
            if edge not in self.store["edges"]:
                reward += 1.0
        self.store["states"].add(nxt)
        self.store["edges"].add((prev, a, nxt))
        tail = tuple(x[1] for x in self.path[-6:])
        self.store["seqs"].add(tail)

        terminated = False
        if nxt == CRASHED:
            reward += 100.0
            terminated = True
            self.store["crashes"].append({
                "episode_step": self.steps,
                "sequence": [ACTIONS[x[1]] for x in self.path],
            })
            info["crash"] = True
        elif nxt == DONE:
            reward += 5.0
            terminated = True
        elif nxt == CLOSED:
            terminated = True

        truncated = self.steps >= MAX_STEPS  # NOTE: no timeout reward (FIX #2)
        return self._obs(), reward, terminated, truncated, info
