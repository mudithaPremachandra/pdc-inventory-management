import io

import pytest
from rich.console import Console

from inventory.cli import commands  # noqa: F401  (registers the commands)
from inventory.cli.client import ApiClient, Session
from inventory.cli.commands import _parse_when
from inventory.cli.main import run_line
from inventory.cli.registry import REGISTRY, UsageError, lookup


@pytest.fixture
def session():
    out = io.StringIO()
    s = Session(api=ApiClient("http://127.0.0.1:9", "http://127.0.0.1:9"),
                console=Console(file=out, width=200), persist=False)
    s.output = out
    return s


def test_every_command_has_a_group_summary_and_valid_parser():
    for cmd in REGISTRY.values():
        assert cmd.summary and cmd.group
        cmd.parser()  # must not raise


def test_help_lists_every_command(session):
    assert run_line(session, "help") == 0
    text = session.output.getvalue()
    for name in REGISTRY:
        assert name in text


def test_help_for_one_command_shows_usage_and_examples(session):
    assert run_line(session, "help receive") == 0
    text = session.output.getvalue()
    assert "usage:" in text and "receive CBL-001 50" in text and "stock:receive" in text


def test_unknown_command_is_usage_error(session):
    assert run_line(session, "teleport") == 2
    assert "unknown command" in session.output.getvalue()


def test_missing_argument_is_usage_error(session):
    assert run_line(session, "receive CBL-001") == 2


def test_quantity_must_be_an_integer():
    with pytest.raises(UsageError):
        lookup("receive").parse(["CBL-001", "ten"])


def test_negative_adjustment_parses_as_number():
    args = lookup("adjust").parse(["CBL-001", "-2", "--reason", "broken"])
    assert args.change == -2


def test_write_commands_get_no_wait_flag():
    assert lookup("receive").parse(["A1", "1", "--no-wait"]).no_wait is True


def test_aliases_resolve():
    assert lookup("quit").name == "exit"
    assert lookup("ls").name == "products"


def test_unreachable_server_is_reported_not_crashed(session):
    assert run_line(session, "products") == 1
    assert "cannot reach" in session.output.getvalue()


def test_relative_and_iso_times():
    assert _parse_when("10m").tzinfo is not None
    assert _parse_when("2026-01-02T03:04").year == 2026
    with pytest.raises(UsageError):
        _parse_when("yesterday-ish")
