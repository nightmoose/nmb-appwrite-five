"""The optional direct-driver PostgreSQL path uses pg8000 (no network needed)."""
import sys
import types

from nmb_five.connectors import appwrite as aw


def test_pg8000_kwargs_parses_dsn():
    kw = aw._pg8000_kwargs("postgresql://admin:p%40ss@db-x.appwrite.center:6432/orders?sslmode=require")
    assert (kw["user"], kw["password"], kw["host"], kw["port"], kw["database"]) == (
        "admin", "p@ss", "db-x.appwrite.center", 6432, "orders")
    assert kw["ssl_context"] is not None
    assert "ssl_context" not in aw._pg8000_kwargs("postgresql://u@h/db?sslmode=disable")


def test_postgres_driver_path_uses_pg8000(monkeypatch):
    calls = {}

    class FakeConn:
        def cursor(self):
            raise AssertionError("not used in this test")

    def connect(**kw):
        calls.update(kw)
        return FakeConn()

    dbapi = types.ModuleType("pg8000.dbapi")
    dbapi.connect = connect
    pkg = types.ModuleType("pg8000")
    pkg.dbapi = dbapi
    monkeypatch.setitem(sys.modules, "pg8000", pkg)
    monkeypatch.setitem(sys.modules, "pg8000.dbapi", dbapi)
    monkeypatch.setenv("APPWRITE_SQL_TRANSPORT", "driver")
    monkeypatch.setenv("APPWRITE_POSTGRES_DSN", "postgresql://admin:pw@db-x.appwrite.center:5432/orders?sslmode=require")

    try:
        aw.PostgresConnector({})
    except AssertionError:
        pass  # connector may probe the cursor on init; the connect call is what we check
    assert calls["host"] == "db-x.appwrite.center" and calls["database"] == "orders"
