#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v claude >/dev/null; then
  echo "Falta 'claude' en el PATH. Instala Claude Code e inicia sesión primero." >&2
  exit 1
fi

VENV="$HOME/.local/share/colmena/venv"
python -m venv --system-site-packages "$VENV"
# Build outside /tmp: on small machines /tmp is RAM.
mkdir -p "$HOME/.cache/tmp"
TMPDIR="$HOME/.cache/tmp" "$VENV/bin/pip" install -q --upgrade .

mkdir -p "$HOME/.local/bin" "$HOME/.config/systemd/user" "$HOME/.local/share/applications"
ln -sf "$VENV/bin/colmena" "$HOME/.local/bin/colmena"
# The service needs to find the claude CLI; bake the current location into its PATH.
sed "s|Environment=PATH=|Environment=PATH=$(dirname "$(command -v claude)"):|" data/colmena.service \
  > "$HOME/.config/systemd/user/colmena.service"
cp data/colmena.desktop "$HOME/.local/share/applications/"
ICON_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"
mkdir -p "$ICON_DIR"
cp colmena/ui/icons/colmena.svg "$ICON_DIR/com.gogema.Colmena.svg"
gtk-update-icon-cache -q -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true

systemctl --user daemon-reload
systemctl --user enable --now colmena
systemctl --user restart colmena
echo "Listo. Abre Colmena desde el menú de apps (Super+Space) o con: colmena"
