"""PPO shim correctness: GAE math hand-checked, update loop finite,
seeding deterministic."""
import os, sys, unittest
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agents.policies import compute_gae, PPOPolicy
import torch


class TestGAE(unittest.TestCase):
    def test_hand_computed_gamma1_lam1(self):
        # rews=[1,1,1], vals=[.5,.5,.5,0(bootstrap)], dones=[0,0,1]
        # deltas: t2: 1+0-.5=.5 ; t1: 1+.5-.5=1 ; t0: 1+.5-.5=1
        # gamma=lam=1: adv2=.5 ; adv1=1+.5=1.5 ; adv0=1+1.5=2.5
        adv = compute_gae(np.array([1., 1., 1.], dtype=np.float32),
                          np.array([.5, .5, .5, 0.], dtype=np.float32),
                          np.array([0., 0., 1.], dtype=np.float32), 1.0, 1.0)
        np.testing.assert_allclose(adv, [2.5, 1.5, 0.5], atol=1e-6)

    def test_zero_lambda_is_delta(self):
        rews = np.array([1., 2., 3.], dtype=np.float32)
        vals = np.array([.5, .5, .5, 0.], dtype=np.float32)
        dones = np.array([0., 0., 1.], dtype=np.float32)
        adv = compute_gae(rews, vals, dones, 0.99, 0.0)
        deltas = rews + 0.99 * vals[1:] * (1 - dones) - vals[:-1]
        np.testing.assert_allclose(adv, deltas, atol=1e-6)

    def test_terminal_cuts_bootstrap(self):
        # done at t=0: no bootstrap from vals[1]
        adv = compute_gae(np.array([1.], dtype=np.float32),
                          np.array([0.5, 99.0], dtype=np.float32),
                          np.array([1.], dtype=np.float32), 0.99, 0.95)
        np.testing.assert_allclose(adv, [0.5], atol=1e-6)


class TestPPO(unittest.TestCase):
    def test_deterministic_seed(self):
        obs = np.zeros(8, dtype=np.float32)
        a1 = PPOPolicy(DummySpace(12), 8, seed=7).act(obs)
        a2 = PPOPolicy(DummySpace(12), 8, seed=7).act(obs)
        self.assertEqual(a1, a2)

    def test_update_runs_and_stays_finite(self):
        pol = PPOPolicy(DummySpace(12), 8, seed=0, batch_steps=32)
        rng = np.random.default_rng(0)
        for _ in range(32):
            obs = rng.random(8).astype(np.float32)
            pol.act(obs)
            pol.observe(1.0, False)  # triggers update() at 32
        for p in pol.net.parameters():
            self.assertTrue(torch.isfinite(p).all().item())


class DummySpace:
    def __init__(self, n):
        self.n = n


if __name__ == "__main__":
    unittest.main()
