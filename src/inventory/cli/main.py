"""CLI entry point.

  inventory                   -> interactive mode (prompt: inventory>)
  inventory receive SKU 10    -> run one command and exit (handy for scripts/tests)
"""

import shlex
import sys

from rich.markup import escape

from inventory.cli import commands as _commands  # noqa: F401  (registers all commands)
from inventory.cli.client import ApiClient, ApiError, Session
from inventory.cli.commands import ExitRepl
from inventory.cli.registry import UsageError, lookup

BANNER = """[bold cyan]Inventory Management[/bold cyan] - CQRS + Event Sourcing
Type [bold]help[/bold] to list commands, [bold]login <username>[/bold] to start, [bold]exit[/bold] to quit."""


def run_line(session: Session, line: str) -> int:
    """Run one typed command. Returns an exit code: 0 ok, 1 server said no, 2 typed wrong."""
    try:
        argv = shlex.split(line)
    except ValueError as exc:
        session.console.print(f"[red]✖ {escape(str(exc))}[/red]")
        return 2
    if not argv:
        return 0
    try:
        cmd = lookup(argv[0])
        cmd.func(session, cmd.parse(argv[1:]))
        return 0
    except UsageError as exc:
        session.console.print(f"[red]✖ {escape(str(exc))}[/red]")
        return 2
    except ApiError as exc:
        hint = ""
        if exc.status == 401:
            hint = " - log in with: login <username>"
        session.console.print(f"[red]✖ {escape(exc.detail)}[/red]{hint}")
        return 1


def _prompt(session: Session) -> str:
    who = session.username or "not logged in"
    return f"inventory({who})> "


def repl(session: Session) -> None:
    try:
        import readline  # noqa: F401  (arrow keys + history on Linux/macOS)
    except ImportError:
        pass
    session.console.print(BANNER)
    if session.username:
        session.console.print(f"[dim]resumed session for {session.username}[/dim]")
    while True:
        try:
            line = input(_prompt(session))
        except (EOFError, KeyboardInterrupt):
            session.console.print()
            break
        try:
            run_line(session, line)
        except ExitRepl:
            break
    session.console.print("bye")


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    session = Session(api=ApiClient())
    session.restore()
    if not argv:
        repl(session)
        return 0
    try:
        return run_line(session, shlex.join(argv))
    except ExitRepl:
        return 0


if __name__ == "__main__":
    sys.exit(main())
