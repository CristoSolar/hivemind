# Colmena

Agentes de Claude Code en equipo, para Omarchy. Cada agente tiene un rol y su propio chat,
comparten un chat grupal donde se pasan trabajo con `@Nombre`, y piden permiso antes de
hacer algo delicado. Siguen trabajando aunque cierres la ventana.

## Instalar como plugin de Omarchy

```bash
omarchy plugin add https://github.com/<tu-usuario>/colmena --enable
```

Aparece una abejita en la barra. El primer clic ofrece «Instalar Colmena» (app, servicio de
usuario y atajo en el menú). Después, la abejita muestra cuántos agentes trabajan y se pone
amarilla con «!» cuando alguno espera tu aprobación: puedes aprobar desde ahí mismo. Clic
del medio abre la ventana.

## Requisitos

- Omarchy (x86_64 o aarch64) con `gtk4`, `libadwaita` y `python-gobject` (vienen con Omarchy).
- Claude Code instalado y con sesión iniciada (`claude`).

## Instalar

```bash
./install.sh
```

Atajo sugerido en `~/.config/hypr/bindings.conf`:

```
bindd = SUPER SHIFT, A, Colmena, exec, colmena
```

## Configurar

- Roles: `~/.config/colmena/roles/*.toml` (`label`, `system_prompt`, `allowed_tools`, `cwd`).
  `allowed_tools` acepta `Read`, comodines como `mcp__claude_ai_Gmail__*`, o `Bash(git status:*)` (prefijo; nunca cubre comandos encadenados con `;`, `&&` o `|`).
- `~/.config/colmena/config.toml`: `max_running = 3` fija el máximo de agentes trabajando a la vez
  (por defecto se calcula con la RAM libre); `model = "sonnet"` fija el modelo.

## Logs

```bash
journalctl --user -u colmena -f
```

## Tests

```bash
python -m venv --system-site-packages .venv && .venv/bin/pip install -e .
.venv/bin/python -m unittest discover -s tests -t .
```
