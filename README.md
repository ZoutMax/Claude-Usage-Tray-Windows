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

## Install (prebuilt exe)

Download `ClaudeUsageTray.exe` from the
[latest release](https://github.com/ZoutMax/Claude-Usage-Tray-Windows/releases)
and double-click it — the ring appears in your system tray (Windows 11 tucks new
icons into the `^` overflow; drag it onto the taskbar to keep it visible).

> **First run: SmartScreen may warn you.** The exe isn't code-signed, so Microsoft
> Defender SmartScreen may show *"Windows protected your PC"* — click **More info
> → Run anyway**. There's no malware; the app is just the Python script in this
> repo, compiled to a native exe with [Nuitka](https://nuitka.net). (Prefer no
> prompt at all? Run [from source](#run-from-source) or
> [build it yourself](#build-your-own-exe).)

To have it start automatically at login, run once in PowerShell:

```powershell
.\install.ps1
```

That copies the exe to `%LOCALAPPDATA%\ClaudeUsageTray`, registers it under the
per-user *Run* key, and launches it. Remove it with `.\uninstall.ps1`.

## Run from source

```powershell
pip install -r requirements.txt
python claude_usage_tray.py            # run the tray app
python claude_usage_tray.py --dump     # print usage to the console and exit
```

Requires Python 3.9+ (`pystray`, `pillow`).

## Build your own exe

```powershell
.\build.ps1
```

Uses [Nuitka](https://nuitka.net) to compile a standalone native
`dist\ClaudeUsageTray.exe` — no Python needed on the machine that runs it. (The
first build downloads a MinGW64 toolchain and takes a few minutes. Native
compilation is deliberate: it avoids the antivirus "Virus detected" false-positive
that PyInstaller one-file exes trigger.)

## Signing in — read this first

The app never asks for your password. There are two ways it gets a token, tried
in this order:

**1. Sign in from the tray (works on any machine).**
Right-click the tray icon → **"Sign in to Claude…"**. If the `claude` CLI is
installed it opens a console running `claude setup-token`; complete the browser
step, copy the token it prints, and paste it into the box. The token is checked
against the API before it is saved, so a mistyped one is rejected immediately
rather than silently breaking the tray. It is stored in
`%APPDATA%\ClaudeUsageTray\token.json`. **"Sign out"** removes it.

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

## How it works

- Polls `https://api.anthropic.com/api/oauth/usage` every 5 minutes (the same
  endpoint the `/usage` screen uses), with exponential backoff when
  rate-limited. Reset countdowns refresh locally every minute — no extra calls.
- During a transient network hiccup the last good numbers stay on screen and the
  ring greys out; a sign-in problem shows once as a tray notification.

## License

GPL-3.0, same as the original. See [LICENSE](LICENSE).
Original Linux project: https://github.com/ZoutMax/Claude-Usage-Tray
