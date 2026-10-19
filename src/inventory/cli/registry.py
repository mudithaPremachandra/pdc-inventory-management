"""Command registry for the CLI.

Every CLI command is a function decorated with @command(...). The decorator stores
its name, group, help text, arguments and examples in REGISTRY, which is what the
`help` command prints and what the REPL uses to dispatch a typed line.
"""

import argparse
from dataclasses import dataclass, field
from typing import Callable


class UsageError(Exception):
    """The user typed a command wrong (unknown command, missing argument...)."""


@dataclass(frozen=True)
class Arg:
    flags: tuple[str, ...]
    kwargs: dict


def arg(*flags: str, **kwargs) -> Arg:
    """Describe one argument, using the same parameters as argparse.add_argument."""
    return Arg(flags, kwargs)


@dataclass
class CliCommand:
    name: str
    group: str
    summary: str
    func: Callable
    args: list[Arg] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)
    # Permission the server will check (shown in `help <cmd>`); None = anyone.
    permission: str | None = None
    # Write commands send a command to the write side and then wait for the read side.
    writes: bool = False
    aliases: tuple[str, ...] = ()

    def parser(self) -> argparse.ArgumentParser:
        parser = _Parser(prog=self.name, description=self.summary, add_help=False)
        for a in self.args:
            parser.add_argument(*a.flags, **a.kwargs)
        if self.writes:
            parser.add_argument("--no-wait", action="store_true", help="don't wait for the read model to update")
        return parser

    def usage(self) -> str:
        return self.parser().format_usage().replace("usage: ", "").strip()

    def parse(self, argv: list[str]) -> argparse.Namespace:
        return self.parser().parse_args(argv)


class _Parser(argparse.ArgumentParser):
    """argparse calls sys.exit() on bad input; inside a REPL we raise instead."""

    def error(self, message):
        raise UsageError(f"{message}\nusage: {self.format_usage().replace('usage: ', '').strip()}")


REGISTRY: dict[str, CliCommand] = {}
_ALIASES: dict[str, str] = {}


def command(name: str, group: str, summary: str, args=(), examples=(), permission=None, writes=False, aliases=()):
    def decorator(func: Callable) -> Callable:
        REGISTRY[name] = CliCommand(
            name, group, summary, func, list(args), list(examples), permission, writes, tuple(aliases)
        )
        for alias in aliases:
            _ALIASES[alias] = name
        return func

    return decorator


def lookup(name: str) -> CliCommand:
    name = _ALIASES.get(name, name)
    try:
        return REGISTRY[name]
    except KeyError:
        raise UsageError(f"unknown command '{name}'. Type 'help' to see all commands.") from None
