"""Pane layout presets."""
import subprocess
import sys
from pathlib import Path
from jp.session import TMUX_SOCKET, JARVIS_DIR, send_cmd, set_pane_title

VALID_LAYOUTS = [1, 2, 3, 4, 6, 8]


def _tmux(args: list) -> None:
    subprocess.run(["tmux", "-L", TMUX_SOCKET] + args, check=True)


def _split_h(name: str, pane: int, percent: int) -> None:
    _tmux(["split-window", "-t", f"{name}:0.{pane}", "-h", "-p", str(percent), "-c", JARVIS_DIR, "zsh"])


def _split_v(name: str, pane: int, percent: int) -> None:
    _tmux(["split-window", "-t", f"{name}:0.{pane}", "-v", "-p", str(percent), "-c", JARVIS_DIR, "zsh"])


def _select(name: str, pane: int) -> None:
    _tmux(["select-pane", "-t", f"{name}:0.{pane}"])


def _tiled(name: str) -> None:
    _tmux(["select-layout", "-t", f"{name}:0", "tiled"])


def apply_layout(name: str, count: int) -> None:
    """Apply layout to a session that already has one pane."""
    if count not in VALID_LAYOUTS:
        print(f"[jp] invalid layout {count}. valid: {VALID_LAYOUTS}", file=sys.stderr)
        sys.exit(1)

    if count == 1:
        return

    if count == 2:
        _split_h(name, 0, 50)

    elif count == 3:
        _split_h(name, 0, 50)
        _split_v(name, 1, 50)

    elif count == 4:
        _split_h(name, 0, 50)
        _select(name, 0)
        _split_v(name, 0, 50)
        _split_v(name, 1, 50)

    elif count in (6, 8):
        for _ in range(count - 1):
            _tmux(["split-window", "-t", f"{name}:0", "-c", JARVIS_DIR, "zsh"])
        _tiled(name)

    _select(name, 0)


def setup_panes(name: str, panes: list[dict]) -> None:
    """Apply labels and start commands defined in a YAML config."""
    for i, pane in enumerate(panes):
        label = pane.get("label", f"Pane {i+1}")
        set_pane_title(name, i, label)
        cmd = (pane.get("cmd") or "").strip()
        if cmd:
            send_cmd(name, i, cmd)
