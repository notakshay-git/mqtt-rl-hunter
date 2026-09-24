"""amqtt broker subprocess entrypoint (amqtt needs a running loop at
construction, so the plain -m form fails)."""
import asyncio, sys, yaml
from amqtt.broker import Broker

async def main(cfg_path):
    with open(cfg_path) as f:
        cfg = yaml.safe_load(f)
    b = Broker(cfg)
    await b.start()
    print("broker ready", flush=True)
    await asyncio.Event().wait()  # run forever

if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
