import asyncio
import json
import os
import sys

_LINE_LIMIT = 16 * 1024 * 1024  # a pasted log must not drop the connection


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

        async def handle(req):
            try:
                result = await _dispatch(hub, req["method"], req.get("params") or {})
                send({"id": req.get("id"), "result": result})
            except Exception as e:  # report to the caller, never drop the connection
                send({"id": req.get("id"), "error": str(e) or type(e).__name__})

        hub.subscribe(on_event)
        tasks = set()
        try:
            while line := await reader.readline():
                try:
                    req = json.loads(line)
                except ValueError:
                    req = None
                if not isinstance(req, dict):
                    send({"id": None, "error": "Petición inválida"})
                    continue
                # One task per request: a slow request (delete waiting on a turn)
                # must not block approvals sent on the same connection.
                task = asyncio.create_task(handle(req))
                tasks.add(task)
                task.add_done_callback(tasks.discard)
                await writer.drain()
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        except Exception as e:
            print(f"colmena: cliente desconectado por error: {e!r}", file=sys.stderr)
        finally:
            hub.unsubscribe(on_event)
            writer.close()

    server = await asyncio.start_unix_server(client, path, limit=_LINE_LIMIT)
    os.chmod(path, 0o600)
    return server
