#!/usr/bin/env bash
# Renders daylog.widget/index.jsx.template (substituting the resolved `dl`
# path) and writes it into Übersicht's widgets folder. Übersicht hot-reloads
# on file change, so it should appear on your desktop within a few seconds
# of running this (with Übersicht open).
#
# Safe to re-run any time (e.g. after `dl` moves) — it just overwrites the
# rendered copy.

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

WIDGETS_DIR="$HOME/Library/Application Support/Übersicht/widgets"
DEST="$WIDGETS_DIR/daylog.widget"

if [ ! -d "/Applications/Übersicht.app" ] && [ ! -d "$HOME/Applications/Übersicht.app" ]; then
  echo "Übersicht.app not found in /Applications or ~/Applications."
  echo "Install it first: brew install --cask ubersicht"
  echo "(no admin rights? use: brew install --cask ubersicht --appdir=~/Applications)"
  exit 1
fi

DL_PATH="$(command -v dl || true)"
if [ -z "$DL_PATH" ]; then
  echo "\`dl\` not found on PATH — run ./install.sh from the daylog repo root first."
  exit 1
fi

mkdir -p "$DEST"
sed "s#{{DL_PATH}}#$DL_PATH#g" daylog.widget/index.jsx.template > "$DEST/index.jsx"

echo "wrote $DEST/index.jsx (using dl at $DL_PATH)"
echo
echo "If Übersicht isn't running yet, open it once (⌘Space, type Übersicht)."
echo "It grants Accessibility permission on first launch and shows the widget"
echo "on your desktop within a few seconds — no restart needed after that."
echo
echo "To reposition/restyle: edit the 'left'/'top' values in the className"
echo "at $DEST/index.jsx (Übersicht hot-reloads on save)."
