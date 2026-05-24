"""Jarvis Panel CLI."""
from __future__ import annotations

import sys
import click

from jp import session as sess
from jp import layout as lay
from jp import config as cfg
from jp import summarize as summ



def _require_tmux() -> None:
    if not sess.tmux_installed():
        click.echo("[jp] tmux not installed. brew install tmux", err=True)
        sys.exit(1)


def _open_or_create(name: str | None, layout: int) -> None:
    if name and sess.session_exists(name):
        click.echo(f"[jp] attaching to {name}")
        sess.attach_session(name)
        return

    session_name = name or sess.next_session_name()
    sess.create_session(session_name)
    lay.apply_layout(session_name, layout)
    sess.set_pane_title(session_name, 0, "Shell")
    click.echo(f"[jp] started {session_name} ({layout} pane{'s' if layout > 1 else ''})")
    sess.attach_session(session_name)


@click.group(invoke_without_command=True)
@click.pass_context
def main(ctx):
    """Jarvis Panel — tmux multi-pane manager with AI summaries."""
    _require_tmux()

    if ctx.invoked_subcommand is not None:
        return

    # Default: attach to most recent jp session, or create a new 1-pane session.
    recent = sess.most_recent_session()
    if recent:
        click.echo(f"[jp] attaching to {recent}")
        sess.attach_session(recent)
    else:
        _open_or_create(None, 1)


@main.command()
@click.option("--layout", "-l", default=1,
              type=click.Choice(["1", "2", "3", "4", "6", "8"]),
              show_default=True, help="Initial pane count")
@click.option("--name", "-n", default=None, help="Session name (auto if omitted)")
def new(layout, name):
    """Create a new panel session."""
    _open_or_create(name, int(layout))


@main.command("run")
@click.argument("config_name")
def run_config(config_name):
    """Load a named config from jp/panels/."""
    c = cfg.load(config_name)
    session_name = f"jp-{config_name}"

    if sess.session_exists(session_name):
        click.echo(f"[jp] attaching to existing {session_name}")
        sess.attach_session(session_name)
        return

    sess.create_session(session_name)
    lay.apply_layout(session_name, c["layout"])
    lay.setup_panes(session_name, c.get("panes", []))
    click.echo(f"[jp] started {session_name} ({c['layout']} panes)")
    sess.attach_session(session_name)


@main.command()
@click.argument("session_name", required=False)
@click.option("--cmd", "-c", default=None, help="Command to run in new pane")
def add(session_name, cmd):
    """Add a pane to a session (default: most recent)."""
    name = session_name or sess.most_recent_session()
    if not name:
        click.echo("[jp] no active jp sessions", err=True)
        sys.exit(1)
    if not sess.session_exists(name):
        click.echo(f"[jp] session '{name}' not found", err=True)
        sys.exit(1)
    idx = sess.add_pane(name, cmd)
    click.echo(f"[jp] added pane {idx} to {name}")


@main.command("list")
def list_sessions_cmd():
    """List active jp sessions."""
    sessions = sess.list_sessions()
    if not sessions:
        click.echo("[jp] no active sessions")
        return
    for s in sessions:
        click.echo(f"  {s}  ({sess.pane_count(s)} panes)")


@main.command()
@click.argument("session_name", required=False)
def attach(session_name):
    """Attach to a session (default: most recent)."""
    name = session_name or sess.most_recent_session()
    if not name:
        click.echo("[jp] no active jp sessions", err=True)
        sys.exit(1)
    if not sess.session_exists(name):
        click.echo(f"[jp] session '{name}' not found", err=True)
        sys.exit(1)
    sess.attach_session(name)


