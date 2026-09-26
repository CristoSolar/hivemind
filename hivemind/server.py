import asyncio
import json
import os
import sys

_LINE_LIMIT = 16 * 1024 * 1024  # a pasted log must not drop the connection


async def _dispatch(hub, method, p, client=None):
    if method == "hello":
        if client is not None:
            client.panel = p.get("role") == "panel"
        return hub.snapshot()
    if method == "history":
        return hub.store.history(p["thread"], p.get("before"), p.get("limit", 50))
    if method == "send":
        await hub.send(p["thread"], p.get("text", ""), attachments=p.get("attachments") or None)
        return True
    if method == "stop":
        await hub.stop(p["agent"])
        return True
    if method == "approve":
        hub.approve(p["approval"], p["decision"])
        return True
    if method == "create_agent":
        return hub.create_agent(p["name"], p["role"], p.get("cwd"), p.get("model"), p.get("brief", ""),
                                p.get("tint"))
    if method == "update_agent":
        changes = {k: p[k] for k in ("model", "cwd", "brief", "tint") if k in p}
        return hub.update_agent(p["agent"], **changes)
    if method == "get_settings":
        return hub.settings()
    if method == "set_settings":
        return hub.set_settings(p["auth"], p.get("api_key"))
    if method == "delete_agent":
        await hub.delete_agent(p["agent"])
        return True
    if method == "list_routines":
        return hub.routines.list()
    if method == "create_routine":
        return hub.routines.create(p["name"], p["target"], p["prompt"], p["schedule"])
    if method == "update_routine":
        fields = {k: p[k] for k in ("name", "target", "prompt", "schedule", "enabled") if k in p}
        return hub.routines.update(p["routine"], **fields)
    if method == "delete_routine":
        hub.routines.delete(p["routine"])
        return True
    if method == "run_routine_now":
        await hub.routines.run_now(p["routine"])
        return True
    if method == "skip_routine":
        hub.routines.skip(p["routine"])
        return True
    if method == "list_tasks":
        return hub.board.list(p.get("status"))
    if method == "create_task":
        return hub.board.create(p["title"], p.get("description", ""), p.get("assignee"))
    if method == "update_task":
        fields = {k: p[k] for k in ("title", "description", "status", "assignee") if k in p}
        return hub.board.update(p["task"], **fields)
    if method == "delete_task":
        hub.board.delete(p["task"])
        return True
    if method == "task_log":
        return hub.board.log(p["task"])
    if method == "list_groups":
        return hub.store.groups()
    if method == "create_group":
        return hub.create_group(p["name"], p["members"])
    if method == "update_group":
        return await hub.update_group(p["group"], p.get("name"), p.get("members"))
    if method == "delete_group":
        await hub.delete_group(p["group"])
        return True
    if method == "clear_thread":
        await hub.clear_thread(p["thread"])
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
                result = await _dispatch(hub, req["method"], req.get("params") or {}, on_event)
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
            print(f"hivemind: cliente desconectado por error: {e!r}", file=sys.stderr)
        finally:
            hub.unsubscribe(on_event)
            writer.close()

    server = await asyncio.start_unix_server(client, path, limit=_LINE_LIMIT)
    os.chmod(path, 0o600)
    return server
