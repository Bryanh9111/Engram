"""API surface coverage invariant test.

Every user-settable column in the `memories` schema MUST be exposed through
all four write surfaces:
    1. MemoryStore.remember
    2. engram.server._handle_remember
    3. MCP `remember` tool (FastMCP-registered)
    4. CLI `engram add` argparse parser

Computed-internal columns (auto-derived, lifecycle-managed) are whitelisted
in `docs/non-exposed-schema-fields.md`. This test reads that whitelist as
the source of truth.

Drift modes this test catches:
    - A new schema column is added without updating any/all four surfaces
    - A column is reclassified as user-settable but a surface is not updated
    - The whitelist doc references a column that no longer exists in schema
"""

from __future__ import annotations

import argparse
import inspect
import os
import re
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
WHITELIST_DOC = REPO_ROOT / "docs" / "non-exposed-schema-fields.md"


# --- Fixtures -------------------------------------------------------------


@pytest.fixture(scope="module")
def schema_columns() -> set[str]:
    """Actual columns in the `memories` table."""
    from engram.db import init_db

    conn = init_db(":memory:")
    cols = {row[1] for row in conn.execute("PRAGMA table_info(memories)")}
    conn.close()
    return cols


@pytest.fixture(scope="module")
def whitelist() -> set[str]:
    r"""Parse the non-exposed-schema-fields.md markdown table.

    Rows are of the form ``| `field_name` | ... |`` — we grab the first
    backticked identifier in each row.
    """
    assert WHITELIST_DOC.exists(), f"Whitelist doc missing: {WHITELIST_DOC}"
    text = WHITELIST_DOC.read_text()
    fields: set[str] = set()
    for line in text.splitlines():
        m = re.match(r"^\|\s*`([a-z_]+)`\s*\|", line)
        if m:
            fields.add(m.group(1))
    assert fields, "Whitelist doc has no table rows matching | `field` | ..."
    return fields


@pytest.fixture(scope="module")
def user_settable(schema_columns, whitelist) -> set[str]:
    """Columns that must appear in every write surface."""
    return schema_columns - whitelist


@pytest.fixture(scope="module")
def mcp_remember_params() -> set[str]:
    """Parameters advertised by the MCP `remember` tool (FastMCP schema)."""
    os.environ["ENGRAM_DB"] = tempfile.mktemp(suffix=".db")
    from engram.server import create_server

    server = create_server()
    tool = server._tool_manager.get_tool("remember")
    assert tool is not None, "MCP `remember` tool not registered"
    return set(tool.parameters["properties"].keys())


@pytest.fixture(scope="module")
def cli_add_params() -> set[str]:
    """Argparse `dest` names for the `engram add` subcommand."""
    from engram.cli import build_parser

    parser = build_parser()
    sub_actions = [
        a for a in parser._actions if isinstance(a, argparse._SubParsersAction)
    ]
    assert sub_actions, "CLI has no subparsers"
    add_parser = sub_actions[0].choices["add"]
    dests = {a.dest for a in add_parser._actions if a.dest != "help"}
    return dests


# --- Invariants -----------------------------------------------------------


class TestWhitelistIntegrity:
    """The whitelist doc must match actual schema — no ghost or missing entries."""

    def test_whitelist_is_subset_of_schema(self, schema_columns, whitelist):
        extra = whitelist - schema_columns
        assert not extra, (
            f"Whitelist references fields that don't exist in schema: {extra}. "
            f"Either rename the column or remove from {WHITELIST_DOC.name}."
        )

    def test_whitelist_is_nonempty(self, whitelist):
        # Sanity: auto-derived fields like `id` and `created_at` must be listed.
        assert {"id", "created_at", "status"} <= whitelist


class TestStoreRememberSurface:
    """`MemoryStore.remember` kwargs must cover every user-settable field."""

    def test_signature_covers_user_settable(self, user_settable):
        from engram.store import MemoryStore

        sig = inspect.signature(MemoryStore.remember)
        params = set(sig.parameters) - {"self"}
        missing = user_settable - params
        assert not missing, (
            f"MemoryStore.remember is missing kwargs for user-settable "
            f"columns: {missing}"
        )


class TestHandleRememberSurface:
    """`_handle_remember` mediates between MCP tool and store — same coverage."""

    def test_signature_covers_user_settable(self, user_settable):
        from engram.server import _handle_remember

        sig = inspect.signature(_handle_remember)
        params = set(sig.parameters) - {"store"}
        missing = user_settable - params
        assert not missing, (
            f"engram.server._handle_remember is missing kwargs for "
            f"user-settable columns: {missing}"
        )


class TestMCPRememberToolSurface:
    """FastMCP-registered `remember` tool advertises every user-settable field."""

    def test_advertises_user_settable(self, mcp_remember_params, user_settable):
        missing = user_settable - mcp_remember_params
        assert not missing, (
            f"MCP `remember` tool is missing arguments for user-settable "
            f"columns: {missing}. Update the inner function signature in "
            f"engram.server.create_server."
        )


class TestCLIAddSurface:
    """`engram add` argparse parser exposes every user-settable field as arg."""

    def test_parser_covers_user_settable(self, cli_add_params, user_settable):
        missing = user_settable - cli_add_params
        assert not missing, (
            f"`engram add` CLI is missing arguments for user-settable "
            f"columns: {missing}. Add them to engram.cli.build_parser."
        )


class TestCrossSurfaceConsistency:
    """The four surfaces should declare the same set of user-settable fields
    (modulo surface-specific extras like MemoryStore's internal-use-only kwargs).
    """

    def test_surfaces_agree_on_user_settable(
        self,
        user_settable,
        mcp_remember_params,
        cli_add_params,
    ):
        from engram.server import _handle_remember
        from engram.store import MemoryStore

        store_params = set(inspect.signature(MemoryStore.remember).parameters) - {"self"}
        handle_params = set(inspect.signature(_handle_remember).parameters) - {"store"}

        surfaces = {
            "MemoryStore.remember": store_params,
            "_handle_remember": handle_params,
            "mcp.remember tool": mcp_remember_params,
            "cli.add": cli_add_params,
        }
        gaps = {
            name: user_settable - params
            for name, params in surfaces.items()
            if user_settable - params
        }
        assert not gaps, (
            "Write surface drift: the following surfaces are missing "
            f"user-settable fields — {gaps}"
        )
