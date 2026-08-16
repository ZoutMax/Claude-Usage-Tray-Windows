#!/usr/bin/env python3
"""Claude usage in the Windows system tray (notification area).

Shows the same numbers as Claude Code's /usage screen: a progress-ring icon
with the highest utilization percentage, and a menu with every usage bucket
(current session, weekly all-models, weekly per-model) and its reset time.

Data source: the OAuth token Claude Code stores in ~/.claude/.credentials.json
is used to poll https://api.anthropic.com/api/oauth/usage every 5 minutes,
with exponential backoff when the endpoint rate-limits. The token is only ever
sent to Anthropic; nothing is written to disk. Reset countdowns in the menu are
refreshed locally every minute.

This is the Windows port of https://github.com/ZoutMax/Claude-Usage-Tray
(the GTK/AppIndicator Linux original). The networking and parsing below are the
stdlib-only logic from that project; only the tray/UI layer differs.

Dependencies:
    pip install pystray pillow

Usage:
    python claude_usage_tray.py           # run the tray app
    python claude_usage_tray.py --dump    # print usage to stdout and exit
"""

import json
import math
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

APP_ID = "claude-usage-tray"
APP_NAME = "Claude Usage Tray"
VERSION = "1.2.1"
PROJECT_URL = "https://github.com/ZoutMax/Claude-Usage-Tray-Windows"


def credentials_path():
    """Claude Code's credentials file, honoring CLAUDE_CONFIG_DIR."""
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR")
    if config_dir:
        return Path(config_dir).expanduser() / ".credentials.json"
    return Path.home() / ".claude" / ".credentials.json"


CREDENTIALS_FILE = credentials_path()


def token_store_path():
    """Where the tray keeps a token the user signed in with directly.

    Claude Code's credentials are only present on a machine where Claude Code
    itself is installed and signed in. On any other machine there is nothing to
    read, which is exactly why the tray appeared to be "not communicating" -
    it had no token at all. A token saved here makes the tray self-sufficient.
    """
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / "ClaudeUsageTray" / "token.json"


TOKEN_FILE = token_store_path()
CONFIG_FILE = TOKEN_FILE.with_name("config.json")
USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
POLL_SECONDS = 300  # normal poll interval
DEFAULT_ALERTS = [80, 95]  # percentages worth interrupting someone for
FAIL_RETRY_SECONDS = 60  # first retry delay after a failure
FAIL_RETRY_MAX = 900  # backoff cap
AUTH_RETRY_SECONDS = 30  # re-check after a sign-in problem (no backoff)

KIND_LABELS = {
    "session": "Session",
    "weekly_all": "Week . all models",
}
BUCKET_ORDER = ["five_hour", "seven_day"]
BUCKET_LABELS = {
    "five_hour": "Session",
    "seven_day": "Week . all models",
    "seven_day_opus": "Week . Opus",
    "seven_day_sonnet": "Week . Sonnet",
    "seven_day_fable": "Week . Fable",
    "seven_day_oauth_apps": "Week . OAuth apps",
}


class UsageError(Exception):
    """A problem we can explain to the user in the menu."""

    retry_after = 0  # seconds the server asked us to wait, if any
    kind = ""  # "auth" for sign-in problems the user must fix themselves


def auth_error(message):
    err = UsageError(message)
    err.kind = "auth"
    return err


SIGN_IN_HINT = 'use "Sign in to Claude…" in this menu'


