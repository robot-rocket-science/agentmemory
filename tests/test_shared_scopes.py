"""Tests for cross-project shared scope functionality (Exp 97/98)."""

from __future__ import annotations

from pathlib import Path

import pytest

import agentmemory.shared_scopes as ss
from agentmemory.shared_scopes import (
    attach_shared_scopes,
    detach_shared_scopes,
    ensure_scope_db,
    get_scope_db_path,
    get_scopes_config,
    get_scopes_for_project,
    list_scopes,
    save_scopes_config,
    search_attached_scope,
    search_shared_scopes,
    share_belief,
    subscribe_project,
    unshare_belief,
    unsubscribe_project,
)


@pytest.fixture
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect shared scope paths to tmp for test isolation."""
    monkeypatch.setattr(ss, "_AGENTMEMORY_HOME", tmp_path)
    monkeypatch.setattr(ss, "_SHARED_DIR", tmp_path / "shared")
    monkeypatch.setattr(ss, "_SCOPES_CONFIG", tmp_path / "scopes.json")
    return tmp_path


class TestScopeManagement:
    def test_ensure_scope_db_creates_db(self, isolated_home: Path) -> None:
        db_path: Path = ensure_scope_db("infra")
        assert db_path.exists()
        assert db_path.parent.name == "infra"

    def test_list_scopes_empty(self, isolated_home: Path) -> None:
        assert list_scopes() == []

    def test_list_scopes_after_create(self, isolated_home: Path) -> None:
        ensure_scope_db("infra")
        ensure_scope_db("deploy")
        assert list_scopes() == ["deploy", "infra"]

    def test_get_scope_db_path(self, isolated_home: Path) -> None:
        path: Path = get_scope_db_path("infra")
        assert path == isolated_home / "shared" / "infra" / "memory.db"


class TestScopesConfig:
    def test_empty_config(self, isolated_home: Path) -> None:
        assert get_scopes_config() == {}

    def test_save_and_load(self, isolated_home: Path) -> None:
        config: dict[str, list[str]] = {"infra": ["/a", "/b"]}
        save_scopes_config(config)
        assert get_scopes_config() == config

    def test_subscribe_project(self, isolated_home: Path) -> None:
        proj: str = str(isolated_home / "myproject")
        subscribe_project("infra", proj)
        config: dict[str, list[str]] = get_scopes_config()
        assert len(config["infra"]) == 1

    def test_subscribe_idempotent(self, isolated_home: Path) -> None:
        proj: str = str(isolated_home / "myproject")
        subscribe_project("infra", proj)
        subscribe_project("infra", proj)
        config: dict[str, list[str]] = get_scopes_config()
        assert len(config["infra"]) == 1

    def test_unsubscribe_project(self, isolated_home: Path) -> None:
        proj_a: str = str(isolated_home / "proj_a")
        proj_b: str = str(isolated_home / "proj_b")
        subscribe_project("infra", proj_a)
        subscribe_project("infra", proj_b)
        unsubscribe_project("infra", proj_a)
        config: dict[str, list[str]] = get_scopes_config()
        assert len(config["infra"]) == 1

    def test_unsubscribe_removes_empty_scope(self, isolated_home: Path) -> None:
        proj: str = str(isolated_home / "proj")
        subscribe_project("infra", proj)
        unsubscribe_project("infra", proj)
        config: dict[str, list[str]] = get_scopes_config()
        assert "infra" not in config

    def test_get_scopes_for_project(self, isolated_home: Path) -> None:
        proj: str = str(isolated_home / "proj")
        other: str = str(isolated_home / "other")
        subscribe_project("infra", proj)
        subscribe_project("deploy", proj)
        subscribe_project("other", other)
        scopes: list[str] = get_scopes_for_project(proj)
        assert sorted(scopes) == ["deploy", "infra"]


class TestShareBelief:
    def test_share_and_search(self, isolated_home: Path) -> None:
        ensure_scope_db("infra")
        share_belief(
            scope_name="infra",
            belief_id="aaa111bbb222",
            content="Deploy to production via deploy.sh",
            belief_type="procedural",
            source_type="user_stated",
            alpha=5.0,
            beta_param=1.0,
            locked=True,
            origin_project="/home/user/proj",
        )
        results = search_shared_scopes(["infra"], "deploy production")
        assert len(results) == 1
        assert results[0][1] == "aaa111bbb222"

    def test_dedup_by_content_hash(self, isolated_home: Path) -> None:
        ensure_scope_db("infra")
        id1: str = share_belief(
            scope_name="infra",
            belief_id="aaa111bbb222",
            content="Same content here",
            belief_type="factual",
            source_type="agent_inferred",
            alpha=0.5,
            beta_param=0.5,
            locked=False,
            origin_project="/proj",
        )
        id2: str = share_belief(
            scope_name="infra",
            belief_id="ccc333ddd444",
            content="Same content here",
            belief_type="factual",
            source_type="agent_inferred",
            alpha=0.5,
            beta_param=0.5,
            locked=False,
            origin_project="/proj",
        )
        assert id1 == id2

    def test_unshare_belief(self, isolated_home: Path) -> None:
        ensure_scope_db("infra")
        share_belief(
            scope_name="infra",
            belief_id="aaa111bbb222",
            content="Removable belief",
            belief_type="factual",
            source_type="agent_inferred",
            alpha=0.5,
            beta_param=0.5,
            locked=False,
            origin_project="/proj",
        )
        assert unshare_belief("infra", "aaa111bbb222")
        results = search_shared_scopes(["infra"], "removable")
        assert len(results) == 0

    def test_unshare_nonexistent(self, isolated_home: Path) -> None:
        ensure_scope_db("infra")
        assert not unshare_belief("infra", "nonexistent_id")

    def test_search_nonexistent_scope(self, isolated_home: Path) -> None:
        results = search_shared_scopes(["doesnotexist"], "anything")
        assert results == []


class TestAttachSearch:
    def test_attach_and_search(self, isolated_home: Path) -> None:
        import sqlite3

        # Create shared scope with content
        ensure_scope_db("infra")
        share_belief(
            scope_name="infra",
            belief_id="infra_001",
            content="Rollback procedure: git revert HEAD",
            belief_type="procedural",
            source_type="user_stated",
            alpha=5.0,
            beta_param=1.0,
            locked=True,
            origin_project="/proj",
        )

        # Create a local DB and attach
        local_db: Path = isolated_home / "local.db"
        conn: sqlite3.Connection = sqlite3.connect(str(local_db))
        conn.execute(
            "CREATE VIRTUAL TABLE search_index USING fts5(id, content, type)"
        )
        conn.execute(
            "INSERT INTO search_index VALUES ('local1', 'Local pytest fixture', 'belief')"
        )
        conn.commit()

        aliases: list[str] = attach_shared_scopes(conn, ["infra"])
        assert aliases == ["shared_infra"]

        # Search the attached scope
        results = search_attached_scope(conn, "shared_infra", "rollback procedure")
        assert len(results) == 1
        assert results[0][0] == "infra_001"

        # Local search still works
        local_results = conn.execute(
            "SELECT id FROM main.search_index WHERE search_index MATCH 'pytest'"
        ).fetchall()
        assert len(local_results) == 1

        detach_shared_scopes(conn, aliases)
        conn.close()

    def test_attach_nonexistent_scope(self, isolated_home: Path) -> None:
        import sqlite3

        local_db: Path = isolated_home / "local.db"
        conn: sqlite3.Connection = sqlite3.connect(str(local_db))
        aliases: list[str] = attach_shared_scopes(conn, ["nonexistent"])
        assert aliases == []
        conn.close()

    def test_budget_limit(self, isolated_home: Path) -> None:

        ensure_scope_db("infra")
        # Add 10 beliefs
        for i in range(10):
            share_belief(
                scope_name="infra",
                belief_id=f"bulk_{i:03d}",
                content=f"Server configuration item number {i}",
                belief_type="factual",
                source_type="agent_inferred",
                alpha=0.5,
                beta_param=0.5,
                locked=False,
                origin_project="/proj",
            )

        # Search with budget=3
        results = search_shared_scopes(["infra"], "server configuration", budget_per_scope=3)
        assert len(results) <= 3
