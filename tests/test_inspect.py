"""Contracts: inspect backend error mapping, limits, and rbxm file handling."""

import base64
import os
import stat
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
ROOT = _HERE.parents[1]  # tests/test_inspect.py -> project root
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backends import inspect as inspect_backend


def _no_peer(monkeypatch):
    def _raise(*args, **kwargs):
        raise ValueError("no connected Studio peer (open Studio + press Connect)")

    monkeypatch.setattr(inspect_backend, "proxy", _raise)


def test_bridge_value_error_becomes_error_dict(monkeypatch, tmp_path):
    _no_peer(monkeypatch)
    small = tmp_path / "a.rbxm"
    small.write_bytes(b"RBXM")
    cases = [
        inspect_backend.place_info(),
        inspect_backend.structure(),
        inspect_backend.file_tree(),
        inspect_backend.attributes("Workspace.Part"),
        inspect_backend.selection_get(),
        inspect_backend.selection_set(["Workspace.Part"]),
        inspect_backend.export_rbxm("Workspace.Part", str(tmp_path / "o.rbxm")),
        inspect_backend.import_rbxm(str(small)),
        inspect_backend.class_info("Part"),
        inspect_backend.scene_analysis(),
        inspect_backend.memory(),
        inspect_backend.script_profiler(),
        inspect_backend.micro_profiler(),
    ]
    assert cases, "expected calls to run"
    for result in cases:
        assert result["error"] == "bridge_error"
        assert result["message"]


def test_micro_profiler_rejects_over_5s_without_network(monkeypatch):
    def _fail(*args, **kwargs):
        raise AssertionError("must reject before touching the bridge")

    monkeypatch.setattr(inspect_backend, "proxy", _fail)
    for seconds in (6, 60, 5.5):
        result = inspect_backend.micro_profiler(seconds=seconds)
        assert result["error"] == "invalid_duration"


def test_micro_profiler_max_ok_sends_duration_ms(monkeypatch):
    seen = {}

    def _ok(endpoint, data, role="edit", timeout=30):
        seen.update(endpoint=endpoint, data=data, role=role)
        return {"ok": True}

    monkeypatch.setattr(inspect_backend, "proxy", _ok)
    assert inspect_backend.micro_profiler(seconds=5) == {"ok": True}
    assert seen["endpoint"] == "/api/capture-micro-profiler"
    assert seen["data"] == {"duration_ms": 5000}


def test_import_rejects_over_37_5mb_without_network(monkeypatch, tmp_path):
    def _fail(*args, **kwargs):
        raise AssertionError("must reject before touching the bridge")

    monkeypatch.setattr(inspect_backend, "proxy", _fail)
    small = tmp_path / "a.rbxm"
    small.write_bytes(b"RBXM")
    monkeypatch.setattr(os.path, "getsize", lambda _: int(37.5 * 1024 * 1024) + 1)
    result = inspect_backend.import_rbxm(str(small))
    assert result["error"] == "import_too_large"


def test_import_small_file_sends_base64(monkeypatch, tmp_path):
    seen = {}

    def _ok(endpoint, data, role="edit", timeout=30):
        seen.update(endpoint=endpoint, data=data, role=role)
        return {"imported": True}

    monkeypatch.setattr(inspect_backend, "proxy", _ok)
    src = tmp_path / "a.rbxm"
    src.write_bytes(b"RBXM-DATA")
    result = inspect_backend.import_rbxm(str(src))
    assert result == {"imported": True}
    assert seen["endpoint"] == "/api/import-rbxm"
    assert seen["role"] == "edit"
    assert seen["data"]["parent_path"] == "Workspace"
    assert base64.b64decode(seen["data"]["base64"]) == b"RBXM-DATA"


def test_export_writes_file_with_mode_0600(monkeypatch, tmp_path):
    blob = b"RBXM-EXPORT"

    def _ok(endpoint, data, role="edit", timeout=30):
        assert data == {"instance_paths": ["Workspace.Part"]}
        return {"base64": base64.b64encode(blob).decode("ascii"), "instance_count": 1}

    monkeypatch.setattr(inspect_backend, "proxy", _ok)
    dest = tmp_path / "part.rbxm"
    result = inspect_backend.export_rbxm("Workspace.Part", str(dest))
    assert result["bytes_written"] == len(blob)
    assert dest.read_bytes() == blob
    assert stat.S_IMODE(os.stat(dest).st_mode) == 0o600


def test_export_missing_base64_is_bridge_error(monkeypatch, tmp_path):
    monkeypatch.setattr(inspect_backend, "proxy", lambda *a, **k: {"ok": True})
    result = inspect_backend.export_rbxm("Workspace.Part", str(tmp_path / "o.rbxm"))
    assert result["error"] == "bridge_error"


def test_selection_set_rejects_bad_paths_without_network(monkeypatch):
    def _fail(*args, **kwargs):
        raise AssertionError("must reject before touching the bridge")

    monkeypatch.setattr(inspect_backend, "proxy", _fail)
    assert inspect_backend.selection_set("Workspace")["error"] == "invalid_paths"
    assert inspect_backend.selection_set(["", 1])["error"] == "invalid_paths"
