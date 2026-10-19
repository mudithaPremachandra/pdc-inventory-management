"""Every command the CLI understands.

Write commands (product-add, receive, ...) call the command-api, print which event
was appended, then wait for the projector so a following query sees the change.
Read commands (products, history, ...) call the query-api and print a table.
"""

import json
import re
from datetime import datetime, timedelta, timezone

from rich.markup import escape
from rich.prompt import Prompt
from rich.table import Table

from inventory.cli.client import ApiError, Session
from inventory.cli.registry import REGISTRY, UsageError, arg, command, lookup


class ExitRepl(Exception):
    pass


# --- helpers ------------------------------------------------------------------------


def _table(title: str, columns: list[str], rows: list[list], empty: str = "nothing to show") -> Table | str:
    if not rows:
        return f"[dim]{empty}[/dim]"
    table = Table(title=title, header_style="bold cyan", title_justify="left")
    for col in columns:
        table.add_column(col)
    for row in rows:
        table.add_row(*("" if v is None else escape(str(v)) for v in row))
    return table


def _time(value: str | None) -> str:
    if not value:
        return ""
    return datetime.fromisoformat(value).astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _write(session: Session, args, method: str, path: str, body: dict) -> None:
    """Send a command to the write side, report the events, then wait for the read side."""
    result = session.api.send_command(method, path, body)
    events = ", ".join(result["events"])
    session.console.print(
        f"[green]✔[/green] {events} → [bold]{result['stream_id']}[/bold] "
        f"(version {result['version']}, position {result['global_position']})"
    )
    if getattr(args, "no_wait", False):
        session.console.print("[dim]not waiting for the read model (--no-wait)[/dim]")
    elif session.api.wait_for_projection(result["global_position"]):
        session.console.print("[dim]read model updated[/dim]")
    else:
        session.console.print(
            "[yellow]read model has not caught up yet (eventual consistency) - queries may show old data "
            "for a moment. Check `status`.[/yellow]"
        )


_RELATIVE = re.compile(r"^(\d+)\s*([smhd])$")


def _parse_when(text: str) -> datetime:
    """Accept '2026-10-16T14:30', '2026-10-16 14:30' or a relative time like '10m' (10 minutes ago)."""
    text = text.strip()
    if m := _RELATIVE.match(text):
        unit = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}[m.group(2)]
        return datetime.now(timezone.utc) - timedelta(**{unit: int(m.group(1))})
    try:
        when = datetime.fromisoformat(text)
    except ValueError:
        raise UsageError(f"cannot read time {text!r}; use e.g. 2026-10-16T14:30 or 10m / 2h / 1d") from None
    return when if when.tzinfo else when.astimezone()  # naive = this machine's local time


# --- general ------------------------------------------------------------------------


@command("help", "General", "Show all commands, or details of one command",
         args=[arg("command", nargs="?", help="command to explain")],
         examples=["help", "help receive"], aliases=("?",))
def help_(session: Session, args) -> None:
    if args.command:
        cmd = lookup(args.command)
        session.console.print(f"[bold]{cmd.name}[/bold] - {cmd.summary}")
        session.console.print(f"\n[cyan]usage:[/cyan] {escape(cmd.usage())}")
        parser = cmd.parser()
        if parser._actions:
            session.console.print("\n[cyan]arguments:[/cyan]")
            for a in parser._actions:
                name = ", ".join(a.option_strings) or a.dest
                required = " (required)" if a.required and a.option_strings else ""
                session.console.print(f"  {escape(name):<20} {escape(a.help or '')}{required}")
        if cmd.permission:
            session.console.print(f"\n[cyan]needs permission:[/cyan] {cmd.permission}")
        if cmd.aliases:
            session.console.print(f"[cyan]aliases:[/cyan] {', '.join(cmd.aliases)}")
        if cmd.examples:
            session.console.print("\n[cyan]examples:[/cyan]")
            for ex in cmd.examples:
                session.console.print(f"  inventory> {escape(ex)}")
        return

    table = Table(title="Commands", header_style="bold cyan", title_justify="left", show_lines=False)
    table.add_column("group")
    table.add_column("command")
    table.add_column("description")
    last_group = None
    for cmd in sorted(REGISTRY.values(), key=lambda c: (_GROUP_ORDER.index(c.group), c.name)):
        table.add_row(cmd.group if cmd.group != last_group else "", cmd.name, cmd.summary)
        last_group = cmd.group
    session.console.print(table)
    session.console.print("Type [bold]help <command>[/bold] for usage and examples.")