@main.command()
@click.argument("session_name", required=False)
@click.option("--no-save", is_flag=True, help="Skip snapshot before killing")
def kill(session_name, no_save):
    """Kill a session (auto-saves snapshot first)."""
    name = session_name or sess.most_recent_session()
    if not name:
        click.echo("[jp] no active jp sessions", err=True)
        sys.exit(1)
    if not sess.session_exists(name):
        click.echo(f"[jp] session '{name}' not found", err=True)
        sys.exit(1)
    if not no_save:
        path = sess.save_snapshot(name)
        click.echo(f"[jp] snapshot saved" if path else "[jp] snapshot unchanged (no save)")
    sess.kill_session(name)
    click.echo(f"[jp] killed {name}")


@main.command()
@click.argument("session_name", required=False)
@click.option("--pane", "-p", default=None, type=int,
              help="Specific pane index (default: all panes)")
@click.option("--lines", "-l", default=200, show_default=True,
              help="Scrollback lines to summarize")
def summarize(session_name, pane, lines):
    """Summarize pane activity via NIM and show in pane border."""
    name = session_name or sess.most_recent_session()
    if not name:
        click.echo("[jp] no active jp sessions", err=True)
        sys.exit(1)
    if not sess.session_exists(name):
        click.echo(f"[jp] session '{name}' not found", err=True)
        sys.exit(1)
    summ.summarize_to_border(name, pane=pane, lines=lines)
    target = f"pane {pane}" if pane is not None else "all panes"
    click.echo(f"[jp] summarized {target} of {name}")


@main.command()
@click.argument("session_name", required=False)
def save(session_name):
    """Save session state for later resume."""
    name = session_name or sess.most_recent_session()
    if not name:
        click.echo("[jp] no active jp sessions", err=True)
        sys.exit(1)
    if not sess.session_exists(name):
        click.echo(f"[jp] session '{name}' not found", err=True)
        sys.exit(1)
    path = sess.save_snapshot(name)
    if path:
        click.echo(f"[jp] saved {name} → {path}")
    else:
        click.echo(f"[jp] snapshot unchanged, nothing saved")


@main.command()
@click.argument("session_name", required=False)
@click.argument("version", required=False, type=int, default=0)
@click.option("--all", "all_sessions", is_flag=True, help="Resume all saved snapshots (latest version)")
def resume(session_name, version, all_sessions):
    """Resume a saved session snapshot.

    VERSION 0 = latest, 1 = one before, etc. (default: 0)
    """
    if all_sessions:
        names = sess.list_snapshots()
        if not names:
            click.echo("[jp] no snapshots found")
            return
        for name in names:
            _resume_one(name, version=0, attach=False)
        click.echo(f"[jp] resumed {len(names)} session(s)")
        return

    name = session_name
    if not name:
        names = sess.list_snapshots()
        if not names:
            click.echo("[jp] no snapshots found", err=True)
            sys.exit(1)
        name = names[0]

    _resume_one(name, version=version, attach=True)


def _resume_one(name: str, version: int = 0, attach: bool = True) -> None:
    import shlex as _shlex
    if sess.session_exists(name):
        click.echo(f"[jp] {name} already running — attaching")
        if attach:
            sess.attach_session(name)
        return

    try:
        snapshot = sess.load_snapshot(name, version)
    except FileNotFoundError:
        click.echo(f"[jp] no snapshot for {name} version {version}", err=True)
        return

    panes = snapshot["panes"]
    count = len(panes)

    sess.create_session(name)
    for _ in range(count - 1):
        sess.add_pane(name)

    for p_data in panes:
        idx = p_data["index"]
        cwd = p_data.get("cwd") or sess.JARVIS_DIR
        title = p_data.get("title") or f"Pane {idx}"
        claude_id = p_data.get("claude_session_id")
        summary_full = p_data.get("summary_full") or ""

        sess.send_cmd(name, idx, f"cd {_shlex.quote(cwd)}")
        sess.set_pane_title(name, idx, title)

        if summary_full:
            sess.set_pane_option(name, idx, "@summary_full", summary_full)

        if claude_id:
            sess.send_cmd(name, idx, f"claude --resume {_shlex.quote(claude_id)} --dangerously-skip-permissions")

    saved_at = snapshot.get("saved_at", "")[:10]
    click.echo(f"[jp] resumed {name} ({count} pane{'s' if count > 1 else ''}, saved {saved_at})")
    if attach:
        sess.attach_session(name)


