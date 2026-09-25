import asyncio
import json
import os
import sys


async def _dispatch(hub, method, p):
    if method == "hello":
        return hub.snapshot()
    if method == "history":
        return hub.store.history(p["thread"], p.get("before"), p.get("limit", 50))
    if method == "send":
        await hub.send(p["thread"], p["text"])
        return True
    if method == "stop":
        await hub.stop(p["agent"])
        return True
    if method == "approve":
        hub.approve(p["approval"], p["decision"])
        return True
    if method == "create_agent":
        return hub.create_agent(p["name"], p["role"], p.get("cwd"))
    if method == "delete_agent":
        await hub.delete_agent(p["agent"])
        return True
    raise ValueError(f"Método desconocido: {method}")


async def serve(hub, path):
    if os.path.exists(path):
        os.unlink(path)

    async def client(reader, writer):
        def send(obj):
            if not writer.is_closing():
                writer.write((json.dumps(obj, ensure_ascii=False) + "\n").encode())

        def on_event(ev):
            send({"event": ev})

        hub.subscribe(on_event)
        try:
            while line := await reader.readline():
                try:
                    req = json.loads(line)
                except ValueError:
                    send({"id": None, "error": "JSON inválido"})
                    continue
                try:
                    result = await _dispatch(hub, req["method"], req.get("params") or {})
                    send({"id": req.get("id"), "result": result})
                except (ValueError, KeyError, TypeError) as e:
                    send({"id": req.get("id"), "error": str(e)})
                await writer.drain()
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        except Exception as e:
            print(f"colmena: cliente desconectado por error: {e!r}", file=sys.stderr)
        finally:
            hub.unsubscribe(on_event)
            writer.close()

    server = await asyncio.start_unix_server(client, path)
    os.chmod(path, 0o600)
    return server
