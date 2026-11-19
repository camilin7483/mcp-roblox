"""Inspect/read-only backend: place info, structure, selection, rbxm, class info, diagnostics.

Source of truth: @chrrxs/robloxstudio-mcp dist/index.js. All endpoints used
below were verified there: /api/place-info ({}), /api/project-structure
({path, maxDepth, scriptsOnly}), /api/file-tree ({path}),
/api/get-attributes ({instancePath}), /api/get-selection ({}),
/api/set-selection ({paths, mode}), /api/export-rbxm ({instance_paths} ->
{base64, instance_count}), /api/import-rbxm ({base64, parent_path,
source_label}), /api/class-info ({className}), /api/get-scene-analysis
({mode, topN, raw}), /api/get-memory-breakdown ({tags}),
/api/capture-script-profiler ({duration_ms, ...}, max 15s),
/api/capture-micro-profiler ({duration_ms, ...}, max 5s). None omitted.

Simplifications vs upstream: project-structure optional filters
(path/maxDepth/scriptsOnly) not exposed; scene/memory single-peer calls
instead of target=all fan-out; import supports a local file only (upstream
also accepts url/base64 sources with a 50MB cap — here capped at
precision.MAX_IMPORT_MB); profilers target the server peer (edit invalid).
"""

import base64
import os
from pathlib import Path

from precision import MAX_IMPORT_MB, MICRO_PROF_MAX_S, proxy

_MAX_IMPORT_BYTES = int(MAX_IMPORT_MB * 1024 * 1024)
_SCRIPT_PROF_MAX_S = 15  # upstream capture_script_profiler schema maximum


def _call(endpoint: str, payload: dict, role: str = "edit", timeout: int = 30) -> dict:
    try:
        return proxy(endpoint, payload, role=role, timeout=timeout)
    except Exception as exc:  # ValueError when no peer; surface as data
        return {"error": "bridge_error", "message": str(exc)}


def place_info() -> dict:
    return _call("/api/place-info", {})


def structure() -> dict:
    return _call("/api/project-structure", {})


def file_tree(path: str = "game") -> dict:
    return _call("/api/file-tree", {"path": path})


def attributes(path: str) -> dict:
    if not path or not str(path).strip():
        return {"error": "invalid_path", "message": "path must not be empty"}
    return _call("/api/get-attributes", {"instancePath": path})


def selection_get() -> dict:
    return _call("/api/get-selection", {}, role="edit")


def selection_set(paths: list) -> dict:
    if not isinstance(paths, list) or any(
        not isinstance(p, str) or not p.strip() for p in paths
    ):
        return {"error": "invalid_paths", "message": "paths must be a list of non-empty strings"}
    return _call("/api/set-selection", {"paths": paths, "mode": "set"}, role="edit")


def export_rbxm(path: str, output_path: str | None = None) -> dict:
    if not path or not str(path).strip():
        return {"error": "invalid_path", "message": "path must not be empty"}
    resp = _call("/api/export-rbxm", {"instance_paths": [path]})
    if not isinstance(resp, dict) or resp.get("error"):
        return resp
    payload = resp.get("base64")
    if not payload:
        return {"error": "bridge_error", "message": "plugin returned no base64 payload"}
    try:
        raw = base64.b64decode(payload)
    except Exception as exc:
        return {"error": "bridge_error", "message": f"base64 decode failed: {exc}"}
    dest = output_path or f"{str(path).split('.')[-1].split('/')[-1] or 'export'}.rbxm"
    try:
        target = Path(dest)
        if str(target.parent) not in (".", ""):
            target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        os.chmod(target, 0o600)
    except OSError as exc:
        return {"error": "write_error", "message": f"failed to write {dest}: {exc}"}
    return {
        "bytes_written": len(raw),
        "instance_count": resp.get("instance_count", 1),
        "output_path": str(dest),
    }


def import_rbxm(file: str, parent: str = "Workspace") -> dict:
    if not parent or not str(parent).strip():
        return {"error": "invalid_parent", "message": "parent must not be empty"}
    try:
        size = os.path.getsize(file)
    except OSError as exc:
        return {"error": "read_error", "message": f"failed to read {file}: {exc}"}
    if size > _MAX_IMPORT_BYTES:
        return {
            "error": "import_too_large",
            "message": f"file exceeds {MAX_IMPORT_MB}MB cap",
            "size": size,
        }
    try:
        raw = Path(file).read_bytes()
    except OSError as exc:
        return {"error": "read_error", "message": f"failed to read {file}: {exc}"}
    if len(raw) > _MAX_IMPORT_BYTES:
        return {
            "error": "import_too_large",
            "message": f"file exceeds {MAX_IMPORT_MB}MB cap",
            "size": len(raw),
        }
    encoded = base64.b64encode(raw).decode("ascii")
    return _call(
        "/api/import-rbxm",
        {"base64": encoded, "parent_path": parent, "source_label": str(file)},
    )


def class_info(class_name: str) -> dict:
    if not class_name or not str(class_name).strip():
        return {"error": "invalid_class", "message": "class_name must not be empty"}
    return _call("/api/class-info", {"className": class_name})


def scene_analysis() -> dict:
    return _call("/api/get-scene-analysis", {})


def memory() -> dict:
    return _call("/api/get-memory-breakdown", {})


def script_profiler(seconds: int = 5) -> dict:
    if not isinstance(seconds, (int, float)) or seconds <= 0 or seconds > _SCRIPT_PROF_MAX_S:
        return {
            "error": "invalid_duration",
            "message": f"seconds must be within (0, {_SCRIPT_PROF_MAX_S}]",
            "seconds": seconds,
        }
    return _call(
        "/api/capture-script-profiler",
        {"duration_ms": int(seconds * 1000)},
        role="server",
        timeout=30 + int(seconds),
    )


def micro_profiler(seconds: int = 1) -> dict:
    if not isinstance(seconds, (int, float)) or seconds <= 0 or seconds > MICRO_PROF_MAX_S:
        return {
            "error": "invalid_duration",
            "message": f"seconds must be within (0, {MICRO_PROF_MAX_S}]",
            "seconds": seconds,
        }
    return _call(
        "/api/capture-micro-profiler",
        {"duration_ms": int(seconds * 1000)},
        role="server",
        timeout=30 + int(seconds),
    )
