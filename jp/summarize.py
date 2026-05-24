"""Summarize tmux pane scrollback via NIM and write to pane border."""
import os
import sys
from pathlib import Path
from jp import session as sess


def _load_env() -> None:
    if os.getenv("NVIDIA_API_KEY"):
        return
    env_file = Path.home() / "jarvis" / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

BORDER_SYSTEM = (
    "Summarize the terminal scrollback in ONE short clause, max 80 chars. "
    "State only what task is being worked on. No preamble. No period. "
    "Examples: 'editing telegram_bot.py: fixing routing', "
    "'running pytest, 3 failures', 'idle zsh prompt'."
)

MAX_LINES = 1000
BORDER_WIDTH = 80


def _format_for_border(text: str) -> str:
    text = text.strip().replace("\n", " ").replace("\r", " ")
    while "  " in text:
        text = text.replace("  ", " ")
    if len(text) > BORDER_WIDTH:
        text = text[:BORDER_WIDTH - 3] + "..."
    return text


def _nim_call(prompt: str) -> str:
    sys.path.insert(0, os.path.expanduser("~/jarvis"))
    from nim_client import call as nim_call
    return nim_call(
        prompt=prompt,
        tier="nano",
        system=BORDER_SYSTEM,
        max_tokens=200,
    )


def summarize_to_border(session: str, pane: int = None, lines: int = 200) -> None:
    """Capture scrollback, summarize, and set pane @summary option.

    pane=None → summarize all panes in the session.
    """
    lines = min(lines, MAX_LINES)

    if pane is not None:
        targets = [pane]
    else:
        targets = list(range(sess.pane_count(session)))

    for p in targets:
        sess.set_pane_option(session, p, "@summary", "summarizing...")

    _load_env()

    if not os.getenv("NVIDIA_API_KEY"):
        for p in targets:
            sess.set_pane_option(session, p, "@summary", "error: NVIDIA_API_KEY not set")
        return

    for p in targets:
        text = sess.capture_pane(session, p, lines)
        if not text.strip():
            sess.set_pane_option(session, p, "@summary", "(empty scrollback)")
            sess.set_pane_option(session, p, "@summary_full", "(empty scrollback)")
            continue

        try:
            result = _nim_call(text)
        except Exception as e:
            msg = str(e).replace("\n", " ")
            err = f"error: {msg[:60]}"
            sess.set_pane_option(session, p, "@summary", err)
            sess.set_pane_option(session, p, "@summary_full", err)
            continue

        sess.set_pane_option(session, p, "@summary", _format_for_border(result))
        sess.set_pane_option(session, p, "@summary_full", result.strip())

    sess.set_window_option(session, "@summary_state", "short")


def clear_summary(session: str, pane: int) -> None:
    sess.set_pane_option(session, pane, "@summary", "")
    sess.set_pane_option(session, pane, "@summary_full", "")


def cycle_summary(session: str) -> None:
    """Cycle all panes: short → full (popup) → hidden → short."""
    state = sess.get_window_option(session, "@summary_state") or "hidden"

    if state == "hidden":
        # Restore short summaries to all pane borders
        count = sess.pane_count(session)
        any_summary = False
        for p in range(count):
            full = sess.get_pane_option(session, p, "@summary_full")
            if full:
                sess.set_pane_option(session, p, "@summary", _format_for_border(full))
                any_summary = True
        if any_summary:
            sess.set_window_option(session, "@summary_state", "short")

    elif state == "short":
        # Show full popup, keep borders visible
        sess.set_window_option(session, "@summary_state", "full")
        sess.show_summary_popup(session)

    else:
        # full or anything else → hide all borders
        count = sess.pane_count(session)
        for p in range(count):
            sess.set_pane_option(session, p, "@summary", "")
        sess.set_window_option(session, "@summary_state", "hidden")
