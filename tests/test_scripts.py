"""Contracts: scripts backend shapes (dry_run without network) + existence."""

import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
ROOT = _HERE.parents[1]  # tests/test_scripts.py -> project root
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backends import scripts


def _capture(monkeypatch, result=None):
    seen = {}

    def fake(endpoint, payload, role="edit"):
        seen["endpoint"] = endpoint
        seen["payload"] = payload
        seen["role"] = role
        return result if result is not None else {"ok": True}

    monkeypatch.setattr(scripts, "proxy", fake)
    return seen


def test_functions_exist():
    for name in (
        "get_source",
        "set_source",
        "edit_lines",
        "insert_lines",
        "delete_lines",
        "grep",
        "find_replace",
    ):
        assert callable(getattr(scripts, name)), name


def test_set_source_dry_run_no_network(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("must not touch the network on dry_run")

    monkeypatch.setattr(scripts, "proxy", boom)
    result = scripts.set_source("ServerScriptService.Main", "print(1)")
    assert result == {
        "dry_run": True,
        "path": "ServerScriptService.Main",
        "would_set": "print(1)",
    }


def test_find_replace_dry_run_no_network(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("must not touch the network on dry_run")

    monkeypatch.setattr(scripts, "proxy", boom)
    result = scripts.find_replace("foo", "bar")
    assert result == {"dry_run": True, "pattern": "foo", "would_replace_with": "bar"}


def test_get_source_shape(monkeypatch):
    seen = _capture(monkeypatch)
    scripts.get_source("ServerScriptService.Main", 1, 5)
    assert seen["endpoint"] == "/api/get-script-source"
    assert seen["payload"] == {
        "instancePath": "ServerScriptService.Main",
        "startLine": 1,
        "endLine": 5,
    }


def test_set_source_live_shape(monkeypatch):
    seen = _capture(monkeypatch)
    scripts.set_source("ServerScriptService.Main", "print(1)", dry_run=False)
    assert seen["endpoint"] == "/api/set-script-source"
    assert seen["payload"] == {
        "instancePath": "ServerScriptService.Main",
        "source": "print(1)",
    }


def test_edit_lines_shape(monkeypatch):
    seen = _capture(monkeypatch)
    scripts.edit_lines("ServerScriptService.Main", "a", "b")
    assert seen["endpoint"] == "/api/edit-script-lines"
    assert seen["payload"] == {
        "instancePath": "ServerScriptService.Main",
        "old_string": "a",
        "new_string": "b",
    }
    scripts.edit_lines("ServerScriptService.Main", "a", "b", 3)
    assert seen["payload"]["startLine"] == 3


def test_insert_lines_shape(monkeypatch):
    seen = _capture(monkeypatch)
    scripts.insert_lines("ServerScriptService.Main", 2, "print(2)")
    assert seen["endpoint"] == "/api/insert-script-lines"
    assert seen["payload"] == {
        "instancePath": "ServerScriptService.Main",
        "afterLine": 2,
        "newContent": "print(2)",
    }


def test_delete_lines_shape(monkeypatch):
    seen = _capture(monkeypatch)
    scripts.delete_lines("ServerScriptService.Main", 1, 4)
    assert seen["endpoint"] == "/api/delete-script-lines"
    assert seen["payload"] == {
        "instancePath": "ServerScriptService.Main",
        "startLine": 1,
        "endLine": 4,
    }


def test_grep_shape(monkeypatch):
    seen = _capture(monkeypatch)
    scripts.grep("print", limit=5)
    assert seen["endpoint"] == "/api/grep-scripts"
    assert seen["payload"] == {"pattern": "print", "maxResults": 5}


def test_find_replace_live_shape(monkeypatch):
    seen = _capture(monkeypatch)
    scripts.find_replace("foo", "bar", dry_run=False)
    assert seen["endpoint"] == "/api/find-and-replace-in-scripts"
    assert seen["payload"] == {
        "pattern": "foo",
        "replacement": "bar",
        "dryRun": False,
    }


def test_bridge_error_shape(monkeypatch):
    def fail(*args, **kwargs):
        raise ValueError("no connected Studio peer")

    monkeypatch.setattr(scripts, "proxy", fail)
    result = scripts.grep("x")
    assert result["error"] == "bridge_error"
    assert "no connected Studio peer" in result["message"]
