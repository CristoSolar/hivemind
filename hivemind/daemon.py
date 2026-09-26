import asyncio
import sys

from hivemind import paths
from hivemind.hub import Hub
from hivemind.roles import load_roles
from hivemind.server import serve
from hivemind.store import Store


async def _main():
    paths.data_dir().mkdir(parents=True, exist_ok=True)
    store = Store(str(paths.data_dir() / "hivemind.db"))
    hub = Hub(store, load_roles(paths.config_dir() / "roles"), config=paths.load_config())
    hub.expire_stale_approvals()
    hub.routines.notify_pending()
    server = await serve(hub, str(paths.socket_path()))
    print(f"hivemind-daemon escuchando en {paths.socket_path()}", flush=True)
    async with server:
        beat = 0
        while True:
            await asyncio.sleep(5)
            await hub.sample_memory()
            beat += 1
            if beat % 6 == 0:  # every 30 s
                try:
                    await hub.routines.tick()
                except Exception as e:  # one bad routine must not stop the daemon
                    print(f"hivemind: rutinas fallaron: {e!r}", file=sys.stderr, flush=True)


def main():
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        pass
