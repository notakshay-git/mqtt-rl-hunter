"""The three hunters: Random, Coverage-guided, RL (custom torch PPO shim).

Three-way comparison on equal step budget - the comparison (unique
states/edges/sequences/crashes/time-to-first-crash) is the headline result.
"""
import numpy as np
import torch
import torch.nn as nn


# ---------------------------------------------------------------- Random
class RandomPolicy:
    name = "random"

    def __init__(self, action_space, seed=0):
        self.rng = np.random.default_rng(seed)
        self.n = action_space.n

    def act(self, obs):
        return int(self.rng.integers(self.n))

    def observe(self, *args, **kwargs):
        pass


# ----------------------------------------------------- Coverage-guided
class CoverageGuidedPolicy:
    """AFL-flavored: prefers actions whose (state, action) pair is least
    tried globally; epsilon-random exploration on top."""
    name = "coverage"

    def __init__(self, action_space, seed=0, epsilon=0.15):
        self.rng = np.random.default_rng(seed)
        self.n = action_space.n
        self.epsilon = epsilon
        self.sa_counts = {}   # (state, action) -> count, GLOBAL

    def act(self, obs, state=None):
        if self.rng.random() < self.epsilon or state is None:
            return int(self.rng.integers(self.n))
        counts = np.array([self.sa_counts.get((state, a), 0)
                           for a in range(self.n)], dtype=np.float64)
        # softmax over negative counts -> least-tried most likely
        logits = -counts
        probs = np.exp(logits - logits.max())
        probs /= probs.sum()
        return int(self.rng.choice(self.n, p=probs))

    def observe(self, state, action, *args):
        if state is not None:
            self.sa_counts[(state, action)] = \
                self.sa_counts.get((state, action), 0) + 1


# ------------------------------------------------------------ PPO (torch)
class ActorCritic(nn.Module):
    def __init__(self, obs_dim, n_actions, hidden=64):
        super().__init__()
        self.body = nn.Sequential(
            nn.Linear(obs_dim, hidden), nn.Tanh(),
            nn.Linear(hidden, hidden), nn.Tanh())
        self.pi = nn.Linear(hidden, n_actions)
        self.v = nn.Linear(hidden, 1)

    def forward(self, x):
        h = self.body(x)
        return self.pi(h), self.v(h).squeeze(-1)


class PPOPolicy:
    """Custom torch PPO shim (pufferlib pip 3.0.0 ships no usable pure-python
    trainer on this box; git main is C/CUDA). Single-env, on-policy."""
    name = "rl-ppo"

    def __init__(self, action_space, obs_dim, seed=0, lr=3e-4, gamma=0.99,
                 lam=0.95, clip=0.2, ent_coef=0.01, epochs=4, batch_steps=2048,
                 device="cpu"):
        torch.manual_seed(seed)
        self.rng = np.random.default_rng(seed)
        self.n = action_space.n
        self.net = ActorCritic(obs_dim, self.n).to(device)
        self.opt = torch.optim.Adam(self.net.parameters(), lr=lr)
        self.gamma, self.lam, self.clip = gamma, lam, clip
        self.ent_coef, self.epochs, self.batch_steps = ent_coef, epochs, batch_steps
        self.device = device
        self._reset_buffers()

    def _reset_buffers(self):
        self.buf = {k: [] for k in
                    ("obs", "act", "logp", "rew", "val", "done")}

    def act(self, obs):
        with torch.no_grad():
            x = torch.as_tensor(obs, dtype=torch.float32, device=self.device)
            logits, v = self.net(x)
            dist = torch.distributions.Categorical(logits=logits)
            a = dist.sample()
        self._last = (obs, int(a), float(dist.log_prob(a)), float(v))
        return int(a)

    def observe(self, reward, done):
        obs, a, logp, v = self._last
        self.buf["obs"].append(obs)
        self.buf["act"].append(a)
        self.buf["logp"].append(logp)
        self.buf["rew"].append(reward)
        self.buf["val"].append(v)
        self.buf["done"].append(done)
        if len(self.buf["rew"]) >= self.batch_steps:
            self.update()

    def update(self):
        b = self.buf
        rews = np.array(b["rew"], dtype=np.float32)
        vals = np.array(b["val"] + [0.0], dtype=np.float32)
        dones = np.array(b["done"] + [True], dtype=np.float32)
        # GAE
        adv = np.zeros_like(rews)
        gae = 0.0
        for t in reversed(range(len(rews))):
            delta = rews[t] + self.gamma * vals[t + 1] * (1 - dones[t]) - vals[t]
            gae = delta + self.gamma * self.lam * (1 - dones[t]) * gae
            adv[t] = gae
        ret = adv + vals[:-1]
        obs = torch.as_tensor(np.array(b["obs"]), dtype=torch.float32,
                              device=self.device)
        act = torch.as_tensor(b["act"], device=self.device)
        old_logp = torch.as_tensor(b["logp"], device=self.device)
        adv_t = torch.as_tensor(adv, device=self.device)
        adv_t = (adv_t - adv_t.mean()) / (adv_t.std() + 1e-8)
        ret_t = torch.as_tensor(ret, device=self.device)
        n = len(act)
        idx = np.arange(n)
        for _ in range(self.epochs):
            self.rng.shuffle(idx)
            for start in range(0, n, 512):
                mb = idx[start:start + 512]
                logits, v = self.net(obs[mb])
                dist = torch.distributions.Categorical(logits=logits)
                logp = dist.log_prob(act[mb])
                ratio = torch.exp(logp - old_logp[mb])
                s1 = ratio * adv_t[mb]
                s2 = torch.clamp(ratio, 1 - self.clip, 1 + self.clip) * adv_t[mb]
                pi_loss = -torch.min(s1, s2).mean()
                v_loss = ((v - ret_t[mb]) ** 2).mean()
                ent = dist.entropy().mean()
                loss = pi_loss + 0.5 * v_loss - self.ent_coef * ent
                self.opt.zero_grad()
                loss.backward()
                nn.utils.clip_grad_norm_(self.net.parameters(), 0.5)
                self.opt.step()
        self._reset_buffers()

    def save(self, path):
        torch.save(self.net.state_dict(), path)

    def load(self, path):
        self.net.load_state_dict(torch.load(path, map_location=self.device))
