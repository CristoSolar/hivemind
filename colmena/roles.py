import json
import os
import sys
import tomllib
from fnmatch import fnmatch

DEFAULT_ROLES = {
    "dev.toml": '''label = "Desarrollo"
system_prompt = """Eres un agente de desarrollo dentro de Colmena. Trabajas en el repositorio de tu
directorio de trabajo. Otros agentes y el usuario comparten un chat grupal: para pedirle algo a
otro agente escribe @Nombre en tu respuesta. Responde en el idioma del usuario."""
allowed_tools = ["Read", "Grep", "Glob", "LS", "TodoWrite"]
cwd = "~/Repositorios"
''',
    "marketing.toml": '''label = "Marketing"
system_prompt = """Eres un agente de marketing dentro de Colmena. Usas los conectores de Meta Ads,
Gmail y Google Drive. Nunca envías correos, publicas anuncios ni gastas presupuesto sin que el
usuario lo apruebe. Para pedirle algo a otro agente escribe @Nombre. Responde en el idioma del usuario."""
allowed_tools = ["Read", "Grep", "Glob", "WebSearch", "WebFetch"]
cwd = "~"
''',
    "sysadmin.toml": '''label = "Sistema"
system_prompt = """Eres un agente de mantenimiento de un escritorio Omarchy (Arch Linux + Hyprland).
Explicas cada cambio antes de hacerlo. Para pedirle algo a otro agente escribe @Nombre.
Responde en el idioma del usuario."""
allowed_tools = ["Read", "Grep", "Glob", "LS"]
cwd = "~"
''',
}

_MAIN_ARG = {"Bash": "command", "Read": "file_path", "Edit": "file_path",
             "Write": "file_path", "WebFetch": "url"}


def load_roles(dir):
    dir.mkdir(parents=True, exist_ok=True)
    for name, text in DEFAULT_ROLES.items():
        if not (dir / name).exists():
            (dir / name).write_text(text)
    roles = {}
    for path in sorted(dir.glob("*.toml")):
        try:
            data = tomllib.loads(path.read_text())
        except (tomllib.TOMLDecodeError, OSError) as e:
            print(f"colmena: rol {path.name} ignorado: {e}", file=sys.stderr)
            continue
        roles[path.stem] = {
            "name": path.stem,
            "label": data.get("label", path.stem),
            "system_prompt": data.get("system_prompt", ""),
            "allowed_tools": list(data.get("allowed_tools", [])),
            "cwd": os.path.expanduser(data.get("cwd", "~")),
        }
    return roles


def permitted(tool, input, rules):
    for rule in rules:
        if rule.endswith(")") and "(" in rule:
            name, pattern = rule[:-1].split("(", 1)
            arg = input.get(_MAIN_ARG.get(tool, ""), json.dumps(input, sort_keys=True))
            if name == tool and fnmatch(str(arg), pattern):
                return True
        elif fnmatch(tool, rule):
            return True
    return False


def suggested_rule(tool, suggestions):
    for s in suggestions:
        if s.type == "addRules":
            for r in s.rules or []:
                if r.tool_name == tool:
                    return f"{tool}({r.rule_content})" if r.rule_content else tool
    return tool
