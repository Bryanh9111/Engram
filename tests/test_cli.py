"""Tests for Engram CLI."""

import json
import subprocess
import sys

import pytest


def run_cli(*args, env_db=None):
    """Run engram CLI and return result."""
    cmd = [sys.executable, "-m", "engram.cli"] + list(args)
    env = None
    if env_db:
        import os
        env = {**os.environ, "ENGRAM_DB": env_db}
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    return result


class TestCLI:
    def test_add_memory(self, tmp_path):
        db = str(tmp_path / "test.db")
        result = run_cli(
            "add",
            "Money values must use integer cents",
            "--kind", "constraint",
            "--project", "payments",
            env_db=db,
        )
        assert result.returncode == 0
        assert "remembered" in result.stdout.lower() or "id" in result.stdout.lower()

    def test_search_memory(self, tmp_path):
        db = str(tmp_path / "test.db")
        # Add first
        run_cli("add", "Redis must be seeded before tests", "--kind", "procedure", env_db=db)
        # Search
        result = run_cli("search", "Redis", env_db=db)
        assert result.returncode == 0
        assert "Redis" in result.stdout

    def test_forget_memory(self, tmp_path):
        db = str(tmp_path / "test.db")
        # Add and capture ID
        add_result = run_cli("add", "Temporary fact", "--kind", "fact", env_db=db)
        # Parse ID from output
        output = add_result.stdout.strip()
        # Search to get results
        search_result = run_cli("search", "Temporary", "--json", env_db=db)
        memories = json.loads(search_result.stdout)
        mem_id = memories[0]["id"]

        forget_result = run_cli("forget", mem_id, env_db=db)
        assert forget_result.returncode == 0

    def test_stats(self, tmp_path):
        db = str(tmp_path / "test.db")
        run_cli("add", "Test memory", "--kind", "fact", env_db=db)
        result = run_cli("stats", env_db=db)
        assert result.returncode == 0
        assert "total" in result.stdout.lower() or "1" in result.stdout

    def test_candidates(self, tmp_path):
        db = str(tmp_path / "test.db")
        result = run_cli("candidates", env_db=db)
        assert result.returncode == 0

    def test_search_json_output(self, tmp_path):
        db = str(tmp_path / "test.db")
        run_cli("add", "Test fact for JSON", "--kind", "fact", env_db=db)
        result = run_cli("search", "JSON", "--json", env_db=db)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert isinstance(data, list)

    def test_add_with_path_scope(self, tmp_path):
        db = str(tmp_path / "test.db")
        result = run_cli(
            "add",
            "Never use floats for money",
            "--kind", "constraint",
            "--path-scope", "billing/*",
            env_db=db,
        )
        assert result.returncode == 0

    def test_add_with_tags(self, tmp_path):
        db = str(tmp_path / "test.db")
        result = run_cli(
            "add",
            "Use Redis for caching",
            "--kind", "decision",
            "--tag", "redis",
            "--tag", "caching",
            env_db=db,
        )
        assert result.returncode == 0

    def test_dashboard(self, tmp_path):
        db = str(tmp_path / "test.db")
        run_cli("add", "Test constraint", "--kind", "constraint", "--project", "demo", env_db=db)
        run_cli("add", "Test fact", "--kind", "fact", env_db=db)
        result = run_cli("dashboard", env_db=db)
        assert result.returncode == 0
        assert "Engram" in result.stdout
        assert "constraint" in result.stdout
        assert "fact" in result.stdout
