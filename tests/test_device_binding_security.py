"""Execute the production binding SQL against isolated SQLite, never live D1."""

import re
import os
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def binding_sql():
    website_root = Path(os.environ.get("NEXUS_WEBSITE_SOURCE", str(Path(__file__).resolve().parents[2] / "website_NexusMC")))
    source = (website_root / "db/auth.ts").read_text(encoding="utf-8")
    body = source.split("export async function bindAccountDevice", 1)[1].split("\n}", 1)[0]
    statements = re.findall(r'prepare\("([^"]+)"\)', body)
    assert len(statements) == 1
    assert ".first<" in body and "return linked?.user_id === userId" in body
    return statements[0]


def database(path):
    connection = sqlite3.connect(path, isolation_level=None, timeout=10)
    connection.execute(
        "CREATE TABLE IF NOT EXISTS account_device_links "
        "(device_hash TEXT PRIMARY KEY,user_id TEXT,source TEXT,created_at INTEGER,last_seen_at INTEGER)"
    )
    return connection


def test_device_claim_only_one_concurrent_owner(tmp_path):
    path = tmp_path / "isolated.sqlite"
    database(path).close()
    sql = binding_sql()
    barrier = threading.Barrier(2)

    def claim(user):
        connection = sqlite3.connect(path, isolation_level=None, timeout=10)
        try:
            barrier.wait(timeout=5)
            result = connection.execute(sql, ("device", user, "launcher", 1, 1)).fetchall()
            return user, bool(result)
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, ["alice", "bob"]))
    assert sum(success for _, success in results) == 1
    connection = database(path)
    try:
        owner = connection.execute("SELECT user_id FROM account_device_links").fetchone()[0]
        assert (owner, True) in results
    finally:
        connection.close()


def test_same_owner_refresh_does_not_reassign_device():
    connection = database(":memory:")
    try:
        sql = binding_sql()
        assert connection.execute(sql, ("device", "alice", "launcher", 1, 1)).fetchall() == [("alice",)]
        assert connection.execute(sql, ("device", "alice", "launcher", 2, 2)).fetchall() == [("alice",)]
        assert connection.execute(sql, ("device", "bob", "launcher", 3, 3)).fetchall() == []
        assert connection.execute("SELECT user_id,created_at,last_seen_at FROM account_device_links").fetchall() == [
            ("alice", 1, 2)
        ]
    finally:
        connection.close()