def read_json_file(path):
    """Read a JSON config written by anyone.

    Always decode as UTF-8 and tolerate a BOM: read_text() would otherwise use
    the locale codepage, and a file saved by PowerShell (Set-Content -Encoding
    utf8 emits a BOM) then fails to parse and looks like "no token at all".
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def load_alert_levels():
    """Percentages at which to warn, from config.json.

    A tray that only shows numbers is a tray you have to remember to look at.
    Anything malformed falls back to the defaults rather than stopping the app
    from starting - a bad config should never cost you the usage display.
    """
    try:
        data = read_json_file(CONFIG_FILE)
    except (FileNotFoundError, OSError, UnicodeDecodeError, json.JSONDecodeError):
        return list(DEFAULT_ALERTS)
    raw = (data or {}).get("alert_at", DEFAULT_ALERTS)
    if raw in (None, False):
        return []                       # explicitly opted out of alerts
    try:
        levels = sorted({int(v) for v in raw if 0 < int(v) <= 100})
    except (TypeError, ValueError):
        return list(DEFAULT_ALERTS)
    return levels or []


def read_saved_token():
    """A token the user pasted into the tray, if any."""
    try:
        data = read_json_file(TOKEN_FILE)
    except (FileNotFoundError, OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    token = (data or {}).get("accessToken")
    return (token, data.get("subscriptionType")) if token else None


def save_token(token, plan=None):
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(
        json.dumps({"accessToken": token, "subscriptionType": plan}), encoding="utf-8"
    )
    try:  # keep it readable only by this user
        os.chmod(TOKEN_FILE, 0o600)
    except OSError:
        pass


def clear_token():
    try:
        TOKEN_FILE.unlink()
    except FileNotFoundError:
        pass


def read_claude_code_token():
    """The OAuth token Claude Code stores, when Claude Code is installed here."""
    try:
        data = read_json_file(CREDENTIALS_FILE)
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UsageError(f"Cannot read credentials: {exc}")
    oauth = data.get("claudeAiOauth") or data
    token = oauth.get("accessToken")
    return (token, oauth.get("subscriptionType")) if token else None


def read_access_token():
    """Prefer a token signed in through the tray, else borrow Claude Code's.

    A locally-expired-looking token is not treated as fatal: Claude Code
    refreshes its own in the background, the stored expiry can lag, and clock
    skew makes the local check unreliable. Send it and let the server decide -
    a real 401/403 surfaces as an auth error further down.
    """
    saved = read_saved_token()
    if saved:
        return saved
    borrowed = read_claude_code_token()
    if borrowed:
        return borrowed
    raise auth_error(f"Not signed in to Claude - {SIGN_IN_HINT}")


def claude_cli():
    """Locate the Claude Code CLI, if it is installed."""
    for candidate in ("claude.cmd", "claude.exe", "claude"):
        found = shutil.which(candidate)
        if found:
            return found
    local = Path.home() / ".local" / "bin" / "claude.exe"
    return str(local) if local.exists() else None


def ask_for_token(prompt=None):
    """Prompt for a token.

    The installer ships Python's *embeddable* runtime, which has no tkinter, so
    a Tk dialog would crash for installed users. PowerShell's InputBox is
    always present on Windows and needs nothing bundled.
    """
    prompt = prompt or "Paste your Claude token."
    # InputBox takes a single-quoted PowerShell string; double any quote in the
    # text so a stray apostrophe cannot break out of it.
    safe = prompt.replace("'", "''").replace("\n", "`n")
    script = (
        "Add-Type -AssemblyName Microsoft.VisualBasic;"
        "[Microsoft.VisualBasic.Interaction]::InputBox("
        f"'{safe}',"
        "'Claude Usage Tray - Sign in','')"
    )
    try:
        done = subprocess.run(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", script],
            capture_output=True, text=True, timeout=600,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return (done.stdout or "").strip() or None


def cli_has_setup_token():
    """Whether the installed Claude Code is new enough to mint a token.

    `setup-token` was added in a later release. Launching it blindly on an older
    CLI drops the user into a console telling them to upgrade, with no way
    forward from the tray - so ask first and route around it.
    """
    cli = claude_cli()
    if not cli:
        return False
    try:
        done = subprocess.run(
            [cli, "--help"], capture_output=True, text=True, timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return "setup-token" in ((done.stdout or "") + (done.stderr or ""))


def run_setup_token():
    """Open a console running `claude setup-token` so the user can mint one."""
    cli = claude_cli()
    if not cli:
        return False
    try:
        subprocess.Popen(f'start "Claude sign-in" cmd /k "{cli}" setup-token', shell=True)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def validate_token(token):
    """Confirm a token works before saving it, so a typo can't silently break the tray."""
    request = urllib.request.Request(
        USAGE_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "anthropic-beta": "oauth-2025-04-20",
            "Accept": "application/json",
            "User-Agent": APP_ID,
        },
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        payload = json.load(response)
    return payload


