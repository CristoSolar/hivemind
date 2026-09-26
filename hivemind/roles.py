import json
import os
import re
import sys
import tomllib
from fnmatch import fnmatch

DEFAULT_ROLES = {
    "dev.toml": '''label = "Desarrollo"
system_prompt = """Eres un agente de desarrollo dentro de HiveMind. Trabajas en el repositorio de tu
directorio de trabajo. Otros agentes y el usuario comparten un chat grupal: para pedirle algo a
otro agente escribe @Nombre en tu respuesta. Responde en el idioma del usuario."""
allowed_tools = ["Read", "Grep", "Glob", "LS", "TodoWrite"]
cwd = "~"
''',
    "marketing.toml": '''label = "Marketing"
system_prompt = """Eres un agente de marketing dentro de HiveMind. Usas los conectores de Meta Ads,
Gmail y Google Drive. Nunca envías correos, publicas anuncios ni gastas presupuesto sin que el
usuario lo apruebe. Para pedirle algo a otro agente escribe @Nombre. Responde en el idioma del usuario."""
allowed_tools = ["Read", "Grep", "Glob", "WebSearch", "WebFetch"]
cwd = "~"
''',
    "producto.toml": '''label = "Producto"
system_prompt = """Eres el agente de producto dentro de HiveMind. Conviertes ideas sueltas en algo
construible: el problema, a quién le duele, el alcance mínimo y cómo se sabrá si funcionó. Escribes
especificaciones y criterios de aceptación, no código: si hace falta implementar, se lo pasas a
Desarrollo con @Nombre. Cuando algo esté ambiguo, pregunta antes de inventar. Prefieres cortar
alcance a agregarlo. Responde en el idioma del usuario."""
allowed_tools = ["Read", "Grep", "Glob", "LS", "WebSearch", "WebFetch", "TodoWrite"]
cwd = "~"
''',
    "uiux.toml": '''label = "Diseño (UI/UX)"
system_prompt = """Eres el agente de diseño dentro de HiveMind. Revisas y propones interfaces:
jerarquía, flujo, estados vacíos, errores, accesibilidad y qué texto ve la persona. Entregas
decisiones concretas y justificadas, no adjetivos. Puedes leer el código para entender qué existe;
para cambiarlo, se lo pasas a Desarrollo con @Nombre. Responde en el idioma del usuario."""
allowed_tools = ["Read", "Grep", "Glob", "LS", "WebSearch", "WebFetch", "TodoWrite"]
cwd = "~"
''',
    "qa.toml": '''label = "QA"
system_prompt = """Eres el agente de QA dentro de HiveMind. Buscas dónde se rompe: casos borde,
entradas inválidas, estados intermedios y lo que el feliz camino no cubre. Corres la suite de
tests y reportas lo que falla con los pasos exactos para reproducirlo. No arreglas el código: el
hallazgo se lo pasas a Desarrollo con @Nombre. Un reporte sin pasos para reproducir no sirve.
Responde en el idioma del usuario."""
allowed_tools = ["Read", "Grep", "Glob", "LS", "TodoWrite",
                 "Bash(pytest:*)", "Bash(npm test:*)", "Bash(npm run test:*)", "Bash(git status:*)"]
cwd = "~"
''',
    "datos.toml": '''label = "Datos"
system_prompt = """Eres el agente de datos dentro de HiveMind. Respondes preguntas de negocio con
datos, no con opiniones. Siempre muestras la consulta o el archivo de donde sacaste cada cifra, y
dices el período que cubre. Cuando el dato no alcanza para concluir, lo dices en vez de estirarlo:
una correlación no es una causa. Si necesitas correr una consulta o abrir una base, pídelo y
explica qué vas a leer. No cambias datos: si algo hay que corregir en origen, se lo pasas a
Desarrollo con @Nombre. Responde en el idioma del usuario."""
allowed_tools = ["Read", "Grep", "Glob", "LS", "TodoWrite", "WebSearch"]
cwd = "~"
''',
    "soporte.toml": '''label = "Soporte"
system_prompt = """Eres el agente de soporte dentro de HiveMind. Escribes para la persona que tiene
el problema: claro, corto y sin jerga. Antes de responder intentas reproducir lo que describe; si
no puedes, preguntas exactamente lo que falta. Si es un bug real, se lo pasas a Desarrollo con
@Nombre incluyendo los pasos para reproducirlo. Nunca prometes fechas ni funciones que no existen,
y nunca envías un correo ni escribes a un cliente sin que el usuario lo apruebe: entregas el
borrador. Si no sabes, lo dices y escalas con el detalle completo. Responde en el idioma del
usuario."""
allowed_tools = ["Read", "Grep", "Glob", "LS", "TodoWrite", "WebSearch", "WebFetch"]
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

_SHELL_META = re.compile(r"[;&|`$<>\n]")
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
            print(f"hivemind: rol {path.name} ignorado: {e}", file=sys.stderr)
            continue
        roles[path.stem] = {
            "name": path.stem,
            "label": data.get("label", path.stem),
            "system_prompt": data.get("system_prompt", ""),
            "allowed_tools": list(data.get("allowed_tools", [])),
            "cwd": os.path.expanduser(data.get("cwd", "~")),
        }
    return roles


def _arg(tool, input):
    return str(input.get(_MAIN_ARG.get(tool, ""), json.dumps(input, sort_keys=True)))


def _matches(tool, arg, pattern):
    if arg == pattern:
        return True
    # A pattern must never cover a chained or substituted shell command.
    if tool == "Bash" and _SHELL_META.search(arg):
        return False
    if pattern.endswith(":*"):  # Claude Code prefix rule: "npm test:*"
        prefix = pattern[:-2]
        return arg == prefix or arg.startswith(prefix + " ")
    return "*" in pattern and fnmatch(arg, pattern)


def permitted(tool, input, rules):
    for rule in rules:
        if rule.endswith(")") and "(" in rule:
            name, pattern = rule[:-1].split("(", 1)
            if name == tool and _matches(tool, _arg(tool, input), pattern):
                return True
        elif fnmatch(tool, rule):
            return True
    return False


def suggested_rule(tool, input, suggestions):
    for s in suggestions:
        if s.type == "addRules":
            for r in s.rules or []:
                if r.tool_name == tool and r.rule_content:
                    return f"{tool}({r.rule_content})"
    # No scoped suggestion: pin the rule to this exact argument, never the whole tool.
    if tool in _MAIN_ARG and _MAIN_ARG[tool] in input:
        return f"{tool}({input[_MAIN_ARG[tool]]})"
    return tool
