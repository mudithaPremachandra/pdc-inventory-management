"""Drive the real CLI commands against the APIs, with the projector running in the background."""

from inventory.config import settings


def test_cli_session_end_to_end(cli):
    code, out = cli("products")
    assert code == 1 and "login" in out  # not logged in yet

    code, out = cli(f"login {settings.admin_username} --password {settings.admin_password}")
    assert code == 0 and "logged in as" in out

    code, out = cli('product-add CBL-001 "USB-C cable" --price 4.99 --reorder-level 20 --category cables')
    assert code == 0 and "ProductRegistered" in out and "read model updated" in out

    code, out = cli("receive CBL-001 50 --ref PO-1")
    assert code == 0 and "version 2" in out

    code, out = cli("dispatch CBL-001 80")
    assert code == 1 and "only 50 in stock" in out

    assert cli("dispatch CBL-001 35 --ref SO-1")[0] == 0

    code, out = cli("product CBL-001")
    assert "15" in out  # 50 - 35, already visible: the CLI waited for the projector

    code, out = cli("history CBL-001")
    assert "received" in out and "dispatched" in out and "-35" in out

    code, out = cli("low-stock")
    assert "CBL-001" in out

    code, out = cli("events --stream product-CBL-001")
    assert "StockDispatched" in out

    code, out = cli("stock-at CBL-001 1d")
    assert code == 1 and "did not exist" in out  # product is younger than a day

    code, out = cli("status")
    assert "lag" in out


def test_cli_user_management_and_forbidden_actions(cli):
    cli(f"login {settings.admin_username} --password {settings.admin_password}")
    assert cli("user-add nimal --role viewer --password secret99")[0] == 0
    code, out = cli("users")
    assert "nimal" in out and "viewer" in out

    cli("login nimal --password secret99")
    code, out = cli("whoami")
    assert "nimal" in out and "inventory:read" in out
    code, out = cli("product-add X-1 Thing --price 1 --reorder-level 0")
    assert code == 1 and "not allowed" in out


def test_cli_rebuild(cli):
    cli(f"login {settings.admin_username} --password {settings.admin_password}")
    cli("product-add RB-9 Thing --price 1 --reorder-level 0")
    code, out = cli("rebuild-projections")
    assert code == 0 and "replayed 2 events" in out