def fetch_usage():
    token, plan = read_access_token()
    request = urllib.request.Request(
        USAGE_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "anthropic-beta": "oauth-2025-04-20",
            "Accept": "application/json",
            "User-Agent": APP_ID,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise auth_error(
                "Claude sign-in expired - run `claude` once to refresh "
                "(this updates automatically)"
            )
        if exc.code == 429:
            err = UsageError("Rate limited - retrying automatically")
            try:
                err.retry_after = int(exc.headers.get("Retry-After") or 0)
            except (TypeError, ValueError):
                pass
            raise err
        detail = ""
        try:
            detail = json.load(exc).get("error", {}).get("message", "")
        except Exception:
            pass
        raise UsageError(f"API error: HTTP {exc.code}" + (f" - {detail}" if detail else ""))
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise UsageError(f"Network error: {getattr(exc, 'reason', exc)}")
    except json.JSONDecodeError:
        raise UsageError("Unexpected response from usage API")
    return parse_buckets(payload), plan


def parse_limits(limits):
    """Parse the newer `limits` array (what the /usage screen renders)."""
    buckets = []
    if not isinstance(limits, list):
        return buckets
    for entry in limits:
        if not isinstance(entry, dict) or entry.get("percent") is None:
            continue
        try:
            pct = float(entry["percent"])
        except (TypeError, ValueError):
            continue
        kind = entry.get("kind") or ""
        label = KIND_LABELS.get(kind)
        if label is None:
            scope = entry.get("scope") or {}
            model = (scope.get("model") or {}).get("display_name")
            if model:
                label = f"Week . {model}" if entry.get("group") == "weekly" else model
            else:
                label = kind.replace("_", " ").title() or "Other"
        buckets.append(
            {
                "key": kind,
                "label": label,
                "pct": pct,
                "resets_at": parse_time(entry.get("resets_at")),
            }
        )
    return buckets


def parse_buckets(payload):
    buckets = parse_limits(payload.get("limits"))
    if buckets:
        return buckets
    # Legacy shape: top-level five_hour / seven_day / seven_day_<model> buckets.
    for key, value in payload.items():
        if not isinstance(value, dict) or value.get("utilization") is None:
            continue
        try:
            pct = float(value["utilization"])
        except (TypeError, ValueError):
            continue
        label = BUCKET_LABELS.get(key) or (
            "Week . " + key.removeprefix("seven_day_").replace("_", " ").title()
        )
        buckets.append(
            {
                "key": key,
                "label": label,
                "pct": pct,
                "resets_at": parse_time(value.get("resets_at")),
            }
        )

    def order(bucket):
        try:
            return (0, BUCKET_ORDER.index(bucket["key"]))
        except ValueError:
            return (1, bucket["key"])

    buckets.sort(key=order)
    if not buckets:
        raise UsageError("No usage buckets in API response")
    return buckets


def parse_time(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def reset_text(when):
    if when is None:
        return ""
    seconds = (when - datetime.now(timezone.utc)).total_seconds()
    if seconds <= 0:
        return "resets soon"
    minutes = int(seconds // 60)
    days, rem = divmod(minutes, 1440)
    hours, mins = divmod(rem, 60)
    if days:
        return f"resets in {days}d {hours}h"
    if hours:
        return f"resets in {hours}h {mins:02d}m"
    return f"resets in {mins}m"


def bar_text(pct):
    filled = min(10, max(0, round(pct / 10)))
    return "█" * filled + "░" * (10 - filled)


def usage_color(pct):
    if pct >= 85:
        return (229, 72, 77)  # red
    if pct >= 60:
        return (240, 160, 0)  # amber
    return (70, 167, 88)  # green


# --------------------------------------------------------------------------
# Windows tray UI (pystray + Pillow)
# --------------------------------------------------------------------------

def make_icon_image(pct, error=False, stale=False, size=64):
    """Render a progress-ring PIL image for the tray icon."""
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    if error:
        color = (143, 143, 143)
        text = "!"
        fraction = 1.0
    else:
        pct = min(100.0, max(0.0, pct))
        color = (158, 158, 158) if stale else usage_color(pct)
        text = f"{pct:.0f}"
        fraction = max(0.04, pct / 100.0)

    # Thin ring hugging the outer edge, so the big number in the middle stays
    # legible at tiny tray sizes (16-24 px).
    pad = max(2, size // 20)
    box = [pad, pad, size - pad, size - pad]
    width = max(2, size // 16)

    # background track ring
    draw.arc(box, 0, 360, fill=(128, 128, 128, 90), width=width)
    # foreground progress arc, starting at top (12 o'clock), clockwise
    start = -90
    end = start + fraction * 360
    draw.arc(box, start, end, fill=color + (255,), width=width)

    # centered percentage text, as large as will fit inside the ring
    scale_by_len = {1: 0.78, 2: 0.66, 3: 0.50}.get(len(text), 0.50)
    try:
        font = ImageFont.truetype("arialbd.ttf", int(size * scale_by_len))
    except Exception:
        try:
            font = ImageFont.truetype("arial.ttf", int(size * scale_by_len))
        except Exception:
            font = ImageFont.load_default()
    tb = draw.textbbox((0, 0), text, font=font)
    tw, th = tb[2] - tb[0], tb[3] - tb[1]
    draw.text(
        ((size - tw) / 2 - tb[0], (size - th) / 2 - tb[1]),
        text,
        fill=color + (255,),
        font=font,
    )
    return img


class TrayApp:
    def __init__(self):
        import pystray

        self.pystray = pystray
        self.last = None  # last successful (buckets, plan)
        self.current = (None, None, None)  # (buckets, plan, notice) shown now
        self.message = "Loading…"
        self.plan = None
        self.fail_delay = FAIL_RETRY_SECONDS
        self.notified_auth = False
        self.wake = threading.Event()  # forces an immediate re-poll
        self.stopping = threading.Event()
        self.alert_levels = load_alert_levels()
        # {bucket label: (resets_at, {levels already announced})} - see _check_alerts
        self.alerted = {}

        self.icon = pystray.Icon(
            APP_ID,
            icon=make_icon_image(0),
            title=APP_NAME,
            menu=pystray.Menu(self._menu_items),
        )

    # -- menu -------------------------------------------------------------
    def _menu_items(self):
        item = self.pystray.MenuItem
        Menu = self.pystray.Menu
        buckets, plan, notice = self.current
        title = "Claude usage" + (f" - {plan} plan" if plan else "")
        yield item(title, None, enabled=False)
        yield Menu.SEPARATOR
        if buckets:
            for bucket in buckets:
                line = f"{bucket['label']}   {bar_text(bucket['pct'])}  {bucket['pct']:.0f}%"
                resets = reset_text(bucket["resets_at"])
                if resets:
                    line += f"   .   {resets}"
                yield item(line, None, enabled=False)
        else:
            yield item(self.message or "…", None, enabled=False)
        if notice:
            yield item(notice, None, enabled=False)
        yield Menu.SEPARATOR
        yield item("Refresh now", self._on_refresh)
        yield item("Sign in to Claude…", self._on_sign_in)
        if read_saved_token():
            yield item("Sign out", self._on_sign_out)
        levels = ", ".join(f"{lv}%" for lv in self.alert_levels) or "off"
        yield item(f"Alerts: {levels}…", self._on_edit_alerts)
        yield item(
            "Open claude.ai usage settings",
            lambda icon, it: webbrowser.open("https://claude.ai/settings/usage"),
        )
        if not buckets or notice:
            yield item(
                "Setup help (GitHub)",
                lambda icon, it: webbrowser.open(PROJECT_URL),
            )
        yield Menu.SEPARATOR
        yield item("Quit", self._on_quit)

    # -- sign-in ----------------------------------------------------------
    def _on_sign_in(self, icon, item):
        # Run off the menu thread: minting a token involves a browser round
        # trip, and blocking here would freeze the tray.
        threading.Thread(target=self._sign_in_flow, daemon=True).start()

    def _sign_in_flow(self):
        # Only launch the CLI when it can actually mint a token. An older Claude
        # Code opens a console that just says "upgrade", which is a dead end.
        if cli_has_setup_token():
            run_setup_token()
            prompt = ("A console is running 'claude setup-token'.\n"
                      "Complete it, then paste the token it prints below.")
        else:
            prompt = (
                "Paste your Claude token below.\n\n"
                "To get one, run this on ANY machine with an up-to-date\n"
                "Claude Code installed - it does not have to be this one:\n\n"
                "    claude setup-token\n\n"
                "Copy what it prints and paste it here."
            )
        token = ask_for_token(prompt)
        if not token:
            return                     # cancelled
        try:
            payload = validate_token(token)
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                self._notify("That token was rejected - please try again")
            else:
                self._notify(f"Could not verify token (HTTP {exc.code})")
            return
        except Exception as exc:       # network, parse, anything else
            self._notify(f"Could not verify token: {exc}")
            return
        plan = None
        if isinstance(payload, dict):
            plan = payload.get("subscription_type") or payload.get("subscriptionType")
        save_token(token, plan)
        self._notify("Signed in - reading your usage now")
        self.wake.set()

    def _on_sign_out(self, icon, item):
        clear_token()
        self._notify("Signed out of the tray's own token")
        self.wake.set()

    def _on_edit_alerts(self, icon, item):
        """Open config.json, creating a commented default if it isn't there yet.

        Writing the file first means the menu entry always opens something
        editable, rather than Notepad's "cannot find the file" dialog.
        """
        try:
            if not CONFIG_FILE.exists():
                CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
                CONFIG_FILE.write_text(
                    json.dumps({"alert_at": self.alert_levels or DEFAULT_ALERTS}, indent=2),
                    encoding="utf-8",
                )
            subprocess.Popen(["notepad.exe", str(CONFIG_FILE)])
            self._notify("Edit alert_at, then use Refresh now to apply")
        except (OSError, subprocess.SubprocessError) as exc:
            self._notify(f"Could not open settings: {exc}")

    def _on_refresh(self, icon, item):
        # Re-read config here too, so editing alert_at takes effect without a
        # restart - the menu entry above tells the user to do exactly this.
        self.alert_levels = load_alert_levels()
        self.wake.set()

    def _on_quit(self, icon, item):
        self.stopping.set()
        self.wake.set()
        self.icon.stop()

    # -- threshold alerts --------------------------------------------------
    def _check_alerts(self, buckets):
        """Warn once when a limit crosses a threshold.

        Keyed on the bucket's reset time as well as its name: when a window
        rolls over, the key changes and the bucket becomes eligible to warn
        again. Without that it would either warn every poll (every 5 minutes,
        which trains you to ignore it) or warn once and stay silent for good.
        Only the highest newly-crossed level is announced, so passing 80 and 95
        between two polls yields one message rather than two.
        """
        if not self.alert_levels:
            return
        for bucket in buckets:
            label, pct = bucket["label"], bucket["pct"]
            resets = str(bucket.get("resets_at"))
            seen_resets, seen_levels = self.alerted.get(label, (None, set()))
            if seen_resets != resets:                 # new window: start clean
                seen_levels = set()
            crossed = [lv for lv in self.alert_levels if pct >= lv and lv not in seen_levels]
            if crossed:
                highest = max(crossed)
                seen_levels.update(crossed)
                when = reset_text(bucket["resets_at"])
                self._notify(
                    f"{label} at {pct:.0f}%" + (f" - {when}" if when else "")
                )
            self.alerted[label] = (resets, seen_levels)
        # drop buckets the API stopped returning, so this cannot grow forever
        live = {b["label"] for b in buckets}
        for gone in [k for k in self.alerted if k not in live]:
            del self.alerted[gone]

    # -- state application ------------------------------------------------
    def _apply(self, buckets, plan, error):
        if error and getattr(error, "kind", "") == "auth" and not self.notified_auth:
            self.notified_auth = True
            self._notify(str(error))
        if error and self.last:
            # Transient failure: keep last good data, grey out the icon.
            buckets, plan = self.last
            notice = f"⚠ {error}"
            worst = max(b["pct"] for b in buckets)
            self.icon.icon = make_icon_image(worst, stale=True)
            self.icon.title = f"Claude usage {worst:.0f}% (stale)"
            self.current = (buckets, plan, notice)
        elif error:
            self.icon.icon = make_icon_image(0, error=True)
            self.icon.title = "Claude usage unavailable"
            self.message = str(error)
            self.plan = plan
            self.current = (None, plan, None)
        else:
            self.last = (buckets, plan)
            worst = max(b["pct"] for b in buckets)
            self.icon.icon = make_icon_image(worst)
            self.icon.title = f"Claude usage {worst:.0f}%"
            self.current = (buckets, plan, None)
            self._check_alerts(buckets)
        try:
            self.icon.update_menu()
        except Exception:
            pass

    def _notify(self, body):
        try:
            self.icon.notify(body, APP_NAME)
        except Exception:
            pass

    # -- background loops -------------------------------------------------
    def _poll_loop(self):
        while not self.stopping.is_set():
            try:
                buckets, plan = fetch_usage()
                self._apply(buckets, plan, None)
                delay = POLL_SECONDS
                self.fail_delay = FAIL_RETRY_SECONDS
            except UsageError as exc:
                self._apply(None, None, exc)
                if getattr(exc, "kind", "") == "auth":
                    # Sign-in problems are fixed outside this app (Claude Code
                    # refreshes its own token). Keep checking on a short, fixed
                    # interval so the tray recovers on its own within a minute
                    # of the user signing in again — no backoff, no clicking.
                    delay = AUTH_RETRY_SECONDS
                else:
                    delay = max(getattr(exc, "retry_after", 0), self.fail_delay)
                    self.fail_delay = min(self.fail_delay * 2, FAIL_RETRY_MAX)
            except Exception as exc:  # never let a surprise kill the tray
                self._apply(None, None, UsageError(f"{type(exc).__name__}: {exc}"))
                delay = self.fail_delay
                self.fail_delay = min(self.fail_delay * 2, FAIL_RETRY_MAX)
            # Sleep until the next poll, but wake early on Refresh/Quit.
            if self.wake.wait(timeout=delay):
                self.wake.clear()

    def _tick_loop(self):
        # Rebuild the menu every minute so "resets in" countdowns stay fresh
        # without extra API calls.
        while not self.stopping.wait(60):
            if self.current[0]:
                try:
                    self.icon.update_menu()
                except Exception:
                    pass

    def run(self):
        threading.Thread(target=self._poll_loop, daemon=True).start()
        threading.Thread(target=self._tick_loop, daemon=True).start()
        self.icon.run()


_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_RUN_NAME = "ClaudeUsageTray"


def _startup_command():
    """Command to launch the tray windowless, for the autostart Run entry."""
    import shutil

    exe = shutil.which("claude-usage-tray")
    if exe:
        return f'"{exe}"'
    # Fallback: pythonw -m claude_usage_tray (no console window).
    pyw = Path(sys.executable).with_name("pythonw.exe")
    py = str(pyw) if pyw.exists() else sys.executable
    return f'"{py}" -m claude_usage_tray'


def enable_startup():
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, _RUN_NAME, 0, winreg.REG_SZ, _startup_command())
    print("Claude Usage Tray will now start automatically at login.")


def disable_startup():
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, _RUN_NAME)
        print("Removed Claude Usage Tray from login startup.")
    except FileNotFoundError:
        print("Autostart was not enabled.")


def dump():
    buckets, plan = fetch_usage()
    if plan:
        print(f"Plan: {plan}")
    for bucket in buckets:
        resets = reset_text(bucket["resets_at"])
        print(
            f"{bucket['label']:<22} {bar_text(bucket['pct'])} {bucket['pct']:5.0f}%"
            + (f"   {resets}" if resets else "")
        )


def diagnose():
    """Explain exactly where authentication stands.

    "It doesn't work" is unactionable; this says which token source was found,
    whether the API accepted it, and what to do next.
    """
    print(f"{APP_NAME} {VERSION}\n")
    print("token sources")
    saved = read_saved_token()
    print(f"  tray sign-in    : {TOKEN_FILE}")
    print(f"                    {'token saved' if saved else 'none'}")
    print(f"  Claude Code     : {CREDENTIALS_FILE}")
    if CREDENTIALS_FILE.exists():
        try:
            borrowed = read_claude_code_token()
            print(f"                    {'token found' if borrowed else 'file present but no token'}")
        except UsageError as exc:
            print(f"                    unreadable: {exc}")
    else:
        print("                    not present (Claude Code not installed/signed in here)")
    print(f"  claude CLI      : {claude_cli() or 'not found'}")

    levels = load_alert_levels()
    print("\nalerts")
    print(f"  config          : {CONFIG_FILE}")
    print(f"  warn at         : {', '.join(f'{lv}%' for lv in levels) or 'disabled'}")

    print("\nresult")
    try:
        token, plan = read_access_token()
    except UsageError as exc:
        print(f"  no usable token - {exc}")
        print('\nnext step: run the tray and choose "Sign in to Claude…",')
        print("or run `claude setup-token` and paste the token it prints.")
        return
    print(f"  using token from: {'tray sign-in' if saved else 'Claude Code'}")
    print(f"  plan            : {plan or '(unknown)'}")
    try:
        validate_token(token)
        print("  API check       : OK - the usage endpoint accepted this token")
    except urllib.error.HTTPError as exc:
        print(f"  API check       : REJECTED (HTTP {exc.code})")
        if exc.code in (401, 403):
            print('\nthe token is expired or invalid. Choose "Sign in to Claude…" in the tray,')
            print("or run `claude setup-token` for a fresh one.")
    except Exception as exc:
        print(f"  API check       : could not reach the API - {exc}")
        print("\nthis looks like a network/proxy problem rather than authentication.")


def main():
    try:  # so block-bar glyphs survive a legacy (cp1252) console on --dump
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if "--version" in sys.argv:
        print(f"{APP_ID} {VERSION}")
    elif "--diagnose" in sys.argv:
        diagnose()
    elif "--enable-startup" in sys.argv:
        enable_startup()
    elif "--disable-startup" in sys.argv:
        disable_startup()
    elif "--dump" in sys.argv:
        try:
            dump()
        except UsageError as exc:
            sys.exit(f"error: {exc}")
    else:
        TrayApp().run()


if __name__ == "__main__":
    main()