_GROUP_ORDER = ["General", "Account", "Products", "Stock", "Reports", "Event sourcing", "Admin"]


@command("exit", "General", "Leave the CLI", aliases=("quit",))
def exit_(session: Session, args) -> None:
    raise ExitRepl


@command("clear", "General", "Clear the screen")
def clear(session: Session, args) -> None:
    session.console.clear()


# --- account ------------------------------------------------------------------------


@command("login", "Account", "Log in (asks for the password if not given)",
         args=[arg("username"), arg("--password", "-p", help="password (prompted if omitted)")],
         examples=["login admin"])
def login(session: Session, args) -> None:
    password = args.password or Prompt.ask("password", password=True, console=session.console)
    result = session.api.login(args.username, password)
    session.set_login(result["access_token"], result["username"], result["role"])
    session.console.print(f"[green]✔[/green] logged in as [bold]{result['username']}[/bold] ({result['role']})")


@command("logout", "Account", "Forget the current login")
def logout(session: Session, args) -> None:
    session.clear_login()
    session.console.print("logged out")


@command("whoami", "Account", "Show the logged-in user, role and permissions")
def whoami(session: Session, args) -> None:
    me = session.api.query("/me")
    session.console.print(f"[bold]{me['username']}[/bold] ({me['role']})")
    session.console.print("permissions: " + ", ".join(me["permissions"]))


@command("passwd", "Account", "Change your own password",
         args=[arg("--old", help="current password (prompted if omitted)"),
               arg("--new", help="new password (prompted if omitted)")])
def passwd(session: Session, args) -> None:
    old = args.old or Prompt.ask("current password", password=True, console=session.console)
    new = args.new or Prompt.ask("new password", password=True, console=session.console)
    _write(session, args, "POST", "/auth/password", {"old_password": old, "new_password": new})


# --- products -----------------------------------------------------------------------


@command("products", "Products", "List products",
         args=[arg("--search", "-s", help="filter by SKU, name or category"),
               arg("--all", action="store_true", help="include discontinued products")],
         examples=["products", "products --search cable"], permission="inventory:read", aliases=("ls",))
def products(session: Session, args) -> None:
    rows = session.api.query("/products", search=args.search, include_discontinued=args.all or None)
    session.console.print(_table(
        "Products", ["SKU", "name", "category", "price", "qty", "reorder at", "status"],
        [[p["sku"], p["name"], p["category"], p["unit_price"], p["quantity"], p["reorder_level"], p["status"]]
         for p in rows],
        empty="no products yet - add one with product-add",
    ))


@command("product", "Products", "Show one product's current state",
         args=[arg("sku")], examples=["product CBL-001"], permission="inventory:read")
def product(session: Session, args) -> None:
    p = session.api.query(f"/products/{args.sku}")
    for key in ("sku", "name", "category", "unit_price", "quantity", "reorder_level", "status", "version"):
        session.console.print(f"  [cyan]{key:<14}[/cyan] {p[key]}")
    session.console.print(f"  [cyan]{'updated':<14}[/cyan] {_time(p['updated_at'])}")


@command("product-add", "Products", "Register a new product",
         args=[arg("sku"), arg("name"),
               arg("--price", required=True, help="unit price, e.g. 12.50"),
               arg("--reorder-level", type=int, required=True, help="warn when stock falls to this level"),
               arg("--category", "-c", help="optional category")],
         examples=['product-add CBL-001 "USB-C cable 1m" --price 4.99 --reorder-level 20 --category cables'],
         permission="product:manage", writes=True)
def product_add(session: Session, args) -> None:
    _write(session, args, "POST", "/products", {
        "sku": args.sku, "name": args.name, "unit_price": args.price,
        "reorder_level": args.reorder_level, "category": args.category,
    })


@command("product-update", "Products", "Change a product's name, price, reorder level or category",
         args=[arg("sku"), arg("--name"), arg("--price"), arg("--reorder-level", type=int), arg("--category")],
         examples=["product-update CBL-001 --price 5.49"], permission="product:manage", writes=True)
