"""ONE-COMMAND validation pipeline for a results file.

  python3 repro/validate_run.py results/mqtt_comparison_seed0.json [port]

Runs the replay gate (every violation candidate re-executed on a fresh
broker) and prints the verdict summary: per agent, per violation type,
candidates vs replay-confirmed.  Only confirmed counts may be cited as
findings.  Supersedes repro/validate_violations.py (canonical probes only -
kept for history, not part of the gate).
"""
import os, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import replay_candidates as R

def main(path, port=R.PORT, cfg=R.CFG):
    if not os.path.exists(cfg):
        sys.path.insert(0, os.path.join(HERE, "..", "envs"))
        from mqtt_env import broker_config
        with open(cfg, "w") as f:
            f.write(broker_config(port))
    proc = subprocess.Popen(
        [sys.executable, os.path.join(HERE, "..", "envs", "broker_runner.py"), cfg],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        preexec_fn=os.setsid)
    import socket
    try:
        for _ in range(75):
            try:
                s = socket.create_connection(("127.0.0.1", port), timeout=0.5)
                s.close()
                break
            except OSError:
                time.sleep(0.2)
        else:
            raise RuntimeError("validation broker failed to start")
        R.main(path, port=port, cfg=cfg)
    finally:
        try:
            os.killpg(os.getpgid(proc.pid), 9)
        except Exception:
            pass

if __name__ == "__main__":
    kw = {}
    if len(sys.argv) > 2:
        kw["port"] = int(sys.argv[2])
    if len(sys.argv) > 3:
        kw["cfg"] = sys.argv[3]
    main(sys.argv[1], **kw)
