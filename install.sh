#!/usr/bin/env bash
# One-shot daylog setup: puts `dl` permanently on PATH, then offers to install
# the Claude Code hooks, launchd reminders, and the desktop widget. Safe to
# re-run — every step is idempotent (pipx upgrades in place, hooks/reminders/
# widget installers dedupe).
#
# Non-interactive mode: `./install.sh --yes` (or `-y`) accepts the
# recommended default for every prompt (hooks: yes, reminders: yes, widget:
# yes on macOS/skipped on Linux) except the unattended-Jira-MCP setting,
# which always stays off unless you answer that one yourself — it's a
# security-relevant tradeoff (unattended tool use on a timer), not a
# convenience default.
#
# What this script does NOT do (deliberately, needs a human in the loop):
#   - grant macOS Calendar access (run `dl calendar-sync` yourself once)
#   - set up the Shortcuts.app quick-entry flow (see shortcuts/README.md)
#   - enable unattended Jira/Outlook MCP pulls (security-relevant, always asked)

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

ASSUME_YES=false
for arg in "$@"; do
  case "$arg" in
    -y|--yes) ASSUME_YES=true ;;
  esac
done

IS_MACOS=false
if [[ "$(uname -s)" == "Darwin" ]]; then
  IS_MACOS=true
fi

# Prompts "$1" (message) and defaults to "y" when $ASSUME_YES is true, or
# when running non-interactively (no tty) with no explicit --yes -- avoids
# hanging forever waiting for input that will never come (e.g. piped into a
# CI runner or `curl | bash`).
confirm() {
  local prompt="$1"
  if $ASSUME_YES; then
    echo "$prompt [y/N] y  (--yes)"
    return 0
  fi
  if [[ ! -t 0 ]]; then
    echo "$prompt [y/N] n  (no tty — pass --yes to auto-confirm)"
    return 1
  fi
  local reply
  read -r -p "$prompt [y/N] " reply
  [[ "$reply" =~ ^[Yy]$ ]]
}

echo "==> Installing daylog with pipx (dl on PATH, no venv activation needed)"
if ! command -v pipx >/dev/null 2>&1; then
  if $IS_MACOS && command -v brew >/dev/null 2>&1; then
    echo "pipx not found — installing it via Homebrew..."
    brew install pipx
    pipx ensurepath
  else
    echo "pipx not found. Install it first:"
    echo "  macOS:  brew install pipx && pipx ensurepath"
    echo "  Linux:  python3 -m pip install --user pipx && python3 -m pipx ensurepath"
    exit 1
  fi
fi
pipx install -e . --force

echo
echo "==> daylog is installed. Verifying:"
hash -r 2>/dev/null || true
echo "    dl is at: $(command -v dl)"
dl day || true

echo
if confirm "Install Claude Code auto-capture hooks (patches ~/.claude/settings.json)?"; then
  python3 hooks/install_hooks.py
else
  echo "  skipped — run 'python3 hooks/install_hooks.py' later"
fi

echo
if confirm "Install the 17:45 checkpoint (calendar + GitHub PR activity, auto) + 18:00 gap-fill reminder (launchd)?"; then
  python3 reminders/install_reminders.py --load

  echo
  echo "  The 17:45 checkpoint can also pull today's Jira activity via headless"
  echo "  Claude + the Atlassian MCP connector — but with no one there to approve"
  echo "  the MCP tool prompts, it needs --dangerously-skip-permissions to do"
  echo "  anything (verified: without it, it safely does nothing and logs why)."
  echo "  This is always asked explicitly, even with --yes, since it's an"
  echo "  unattended-tool-use tradeoff, not a plain convenience default."
  read -r -p "  Enable unattended Jira pulls in the checkpoint? [y/N] " enable_jira_checkpoint
  if [[ "$enable_jira_checkpoint" =~ ^[Yy]$ ]]; then
    # Use the same python daylog itself runs under (found via dl's shebang),
    # not the system python3 — this needs PyYAML + the daylog package, which
    # only the pipx/venv interpreter is guaranteed to have.
    dl_python=$(head -1 "$(command -v dl)" | sed 's/^#!//')
    "$dl_python" -c "
