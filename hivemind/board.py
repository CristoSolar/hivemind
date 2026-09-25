from claude_agent_sdk import create_sdk_mcp_server, tool

STATUSES = {"todo": "Por hacer", "doing": "En curso", "done": "Listo"}
_STATUS_ALIASES = {"todo": "todo", "por hacer": "todo", "pendiente": "todo",
                   "doing": "doing", "en curso": "doing", "haciendo": "doing",
                   "done": "done", "listo": "done", "hecho": "done", "terminado": "done"}


def _text(message, error=False):
    out = {"content": [{"type": "text", "text": message}]}
    if error:
        out["is_error"] = True
    return out


class Board:
    def __init__(self, hub):
        self.hub = hub

    @property
    def store(self):
        return self.hub.store

    def _names(self):
        return {a["id"]: a["name"] for a in self.store.agents()}

    def _actor(self, actor):
        return "Usuario" if actor == "user" else self._names().get(actor, "?")

    def _status(self, value):
        status = _STATUS_ALIASES.get(str(value).strip().lower())
        if status is None:
            raise ValueError(f"Estado desconocido: {value}. Usa Por hacer, En curso o Listo.")
        return status

    def _assignee(self, value):
        if value in (None, ""):
            return None
        for a in self.store.agents():
            if value == a["id"] or str(value).casefold() == a["name"].casefold():
                return a["id"]
        raise ValueError(f"No hay un agente llamado {value}.")

    def _task(self, task_id):
        task = self.store.task(task_id)
        if task is None:
            raise ValueError(f"No existe la tarea {task_id}.")
        return task

    def _changed(self):
        self.hub.broadcast({"type": "tasks", "tasks": self.list()})

    def list(self, status=None):
        names = self._names()
        return [{**t, "assignee_name": names.get(t["assignee"])}
                for t in self.store.tasks(self._status(status) if status else None)]

    def create(self, title, description="", assignee=None, actor="user"):
        title = (title or "").strip()
        if not title:
            raise ValueError("La tarea necesita un título.")
        task = self.store.create_task(title, description or "", self._assignee(assignee), actor)
        self.store.add_task_log(task["id"], actor, f"{self._actor(actor)} creó la tarea")
        self._changed()
        return next(t for t in self.list() if t["id"] == task["id"])

    def update(self, task_id, actor="user", **fields):
        task = self._task(task_id)
        changes, notes = {}, []
        if "title" in fields:
            title = (fields["title"] or "").strip()
            if not title:
                raise ValueError("La tarea necesita un título.")
            changes["title"] = title
        if "description" in fields:
            changes["description"] = fields["description"] or ""
        if "status" in fields:
            changes["status"] = self._status(fields["status"])
            notes.append(f"movió la tarea a {STATUSES[changes['status']]}")
        if "assignee" in fields:
            changes["assignee"] = self._assignee(fields["assignee"])
            who = self._names().get(changes["assignee"])
            notes.append(f"asignó la tarea a {who}" if who else "dejó la tarea sin asignar")
        if not changes:
            return next(t for t in self.list() if t["id"] == task["id"])
        self.store.update_task(task_id, **changes)
        for note in notes or ["editó la tarea"]:
            self.store.add_task_log(task_id, actor, f"{self._actor(actor)} {note}")
        self._changed()
        return next(t for t in self.list() if t["id"] == task_id)

    def delete(self, task_id, actor="user"):
        self._task(task_id)
        self.store.delete_task(task_id)
        self._changed()

    def log(self, task_id):
        return self.store.task_log(task_id)

    # agent tools ------------------------------------------------------------
    def tools(self, agent_id):
        def guarded(fn):
            async def handler(args):
                try:
                    return _text(fn(args))
                except ValueError as e:
                    return _text(str(e), error=True)
            return handler

        def listar(args):
            tasks = self.list(args.get("estado"))
            if not tasks:
                return "El tablero está vacío."
            return "\n".join(f"[{t['id']}] {STATUSES[t['status']]} · {t['title']}"
                             f" · {t['assignee_name'] or 'sin asignar'}" for t in tasks)

        def crear(args):
            t = self.create(args.get("titulo"), args.get("descripcion", ""), args.get("asignado"), actor=agent_id)
            return f"Creada la tarea [{t['id']}] {t['title']}."

        def mover(args):
            t = self.update(args.get("id"), actor=agent_id, status=args.get("estado"))
            return f"[{t['id']}] ahora está en {STATUSES[t['status']]}."

        def asignar(args):
            t = self.update(args.get("id"), actor=agent_id, assignee=args.get("agente"))
            return f"[{t['id']}] asignada a {t['assignee_name'] or 'nadie'}."

        schema = lambda props, required=(): {"type": "object", "properties": props, "required": list(required)}
        s = {"type": "string"}
        return [
            tool("tablero_listar", "Lista las tareas del tablero compartido de HiveMind. Filtra por estado opcional: "
                 "Por hacer, En curso o Listo.", schema({"estado": s}))(guarded(listar)),
            tool("tablero_crear", "Crea una tarea en el tablero compartido. Asigna a un agente por su nombre si quieres.",
                 schema({"titulo": s, "descripcion": s, "asignado": s}, ["titulo"]))(guarded(crear)),
            tool("tablero_mover", "Cambia el estado de una tarea: Por hacer, En curso o Listo.",
                 schema({"id": s, "estado": s}, ["id", "estado"]))(guarded(mover)),
            tool("tablero_asignar", "Asigna una tarea a un agente por su nombre, o déjala sin asignar con agente vacío.",
                 schema({"id": s, "agente": s}, ["id"]))(guarded(asignar)),
        ]

    def mcp_server(self, agent_id):
        return create_sdk_mcp_server("tablero", tools=self.tools(agent_id))
