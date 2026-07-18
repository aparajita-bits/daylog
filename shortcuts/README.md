# Quick-entry via macOS Shortcuts

The whole point of daylog is that logging takes under 5 seconds. A terminal
window is friction. This sets up a **Shortcuts.app shortcut** so logging is
`⌘Space` → type a shortcut name → type one line → Enter — no terminal, no
`cd`, no remembering flags.

Shortcuts you create in Shortcuts.app are automatically searchable in
Spotlight by name, and you can additionally bind any of them to a global
keyboard shortcut. Both entry points call the same `dl quicklog` command
under the hood, which is why the shorthand syntax is what makes this work:
`dl quicklog "mtg design review 45m"` or `dl quicklog "AXON-1234 fixed
pruning bug 90m"` — one string, duration/category/jira all inferred.

This part can't be scripted reliably (Shortcuts.app has no safe way to
import a hand-built `.shortcut` file from the command line), so it's a
one-time ~3 minute manual setup. Once built, it never needs touching again.

## 1. "Log Time" shortcut

1. Open **Shortcuts.app** → **+** (new shortcut).
2. Rename it to **Log Time** (top-left, click the name).
3. Add action **Ask for Input** → Input Type: **Text** → Prompt: `What were you doing?`
4. Add action **Run Shell Script**:
   - Shell: `/bin/zsh`
   - Input: **Provided Input** (this pipes the previous action's text in as `$1` if you set "Pass Input" to **as Arguments**; make sure that's selected)
   - Script:
     ```sh
     /usr/bin/env dl quicklog "$1"
     ```
   - If `dl` isn't on the PATH that Shortcuts.app sees, use the absolute path instead — find it with `which dl` in Terminal and hardcode it, e.g. `/Users/you/Downloads/daylog/.venv/bin/dl quicklog "$1"`.
5. Add action **Show Notification** → Text: `Logged`. (Optional, but confirms it worked without opening a window.)
6. Close the editor. That's it — the shortcut is saved.

**Run it:** press `⌘Space`, type `Log Time`, hit Enter, type your entry, hit Enter twice more (input, then the shell script runs). Total: under 5 seconds once you're used to it.

## 2. (Optional) bind a global keyboard shortcut

1. **System Settings → Keyboard → Keyboard Shortcuts → App Shortcuts → +**
2. Application: **Shortcuts.app** (or "All Applications" if you want it to work everywhere)
3. Menu Title: must exactly match the shortcut name, **Log Time**
4. Keyboard Shortcut: e.g. `⌃⌥⌘L`

Now that key combo opens the same quick-entry prompt from anywhere, no Spotlight step needed.

## 3. Optional companion shortcuts

Repeat the same pattern for:

- **Fill Gaps** — Run Shell Script: `osascript -e 'tell application "Terminal" to do script "dl fill"'` (gap-filling needs a real terminal since it's interactive prompt-by-prompt; this just opens one for you).
- **Standup** — Run Shell Script: `/usr/bin/env dl standup | pbcopy` then **Show Notification** "Standup copied to clipboard" — copy-paste ready standup in one keystroke.

## Why not a native .shortcut file you can just double-click?

`.shortcut` files are a binary/plist format that Shortcuts.app itself
generates; there's no supported way to hand-author one from a script and
guarantee it imports cleanly. Building it wrong would mean shipping
something that silently fails to import — worse than a 3-minute manual
setup that's guaranteed to work. If you'd rather script it, the
[`shortcuts` CLI](https://developer.apple.com/documentation/shortcuts) can
run and export *existing* shortcuts, but not construct new ones from a
JSON/YAML spec.