@main.command("snapshots")
def list_snapshots_cmd():
    """List saved session snapshots."""
    names = sess.list_snapshots()
    if not names:
        click.echo("[jp] no snapshots")
        return
    for name in names:
        versions = sess.list_snapshot_versions(name)
        click.echo(f"  {name}  ({len(versions)} version{'s' if len(versions) != 1 else ''})")
        for v in versions:
            snap = v["snapshot"]
            ver = v["version"]
            pane_count = len(snap.get("panes", []))
            claude_count = sum(1 for p in snap["panes"] if p.get("claude_session_id"))
            saved_at_raw = snap.get("saved_at", "")
            try:
                from datetime import datetime, timezone
                dt = datetime.fromisoformat(saved_at_raw).astimezone()
                saved_at = dt.strftime("%Y-%m-%d %H:%M")
            except Exception:
                saved_at = saved_at_raw[:16]
            suffix = f", {claude_count} claude" if claude_count else ""
            label = "latest" if ver == 0 else f"-{ver}"
            click.echo(f"    {ver}  {saved_at}  {pane_count} panes{suffix}  [{label}]")


@main.command("help")
def help_cmd():
    """Show all commands and keybindings."""
    click.echo("""
JARVIS PANEL — jp

CLI COMMANDS
  jp                        attach to most recent session (or create one)
  jp new [-l 1|2|3|4|6|8]  create a new session
  jp list                   list active sessions
  jp attach [name]          attach to a session
  jp kill [name]            save snapshot + kill session
  jp kill --no-save [name]  kill without saving
  jp save [name]            save snapshot without killing
  jp resume [name]          restore a saved snapshot
  jp resume --all           restore all saved snapshots
  jp snapshots              list saved snapshots
  jp add [name]             add a pane to a session
  jp summarize [name]       summarize all panes via NIM
  jp run <config>           start a named config layout
  jp configs                list available configs

TMUX KEYBINDINGS  (prefix: Ctrl+B)
  n          add a new pane
  N          add a new pane with claude --dangerously-skip-permissions
  1–8        switch to pane by number
  s          summarize current pane (NIM)
  S          summarize all panes (NIM)
  c          cycle summaries: short → full popup → hidden
  r          reset current pane (fresh zsh in ~/jarvis)
  w          close current pane
  q          save snapshot + kill session
  Q          kill session without saving
""")


@main.command("configs")
def list_configs_cmd():
    """List available named configs."""
    configs = cfg.list_configs()
    if not configs:
        click.echo("[jp] no configs in jp/panels/")
        return
    for c in configs:
        click.echo(f"  {c}")


@main.command("_binder", hidden=True)
@click.argument("subcommand")
@click.argument("session")
@click.argument("pane", required=False, type=int)
def _binder(subcommand, session, pane):
    """Internal: called by tmux keybindings."""
    if not sess.session_exists(session):
        return
    if subcommand == "add":
        sess.add_pane(session)
    elif subcommand == "claude":
        idx = sess.add_pane(session)
        sess.send_cmd(session, idx, "claude --dangerously-skip-permissions")
    elif subcommand == "summarize":
        if pane is None:
            return
        summ.summarize_to_border(session, pane=pane)
    elif subcommand == "summarize-all":
        summ.summarize_to_border(session, pane=None)
    elif subcommand == "cycle":
        summ.cycle_summary(session)
    elif subcommand == "reset":
        if pane is None:
            return
        sess.reset_pane(session, pane)
        summ.clear_summary(session, pane)
    elif subcommand == "savekill":
        sess.save_snapshot(session)
        sess.kill_session(session)
