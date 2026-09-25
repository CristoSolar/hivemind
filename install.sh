#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v claude >/dev/null; then
  echo "Falta 'claude' en el PATH. Instala Claude Code e inicia sesión primero." >&2
  exit 1
fi

DATA="$HOME/.local/share/hivemind"
CONFIG="$HOME/.config/hivemind"

# Migrate from the app's old name (Colmena). Copy, never move: the old folders stay as a
# backup until the user deletes them. Safe to re-run: skipped once the new folders exist.
OLD_DATA="$HOME/.local/share/colmena"
OLD_CONFIG="$HOME/.config/colmena"
if [[ -f $OLD_DATA/colmena.db && ! -e $DATA/hivemind.db ]]; then
  echo "Migrando datos de Colmena a HiveMind…"
  mkdir -p "$DATA"
  # Stop the old daemon first so the database copy is consistent.
  systemctl --user stop colmena 2>/dev/null || true
  cp -a "$OLD_DATA/colmena.db" "$DATA/hivemind.db"
fi
if [[ -d $OLD_CONFIG && ! -e $CONFIG ]]; then
  cp -a "$OLD_CONFIG" "$CONFIG"
  sed -i 's/Colmena/HiveMind/g' "$CONFIG"/roles/*.toml 2>/dev/null || true
fi

VENV="$DATA/venv"
python -m venv --system-site-packages "$VENV"
# Build outside /tmp: on small machines /tmp is RAM.
mkdir -p "$HOME/.cache/tmp"
TMPDIR="$HOME/.cache/tmp" "$VENV/bin/pip" install -q --upgrade .

mkdir -p "$HOME/.local/bin" "$HOME/.config/systemd/user" "$HOME/.local/share/applications"
ln -sf "$VENV/bin/hivemind" "$HOME/.local/bin/hivemind"
# The service needs to find the claude CLI; bake the current location into its PATH.
sed "s|Environment=PATH=|Environment=PATH=$(dirname "$(command -v claude)"):|" data/hivemind.service \
  > "$HOME/.config/systemd/user/hivemind.service"
cp data/hivemind.desktop "$HOME/.local/share/applications/"
ICON_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"
mkdir -p "$ICON_DIR"
cp hivemind/ui/icons/hivemind.svg "$ICON_DIR/com.gogema.HiveMind.svg"
gtk-update-icon-cache -q -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true

systemctl --user daemon-reload
systemctl --user enable --now hivemind
systemctl --user restart hivemind

# Retire the old install only once the new daemon answers. Its data folders are kept.
SOCK="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/hivemind.sock"
for _ in $(seq 20); do [[ -S $SOCK ]] && break; sleep 0.5; done
if [[ -S $SOCK && -e $HOME/.config/systemd/user/colmena.service ]]; then
  systemctl --user disable --now colmena 2>/dev/null || true
  rm -f "$HOME/.config/systemd/user/colmena.service" "$HOME/.local/share/applications/colmena.desktop" \
        "$HOME/.local/share/icons/hicolor/scalable/apps/com.gogema.Colmena.svg" "$HOME/.local/bin/colmena"
  rm -rf "$OLD_DATA/venv"
  systemctl --user daemon-reload
  gtk-update-icon-cache -q -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
  echo "Colmena retirada. Tus datos viejos quedan de respaldo en $OLD_DATA y $OLD_CONFIG."
fi
echo "Listo. Abre HiveMind desde el menú de apps (Super+Space) o con: hivemind"
