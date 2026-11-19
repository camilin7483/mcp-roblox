"""Contracts: runtime backend shapes without touching the network."""

import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve()
ROOT = _HERE.parents[1]  # tests/test_runtime.py -> project root
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backends import runtime

_FUNCTIONS = [
    "playtest_start",
    "playtest_stop",
    "multiplayer_start",
    "multiplayer_add_players",
    "multiplayer_leave",
    "multiplayer_end",
    "multiplayer_state",
    "breakpoints",
    "input_mouse",
    "input_keyboard",
    "focus_viewport",
]


def _offline(monkeypatch):
    def _raise(*args, **kwargs):
        raise ValueError("no connected Studio peer (open Studio + press Connect)")

    monkeypatch.setattr(runtime, "proxy", _raise)


@pytest.mark.parametrize("name", _FUNCTIONS)
def test_functions_exist(name):
    assert callable(getattr(runtime, name, None))


@pytest.mark.parametrize("name", _FUNCTIONS)
def test_bridge_error_shape_without_network(monkeypatch, name):
    _offline(monkeypatch)
    fn = getattr(runtime, name)
    kwargs = {"path": "game.Workspace.Part"} if name == "focus_viewport" else {}
    assert fn(**kwargs)["error"] == "bridge_error"


def test_bridge_error_carries_message(monkeypatch):
    _offline(monkeypatch)
    result = runtime.playtest_start()
    assert result["error"] == "bridge_error"
    assert "no connected Studio peer" in result["message"]


def test_invalid_args_do_not_hit_bridge(monkeypatch):
    def _boom(*args, **kwargs):  # pragma: no cover - must not be called
        raise AssertionError("proxy must not be called for invalid args")

    monkeypatch.setattr(runtime, "proxy", _boom)
    assert runtime.playtest_start(mode="bogus")["error"] == "invalid_arg"
    assert runtime.multiplayer_start(player_count=0)["error"] == "invalid_arg"
    assert runtime.multiplayer_add_players(count=99)["error"] == "invalid_arg"
    assert runtime.breakpoints(action="bogus")["error"] == "invalid_arg"
    assert runtime.focus_viewport()["error"] == "invalid_arg"
