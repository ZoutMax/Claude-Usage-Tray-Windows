# Claude Usage Tray (Windows)

A tiny Windows notification-area (system tray) app that shows your **Claude plan
usage limits** — the same numbers as the `/usage` screen in Claude Code (current
session, weekly all-models, weekly per-model), each with its reset countdown.

- **Tray icon**: a colored progress ring (green → amber → red) showing your
  highest utilization percentage, with the number drawn inside it.
- **Menu**: one row per usage limit with a bar, percentage and reset time, plus
  Refresh / open claude.ai usage settings / Quit.
- Reads Claude Code's own sign-in — no password, no API key to enter.

This is the Windows port of the Linux/GTK app
[**Claude-Usage-Tray**](https://github.com/ZoutMax/Claude-Usage-Tray). The
networking and parsing are the same stdlib logic; only the tray/UI layer differs
(`pystray` + `Pillow` instead of GTK/AppIndicator).

## Install

Download `ClaudeUsageTray-Setup-1.2.1.exe` from the
[latest release](https://github.com/ZoutMax/Claude-Usage-Tray-Windows/releases)
and run it. The installer:

- Bundles Python's official embeddable runtime (no packed binary, so **no antivirus
  false-positive**)
- Installs per-user to `%LOCALAPPDATA%\Programs\Claude Usage Tray` — no admin rights
- Creates a tray shortcut
- Optionally starts it automatically at login

Uninstalling removes everything, including the bundled Python and your saved
token. **Python does not need to be installed on the machine** — the installer
brings its own, inside its own folder, and takes it away again.

The ring appears in your system tray (Windows 11 tucks new icons into the `^`
overflow; drag it onto the taskbar to keep it visible).

> **No SmartScreen warning.** The installer is not code-signed, but it contains
> no packed executable — just Python and standard libraries. Scanned clean by
> Microsoft Defender.

## Run from source

```powershell
pip install -r requirements.txt
python claude_usage_tray.py            # run the tray app
python claude_usage_tray.py --dump     # print usage to the console and exit
```

Requires Python 3.9+ (`pystray`, `pillow`).

## Build the installer

```powershell
cd installer
.\build-installer.ps1
```

Requires:
- Python 3.12 on PATH (to fetch and install dependencies)
- [Inno Setup 6](https://jrsoftware.com/isinfo.php) — install with
  `winget install JRSoftware.InnoSetup`

The script:
1. Downloads Python 3.12's official embeddable runtime
2. Installs `pystray` and `pillow` into it
3. Bundles the app source and assets
4. Compiles `ClaudeUsageTray-Setup-1.2.1.exe`

Output lands in `installer\dist-installer\`. No packed binary, no antivirus
false-positive.

## Signing in — read this first

The app never asks for your password. There are two ways it gets a token, tried
in this order:

**1. Sign in from the tray (works on any machine).**
Right-click the tray icon → **"Sign in to Claude…"** and paste a token.

**Claude Code does not need to be installed on this machine.** Mint the token
once, on any machine that has an up-to-date Claude Code:

```
claude setup-token
```

Copy what it prints and paste it into the tray on whatever machine you want the
icon on. If the local `claude` is new enough the tray opens that console for
you; if it is missing or too old, it simply asks you to paste — no dead end.

The token is checked against the API before it is saved, so a mistyped one is
rejected immediately rather than silently breaking the tray. It is stored in
`%APPDATA%\ClaudeUsageTray\token.json`. **"Sign out"** removes it, and
uninstalling deletes it.

> `setup-token` is a recent Claude Code command. On an older version it will
> tell you to upgrade — do that on the machine you are minting from, not
> necessarily the one running the tray.

**2. Borrow Claude Code's sign-in (automatic).**
If you have not signed in through the tray, it reuses the OAuth token
[Claude Code](https://docs.anthropic.com/en/docs/claude-code) already stores in
`%USERPROFILE%\.claude\.credentials.json` (or `%CLAUDE_CONFIG_DIR%\.credentials.json`).
This needs nothing from you — but it only exists on a machine where Claude Code
itself is installed *and* signed in.

Either way the token goes only to `api.anthropic.com`.

### If the tray shows no numbers

Run this — it says exactly which token source was found and whether the API
accepted it:

```
claude-usage-tray --diagnose
```

It distinguishes the three cases that look identical from the tray: no token at
all, a token the API rejects (expired — sign in again), and a network/proxy
problem.

## Usage alerts

By default the tray notifies you once when a limit crosses **80%** and again at
**95%** — so you find out you are running low while you can still do something
about it, instead of when a request fails.

Each level fires **once per window**. When the session or weekly limit resets,
the warnings arm themselves again. Crossing several levels between two polls
produces one message, not a burst.

Change the levels from the tray menu (**"Alerts: 80%, 95%…"**), which opens
`%APPDATA%\ClaudeUsageTray\config.json`:

```json
{ "alert_at": [50, 75, 90] }
```

Then click **Refresh now** to apply — no restart needed. Set `"alert_at": []`
(or `false`) to switch alerts off entirely. A malformed config falls back to the
defaults rather than preventing the app from starting.

## How it works

- Polls `https://api.anthropic.com/api/oauth/usage` every 5 minutes (the same
  endpoint the `/usage` screen uses), with exponential backoff when
  rate-limited. Reset countdowns refresh locally every minute — no extra calls.
- During a transient network hiccup the last good numbers stay on screen and the
  ring greys out; a sign-in problem shows once as a tray notification.

## License

GPL-3.0, same as the original. See [LICENSE](LICENSE).
Original Linux project: https://github.com/ZoutMax/Claude-Usage-Tray
