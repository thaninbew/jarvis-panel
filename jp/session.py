"""tmux session lifecycle for Jarvis Panel.

All operations target an isolated tmux server (socket name "jp") so that
jp options/bindings never affect the user's regular tmux sessions.
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import tempfile
import textwrap
from datetime import datetime, timezone
from pathlib import Path

TMUX_SOCKET = "jp"
SESSION_PREFIX = "jp-"
HISTORY_LIMIT = 5000
MAX_PANES = 8
SNAPSHOT_DIR = Path.home() / "jarvis" / ".jp"

_JP_PY = str(Path(__file__).resolve().parent.parent / "jp.py")


def _tmux(args: list, check: bool = True, capture: bool = False) -> subprocess.CompletedProcess:
    cmd = ["tmux", "-L", TMUX_SOCKET] + args
    return subprocess.run(cmd, check=check, capture_output=capture, text=True)


def _tmux_silent(args: list) -> None:
    """Run a tmux command, suppressing all output."""
    subprocess.run(["tmux", "-L", TMUX_SOCKET] + args, check=False, capture_output=True)


def _server_running() -> bool:
    r = _tmux(["list-sessions"], check=False, capture=True)
    return r.returncode == 0


def session_exists(name: str) -> bool:
    r = _tmux(["has-session", "-t", name], check=False, capture=True)
    return r.returncode == 0


def list_sessions() -> list[str]:
    if not _server_running():
        return []
    r = _tmux(["list-sessions", "-F", "#{session_name}"], check=False, capture=True)
    if r.returncode != 0:
        return []
    return [s for s in r.stdout.strip().splitlines() if s.startswith(SESSION_PREFIX)]


def most_recent_session() -> str | None:
    if not _server_running():
        return None
    r = _tmux(
        ["list-sessions", "-F", "#{session_created} #{session_name}"],
        check=False, capture=True
    )
    if r.returncode != 0 or not r.stdout.strip():
        return None
    rows = []
    for line in r.stdout.strip().splitlines():
        parts = line.split(" ", 1)
        if len(parts) == 2 and parts[1].startswith(SESSION_PREFIX):
            rows.append((int(parts[0]), parts[1]))
    if not rows:
        return None
    rows.sort()
    return rows[-1][1]


def next_session_name() -> str:
    existing = list_sessions()
    nums = set()
    for s in existing:
        suffix = s[len(SESSION_PREFIX):]
        if suffix.isdigit():
            nums.add(int(suffix))
    n = 1
    while n in nums:
        n += 1
    return f"{SESSION_PREFIX}{n}"


def configure_server() -> None:
    """Set jp-server-wide options and bindings. Idempotent."""
    _tmux_silent(["set-option", "-g", "mouse", "on"])
    _tmux_silent(["set-option", "-g", "base-index", "0"])
    _tmux_silent(["set-option", "-g", "pane-base-index", "0"])
    _tmux_silent(["set-option", "-g", "renumber-windows", "on"])
    _tmux_silent(["set-option", "-g", "history-limit", str(HISTORY_LIMIT)])
    _tmux_silent(["set-option", "-g", "escape-time", "10"])

    # Pane borders carry per-pane title or AI summary
    _tmux_silent(["set-option", "-g", "pane-border-status", "top"])
    border_fmt = (
        "#{?pane_active,#[fg=cyan bold],#[fg=#555555]}"
        "#{?#{==:#{@summary},,},"
        "#{?#{!=:#{pane_title},#{host_short}},#{pane_title},Pane #{pane_index}},"
        "#[fg=yellow]#{@summary}"
        "}"
    )
    _tmux_silent(["set-option", "-g", "pane-border-format", border_fmt])
    _tmux_silent(["set-option", "-g", "pane-border-style", "fg=#333333"])
    _tmux_silent(["set-option", "-g", "pane-active-border-style", "fg=cyan"])

    # Status bar with keybinding hints
    _tmux_silent(["set-option", "-g", "status", "on"])
    _tmux_silent(["set-option", "-g", "status-position", "bottom"])
    _tmux_silent(["set-option", "-g", "status-interval", "5"])
    _tmux_silent(["set-option", "-g", "status-style", "bg=default,fg=#666666"])
    _tmux_silent([
        "set-option", "-g", "status-left",
        "#{?client_prefix,#[bg=cyan fg=black bold] PREFIX ,"
        "#[fg=cyan bold] JARVIS PANEL }"
        "#[default] #[fg=#999999]#{session_name}#[default]  "
    ])
    _tmux_silent(["set-option", "-g", "status-left-length", "60"])
    _tmux_silent([
        "set-option", "-g", "status-right",
        "#[fg=#888888]^B n add · ^B N claude · ^B s sum · ^B S sum-all · ^B c toggle · ^B r reset · ^B R restart · ^B w close · ^B q save+quit · ^B Q quit "
    ])
    _tmux_silent(["set-option", "-g", "status-right-length", "120"])
    _tmux_silent(["set-option", "-g", "status-justify", "left"])
    _tmux_silent(["set-option", "-g", "window-status-format", ""])
    _tmux_silent(["set-option", "-g", "window-status-current-format", ""])
    _tmux_silent(["set-option", "-g", "window-status-separator", ""])

    # Keybindings
    bindings = [
        ("n", ["run-shell", "-b", f"python3 {_JP_PY} _binder add #{{session_name}}"]),
        ("N", ["run-shell", "-b", f"python3 {_JP_PY} _binder claude #{{session_name}}"]),
        ("s", ["run-shell", "-b", f"python3 {_JP_PY} _binder summarize #{{session_name}} #{{pane_index}}"]),
        ("S", ["run-shell", "-b", f"python3 {_JP_PY} _binder summarize-all #{{session_name}}"]),
        ("c", ["run-shell", f"python3 {_JP_PY} _binder cycle #{{session_name}}"]),
        ("r", ["run-shell", "-b", f"python3 {_JP_PY} _binder reset #{{session_name}} #{{pane_index}}"]),
        ("R", ["run-shell", "-b", f"python3 {_JP_PY} _binder restart #{{session_name}}"]),
        ("w", ["kill-pane"]),
        ("q", ["run-shell", f"python3 {_JP_PY} _binder savekill #{{session_name}}"]),
        ("Q", ["kill-session"]),
    ]
    for key, cmd in bindings:
        _tmux_silent(["unbind-key", key])
        _tmux_silent(["bind-key", key] + cmd)
    _tmux_silent(["unbind-key", "x"])
    _tmux_silent(["set-hook", "-g", "after-kill-pane", "select-layout tiled"])

    # 1–8 → switch to pane by number
    for i in range(1, 9):
        _tmux_silent(["unbind-key", str(i)])
        _tmux_silent(["bind-key", str(i), "select-pane", "-t", str(i - 1)])


JARVIS_DIR = str(Path.home() / "jarvis")


def create_session(name: str) -> None:
    """Create a detached session with one pane."""
    try:
        sz = os.get_terminal_size()
        cols, rows = str(sz.columns), str(sz.lines)
    except OSError:
        cols, rows = "220", "50"
    _tmux([
        "new-session", "-d", "-s", name,
        "-x", cols, "-y", rows,
        "-c", JARVIS_DIR,
        "zsh"
    ])
    configure_server()
    _tmux_silent(["set-option", "-t", name, "history-limit", str(HISTORY_LIMIT)])


def kill_session(name: str) -> None:
    _tmux(["kill-session", "-t", name])


def attach_session(name: str) -> None:
    """Replace current process with tmux attach."""
    os.execvp("tmux", ["tmux", "-L", TMUX_SOCKET, "attach-session", "-t", name])


def pane_count(name: str) -> int:
    r = _tmux(
        ["list-panes", "-t", f"{name}:0", "-F", "#{pane_index}"],
        capture=True
    )
    lines = [l for l in r.stdout.strip().splitlines() if l.strip()]
    return len(lines)


def add_pane(name: str, cmd: str = None) -> int:
    count = pane_count(name)
    if count >= MAX_PANES:
        print(f"[jp] max {MAX_PANES} panes reached in {name}", file=sys.stderr)
        sys.exit(1)

    last = count - 1
    _tmux(["split-window", "-t", f"{name}:0.{last}", "-h", "-c", JARVIS_DIR, "zsh"])
    _tmux(["select-layout", "-t", f"{name}:0", "tiled"])

    new_idx = count
    if cmd:
        _tmux(["send-keys", "-t", f"{name}:0.{new_idx}", cmd, "Enter"])
    return new_idx


def send_cmd(name: str, pane: int, cmd: str) -> None:
    _tmux(["send-keys", "-t", f"{name}:0.{pane}", cmd, "Enter"], check=False)


def set_pane_title(name: str, pane: int, title: str) -> None:
    _tmux(["select-pane", "-t", f"{name}:0.{pane}", "-T", title], check=False)


def set_pane_option(name: str, pane: int, key: str, value: str) -> None:
    _tmux(
        ["set-option", "-p", "-t", f"{name}:0.{pane}", key, value],
        check=False
    )


def reset_pane(name: str, pane: int) -> None:
    _tmux(
        ["respawn-pane", "-k", "-c", JARVIS_DIR, "-t", f"{name}:0.{pane}"],
        check=False
    )


def get_pane_option(name: str, pane: int, key: str) -> str:
    r = _tmux(
        ["show-options", "-pv", "-t", f"{name}:0.{pane}", key],
        check=False, capture=True
    )
    return r.stdout.strip()


def get_window_option(name: str, key: str) -> str:
    r = _tmux(
        ["show-options", "-wv", "-t", f"{name}:0", key],
        check=False, capture=True
    )
    return r.stdout.strip()


def set_window_option(name: str, key: str, value: str) -> None:
    _tmux(["set-option", "-w", "-t", f"{name}:0", key, value], check=False)


def show_summary_popup(name: str) -> None:
    count = pane_count(name)
    lines = ["  JARVIS PANEL — SUMMARIES  ", ""]
    for p in range(count):
        title_r = _tmux(
            ["display-message", "-t", f"{name}:0.{p}", "-p", "#{pane_title}"],
            check=False, capture=True
        )
        title = title_r.stdout.strip() or f"Pane {p}"
        full = get_pane_option(name, p, "@summary_full") or "(no summary)"
        lines.append(f"Pane {p} · {title}")
        for wrapped_line in textwrap.wrap(full, width=68):
            lines.append(f"  {wrapped_line}")
        lines.append("")

    lines.append("Press Enter to close")
    content = "\n".join(lines)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write(content)
        tmpfile = f.name

    _tmux([
        "display-popup",
        "-w", "75%", "-h", "60%",
        "-E", f"cat {shlex.quote(tmpfile)}; rm -f {shlex.quote(tmpfile)}; read -r",
    ], check=False)


def capture_pane(name: str, pane: int, lines: int) -> str:
    r = _tmux(
        ["capture-pane", "-t", f"{name}:0.{pane}", "-p", "-S", f"-{lines}"],
        capture=True
    )
    return r.stdout


def tmux_installed() -> bool:
    try:
        subprocess.run(["tmux", "-V"], capture_output=True, check=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


# ── Snapshot / resume ──────────────────────────────────────────────────────

def get_pane_cwd(name: str, pane: int) -> str:
    r = _tmux(
        ["display-message", "-t", f"{name}:0.{pane}", "-p", "#{pane_current_path}"],
        check=False, capture=True
    )
    return r.stdout.strip() or JARVIS_DIR


def get_pane_pid(name: str, pane: int) -> str:
    r = _tmux(
        ["display-message", "-t", f"{name}:0.{pane}", "-p", "#{pane_pid}"],
        check=False, capture=True
    )
    return r.stdout.strip()


def get_claude_session_id(name: str, pane: int) -> str | None:
    """Find the claude session ID for a pane by reading ~/.claude/sessions/<child_pid>.json."""
    shell_pid = get_pane_pid(name, pane)
    if not shell_pid:
        return None
    try:
        r = subprocess.run(["pgrep", "-P", shell_pid], capture_output=True, text=True)
        child_pids = r.stdout.strip().splitlines()
    except Exception:
        return None
    for pid in child_pids:
        session_file = Path.home() / ".claude" / "sessions" / f"{pid}.json"
        if session_file.exists():
            try:
                data = json.loads(session_file.read_text())
                sid = data.get("sessionId")
                if sid:
                    return sid
            except Exception:
                continue
    return None


SNAPSHOT_VERSIONS = 5


def _snapshot_path(name: str, version: int = 0) -> Path:
    return SNAPSHOT_DIR / f"{name}_{version}.json"


def _rotate_snapshots(name: str) -> None:
    for v in range(SNAPSHOT_VERSIONS - 2, -1, -1):
        src = _snapshot_path(name, v)
        dst = _snapshot_path(name, v + 1)
        if src.exists():
            src.rename(dst)


def _snapshot_fingerprint(snapshot: dict) -> list:
    return [(p["title"], p["cwd"], p.get("claude_session_id")) for p in snapshot.get("panes", [])]


def save_snapshot(name: str) -> Path | None:
    """Save snapshot, rotating history. Returns None if redundant."""
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    count = pane_count(name)
    panes = []
    for p in range(count):
        title_r = _tmux(
            ["display-message", "-t", f"{name}:0.{p}", "-p", "#{pane_title}"],
            check=False, capture=True
        )
        title = title_r.stdout.strip() or f"Pane {p}"
        panes.append({
            "index": p,
            "title": title,
            "cwd": get_pane_cwd(name, p),
            "claude_session_id": get_claude_session_id(name, p),
            "summary_full": get_pane_option(name, p, "@summary_full"),
        })
    snapshot = {
        "name": name,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "panes": panes,
    }
    latest = _snapshot_path(name, 0)
    if latest.exists():
        try:
            existing = json.loads(latest.read_text())
            if _snapshot_fingerprint(existing) == _snapshot_fingerprint(snapshot):
                return None
        except Exception:
            pass
    _rotate_snapshots(name)
    path = _snapshot_path(name, 0)
    path.write_text(json.dumps(snapshot, indent=2))
    return path


def list_snapshots() -> list[str]:
    """Return session names that have at least one snapshot, newest first."""
    if not SNAPSHOT_DIR.exists():
        return []
    seen: dict[str, float] = {}
    for p in SNAPSHOT_DIR.glob("*_0.json"):
        session_name = p.stem.rsplit("_", 1)[0]
        seen[session_name] = p.stat().st_mtime
    return sorted(seen, key=lambda n: seen[n], reverse=True)


def list_snapshot_versions(name: str) -> list[dict]:
    """Return all available versions for a session, newest first."""
    versions = []
    for v in range(SNAPSHOT_VERSIONS):
        path = _snapshot_path(name, v)
        if path.exists():
            try:
                snap = json.loads(path.read_text())
                versions.append({"version": v, "snapshot": snap})
            except Exception:
                pass
    return versions


def load_snapshot(name: str, version: int = 0) -> dict:
    path = _snapshot_path(name, version)
    if not path.exists():
        raise FileNotFoundError(f"no snapshot for {name} version {version}")
    return json.loads(path.read_text())