def product_update(session: Session, args) -> None:
    body = {"name": args.name, "unit_price": args.price, "reorder_level": args.reorder_level, "category": args.category}
    body = {k: v for k, v in body.items() if v is not None}
    if not body:
        raise UsageError("give at least one of --name --price --reorder-level --category")
    _write(session, args, "PATCH", f"/products/{args.sku}", body)


@command("product-discontinue", "Products", "Stop selling a product (history is kept)",
         args=[arg("sku"), arg("--reason")],
         examples=['product-discontinue CBL-001 --reason "replaced by CBL-002"'],
         permission="product:manage", writes=True)
def product_discontinue(session: Session, args) -> None:
    _write(session, args, "POST", f"/products/{args.sku}/discontinue", {"reason": args.reason})


# --- stock --------------------------------------------------------------------------


@command("receive", "Stock", "Add stock (goods arrived)",
         args=[arg("sku", help="product code"), arg("quantity", type=int, help="how many units arrived"),
               arg("--ref", help="e.g. purchase order number")],
         examples=["receive CBL-001 50 --ref PO-1001"], permission="stock:receive", writes=True)
def receive(session: Session, args) -> None:
    _write(session, args, "POST", f"/products/{args.sku}/receive", {"quantity": args.quantity, "reference": args.ref})


@command("dispatch", "Stock", "Remove stock (goods shipped); refused if not enough stock",
         args=[arg("sku", help="product code"), arg("quantity", type=int, help="how many units are leaving"),
               arg("--ref", help="e.g. sales order number")],
         examples=["dispatch CBL-001 5 --ref SO-2001"], permission="stock:dispatch", writes=True)
def dispatch(session: Session, args) -> None:
    _write(session, args, "POST", f"/products/{args.sku}/dispatch", {"quantity": args.quantity, "reference": args.ref})


@command("adjust", "Stock", "Correct stock after a count (+ or - quantity, reason required)",
         args=[arg("sku", help="product code"), arg("change", type=int, help="e.g. 3 or -2"),
               arg("--reason", "-r", required=True, help="why the stock is being corrected")],
         examples=['adjust CBL-001 -2 --reason "damaged in storage"'], permission="stock:adjust", writes=True)
def adjust(session: Session, args) -> None:
    _write(session, args, "POST", f"/products/{args.sku}/adjust",
           {"quantity_change": args.change, "reason": args.reason})


# --- reports ------------------------------------------------------------------------


@command("history", "Reports", "Stock movements of one product (from the read model)",
         args=[arg("sku"), arg("--limit", type=int, default=50)],
         examples=["history CBL-001"], permission="inventory:read")
def history(session: Session, args) -> None:
    rows = session.api.query(f"/products/{args.sku}/history", limit=args.limit)
    session.console.print(_table(
        f"Stock history of {args.sku.upper()}", ["when", "movement", "change", "qty after", "ref/reason", "by"],
        [[_time(m["occurred_at"]), m["movement_type"], f"{m['quantity_change']:+d}", m["quantity_after"],
          m["reference"], m["performed_by"]] for m in rows],
        empty="no stock movements yet",
    ))


@command("low-stock", "Reports", "Products at or below their reorder level",
         examples=["low-stock"], permission="inventory:read")
def low_stock(session: Session, args) -> None:
    rows = session.api.query("/reports/low-stock")
    session.console.print(_table(
        "Low stock", ["SKU", "name", "qty", "reorder at", "shortfall"],
        [[r["sku"], r["name"], r["quantity"], r["reorder_level"], r["shortfall"]] for r in rows],
        empty="all products are above their reorder level",
    ))


@command("valuation", "Reports", "Stock value per category", permission="reports:read")
def valuation(session: Session, args) -> None:
    report = session.api.query("/reports/valuation")
    session.console.print(_table(
        "Stock valuation", ["category", "products", "units", "value"],
        [[c["category"], c["products"], c["units"], c["value"]] for c in report["categories"]],
        empty="no active products",
    ))
    session.console.print(f"[bold]total value:[/bold] {report['total_value']}")


# --- event sourcing -----------------------------------------------------------------