import yaml
from daylog.config import CONFIG_PATH, load_config
cfg = load_config()
cfg.setdefault('checkpoint', {})['jira_skip_permissions'] = True
CONFIG_PATH.write_text(yaml.safe_dump(cfg, sort_keys=False))
print('  set checkpoint.jira_skip_permissions: true in', CONFIG_PATH)
"
  else
    echo "  left off — Jira stays manual via /daylog-backfill-jira. Flip it in"
    echo "  ~/.daylog/config.yaml (checkpoint.jira_skip_permissions) any time."
  fi
else
  echo "  skipped — run 'python3 reminders/install_reminders.py --load' later"
fi

echo
if $IS_MACOS && confirm "Install the morning-brief poller (yesterday's AI standup, delivered to Notes.app shortly after you next open your laptop)?"; then
  python3 reminders/install_reminders.py --load --morning-brief

  dl_python=$(head -1 "$(command -v dl)" | sed 's/^#!//')
  "$dl_python" -c "
import yaml
from daylog.config import CONFIG_PATH, load_config
cfg = load_config()
cfg.setdefault('morning_brief', {})['enabled'] = True
CONFIG_PATH.write_text(yaml.safe_dump(cfg, sort_keys=False))
print('  set morning_brief.enabled: true in', CONFIG_PATH)
"
  echo "  Delivers to Notes.app by default (morning_brief.delivery: notes) — run"
  echo "  'dl morning-brief' by hand once and check Notes.app to confirm it works"
  echo "  on your machine before trusting the unattended poller. Prefer email"
  echo "  instead? Set morning_brief.delivery: email and morning_brief.recipient_email"
  echo "  in ~/.daylog/config.yaml (needs the Gmail MCP connector)."
elif ! $IS_MACOS; then
  echo "  (morning-brief poller needs macOS/Notes.app — skipping)"
else
  echo "  skipped — off by default in config.yaml, run"
  echo "  'python3 reminders/install_reminders.py --load --morning-brief' and set"
  echo "  morning_brief.enabled: true in ~/.daylog/config.yaml later if you want it"
fi

echo
if ! $IS_MACOS; then
  echo "==> Desktop widget needs macOS (Übersicht) — skipping. See widget/README.md"
  echo "    if you're on a Mac elsewhere; reminders/daylog-cron.md has a Linux"
  echo "    notification equivalent for the gap-fill reminder."
elif confirm "Install the desktop widget (today's/this week's hours + AI insights + quick-log, via Übersicht)?"; then
  if ! command -v brew >/dev/null 2>&1; then
    echo "  Homebrew not found — install it from https://brew.sh, then re-run this script."
  else
    if [ ! -d "/Applications/Übersicht.app" ] && [ ! -d "$HOME/Applications/Übersicht.app" ]; then
      echo "  Installing Übersicht..."
      if ! brew install --cask ubersicht 2>/tmp/daylog-ubersicht-install.log; then
        echo "  Default install failed (likely needs admin rights) — retrying into ~/Applications..."
        brew install --cask ubersicht --appdir="$HOME/Applications"
      fi
    fi
    ./widget/install_widget.sh
    open "/Applications/Übersicht.app" 2>/dev/null || open "$HOME/Applications/Übersicht.app" 2>/dev/null || true
    echo "  If this is Übersicht's first launch, grant the Accessibility permission it asks for."
  fi
else
  echo "  skipped — see widget/README.md later"
fi

cat <<'EOF'

==> Done. Two things left, both need you (can't be scripted):
    1. Run `dl calendar-sync` once — macOS will prompt for Calendar access.
    2. Set up quick-entry via macOS Shortcuts — see shortcuts/README.md (~3 min).

Try it now:
    dl log "read the daylog README" -d 5
    dl day
EOF
