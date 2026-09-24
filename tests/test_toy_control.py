"""Positive-control regression: on the toy env (planted AUTH->INIT->RESET->
DATA->CRASH bug), random search on a fixed seed MUST find crashes and
saturate the state graph. If this breaks, the measurement pipeline broke,
not the target."""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from envs.toy_protocol import ToyProtocolEnv
from agents.policies import RandomPolicy


class TestToyPositiveControl(unittest.TestCase):
    def test_random_finds_planted_crash_and_saturates_states(self):
        store = {"states": set(), "edges": set(), "seqs": set(),
                 "crashes": [], "violations": []}
        env = ToyProtocolEnv(novelty_reward=True, novelty_store=store)
        agent = RandomPolicy(env.action_space, seed=0)
        obs, _ = env.reset(seed=0)
        for _ in range(20_000):
            obs, r, term, trunc, info = env.step(agent.act(obs))
            if term or trunc:
                obs, _ = env.reset()
        self.assertGreater(len(store["crashes"]), 0,
                           "planted bug not found - pipeline is broken")
        self.assertEqual(len(store["states"]), 10,
                         "state graph not saturated - pipeline is broken")
        for c in store["crashes"]:
            self.assertIn("sequence", c)

    def test_crash_reward_is_terminal(self):
        env = ToyProtocolEnv(novelty_reward=False,
                             novelty_store={"states": set(), "edges": set(),
                                            "seqs": set(), "crashes": [],
                                            "violations": []})
        obs, _ = env.reset(seed=0)
        for _ in range(20_000):
            # AUTH->INIT->RESET->DATA walk via random actions until crash
            a = env.action_space.sample()
            obs, r, term, trunc, info = env.step(a)
            if info.get("crash"):
                self.assertTrue(term)
                self.assertGreaterEqual(r, 100.0)
                return
            if term or trunc:
                obs, _ = env.reset()
        self.fail("no crash in 20k random steps")


if __name__ == "__main__":
    unittest.main()