@command("stock-at", "Event sourcing", "Time travel: a product's state at a past moment, by replaying its events",
         args=[arg("sku"), arg("when", help="ISO time (2026-10-16T14:30) or relative (30s, 10m, 2h, 1d ago)")],
         examples=["stock-at CBL-001 10m", 'stock-at CBL-001 "2026-10-16 09:00"'], permission="inventory:read")
def stock_at(session: Session, args) -> None:
    when = _parse_when(args.when)
    p = session.api.query(f"/products/{args.sku}/as-of", at=when.isoformat())
    session.console.print(f"[bold]{p['sku']}[/bold] as of {_time(p['as_of'])} "
                          f"[dim](replayed {p['events_replayed']} events)[/dim]")
    for key in ("name", "unit_price", "quantity", "reorder_level", "status", "version"):
        session.console.print(f"  [cyan]{key:<14}[/cyan] {p[key]}")


@command("events", "Event sourcing", "Show the raw event log (the source of truth)",
         args=[arg("--stream", help="only one stream, e.g. product-CBL-001 or user-admin"),
               arg("--limit", type=int, default=20)],
         examples=["events", "events --stream product-CBL-001"], permission="events:read")
def events(session: Session, args) -> None:
    rows = session.api.query("/events", stream=args.stream, limit=args.limit)
    session.console.print(_table(
        "Event log", ["pos", "stream", "v", "event", "data", "by", "when"],
        [[e["global_position"], e["stream_id"], e["version"], e["event_type"],
          json.dumps(e["data"], separators=(",", ":")), e["metadata"].get("user"), _time(e["occurred_at"])]
         for e in rows],
        empty="no events",
    ))


@command("status", "Event sourcing", "How far the read model is behind the event store")
def status(session: Session, args) -> None:
    s = session.api.query("/status")
    colour = "green" if s["lag"] == 0 else "yellow"
    session.console.print(f"event store head: {s['head_position']}   projector checkpoint: {s['checkpoint']}   "
                          f"lag: [{colour}]{s['lag']} event(s)[/{colour}]")


# --- admin --------------------------------------------------------------------------


@command("users", "Admin", "List users", permission="users:manage")
def users(session: Session, args) -> None:
    rows = session.api.query("/users")
    session.console.print(_table(
        "Users", ["username", "role", "active", "created"],
        [[u["username"], u["role"], "yes" if u["active"] else "no", _time(u["created_at"])] for u in rows],
    ))


@command("user-add", "Admin", "Create a user with a role (admin, manager, clerk, viewer)",
         args=[arg("username"), arg("--role", required=True, choices=["admin", "manager", "clerk", "viewer"]),
               arg("--password", "-p", help="initial password (prompted if omitted)")],
         examples=["user-add nimal --role clerk"], permission="users:manage", writes=True)
def user_add(session: Session, args) -> None:
    password = args.password or Prompt.ask("password for new user", password=True, console=session.console)
    _write(session, args, "POST", "/users", {"username": args.username, "password": password, "role": args.role})


@command("user-role", "Admin", "Change a user's role",
         args=[arg("username"), arg("role", choices=["admin", "manager", "clerk", "viewer"])],
         examples=["user-role nimal manager"], permission="users:manage", writes=True)
def user_role(session: Session, args) -> None:
    _write(session, args, "POST", f"/users/{args.username}/role", {"role": args.role})


@command("user-deactivate", "Admin", "Block a user from logging in or acting",
         args=[arg("username")], examples=["user-deactivate nimal"], permission="users:manage", writes=True)
def user_deactivate(session: Session, args) -> None:
    _write(session, args, "POST", f"/users/{args.username}/deactivate", {})


@command("user-reactivate", "Admin", "Allow a deactivated user again",
         args=[arg("username")], examples=["user-reactivate nimal"], permission="users:manage", writes=True)
def user_reactivate(session: Session, args) -> None:
    _write(session, args, "POST", f"/users/{args.username}/reactivate", {})


@command("rebuild-projections", "Admin", "Wipe the read models and rebuild them by replaying every event",
         permission="projections:rebuild")
def rebuild_projections(session: Session, args) -> None:
    result = session.api.admin_post("/admin/rebuild-projections")
    session.console.print(f"[green]✔[/green] replayed {result['replayed_events']} events; "
                          f"checkpoint is now {result['checkpoint']}")


__all__ = ["ApiError", "ExitRepl"]
