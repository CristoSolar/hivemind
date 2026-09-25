import asyncio

from colmena import paths
from colmena.hub import Hub
from colmena.roles import load_roles
from colmena.server import serve
from colmena.store import Store


async def _main():
    paths.data_dir().mkdir(parents=True, exist_ok=True)
    store = Store(str(paths.data_dir() / "colmena.db"))
    hub = Hub(store, load_roles(paths.config_dir() / "roles"), config=paths.load_config())
    hub.expire_stale_approvals()
    server = await serve(hub, str(paths.socket_path()))
    print(f"colmena-daemon escuchando en {paths.socket_path()}", flush=True)
    async with server:
        while True:
            await asyncio.sleep(5)
            await hub.sample_memory()


def main():
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        pass
