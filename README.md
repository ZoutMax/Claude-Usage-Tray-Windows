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

> **The browser/Windows may warn you — it's a false positive.** The exe isn't
> code-signed, so Chrome/Edge may flag the download as *"Virus detected"* and
> Microsoft Defender SmartScreen shows *"Windows protected your PC"*. There is no
> actual malware — Windows Defender scans the file and finds nothing; the flags
> are purely because the file is unsigned and has no download reputation yet. To
> proceed: in the browser click the download's **⋮ → Keep**, then on first run
> click **More info → Run anyway**. If you'd rather have no warnings at all, run
> [from source](#run-from-source) (needs Python) or
> [build it yourself](#build-your-own-exe).

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

Uses PyInstaller to produce a standalone `dist\ClaudeUsageTray.exe` — no Python
needed on the machine that runs it.

## Credentials — read this first

The app does **not** ask for a password or API key. It reuses the sign-in of
[Claude Code](https://docs.anthropic.com/en/docs/claude-code) (the `claude`
CLI), reading the OAuth token from `%USERPROFILE%\.claude\.credentials.json`
(or `%CLAUDE_CONFIG_DIR%\.credentials.json` if you set that variable). The token
is sent only to `api.anthropic.com`; nothing is written to disk.

If you see **"Not signed in to Claude"**, install Claude Code and run `claude`
in a terminal once to sign in. If you see **"sign-in expired"**, open Claude
Code once to refresh the token.

## How it works

- Polls `https://api.anthropic.com/api/oauth/usage` every 5 minutes (the same
  endpoint the `/usage` screen uses), with exponential backoff when
  rate-limited. Reset countdowns refresh locally every minute — no extra calls.
- During a transient network hiccup the last good numbers stay on screen and the
  ring greys out; a sign-in problem shows once as a tray notification.

## License

GPL-3.0, same as the original. See [LICENSE](LICENSE).
Original Linux project: https://github.com/ZoutMax/Claude-Usage-Tray
