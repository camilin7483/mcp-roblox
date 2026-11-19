#!/usr/bin/env python3
"""mcp-roblox — Roblox Studio autonomous gateway (FastMCP stdio server)."""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

# Ensure `import precision` and `from backends.world import ...` both work
# whether the server is run as `python3 server.py` or `python3 -m server`
# from its own directory or elsewhere.
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    from mcp.server.mcpserver import MCPServer as FastMCP  # mcp 2.x fallback

import autonomy
import planner
import precision
import verifier
from backends import inspect as insp
from backends import official, runtime, scripts, toolbox, world
from backends import advanced as adv

try:
    from precision import (
        MAX_EXEC_LEN,
        validate_asset_id,
        validate_limit,
        validate_parent,
        validate_text,
    )
except ImportError:  # pragma: no cover - precision is required in practice
    MAX_EXEC_LEN = 16384

    def validate_text(v, n, limit=4096):
        return v.strip()

    def validate_limit(l):
        return max(1, min(50, int(l)))

    def validate_asset_id(a):
        return int(a)

    def validate_parent(p):
        return p

try:
    mcp = FastMCP(
        "roblox",
        instructions="Roblox Studio autonomous gateway — Explorer, Scripts, Toolbox, playtest, verify",
    )
except TypeError:
    mcp = FastMCP("roblox")


@mcp.tool()
def roblox_status() -> str:
    """Bridge + plugin status and effective env config."""
    try:
        bridge_url, _ = precision.load_bridge_config()
        return precision.ok(
            {
                "bridge": autonomy.health(),
                "plugin": autonomy.ensure_plugin(),
                "bridge_url": bridge_url,
                "token_file": os.environ.get(
                    "ROBLOX_BRIDGE_TOKEN_FILE", precision.TOKEN_FILE
                ),
                "plugins_dir": os.environ.get("MCP_PLUGINS_DIR", ""),
            }
        )
    except Exception as exc:
        return precision.err("status_error", str(exc))


@mcp.tool()
def roblox_ensure_ready(auto_launch: bool = False) -> str:
    """Plugin + bridge readiness (never launches processes)."""
    try:
        return precision.ok(autonomy.ensure_ready(auto_launch=auto_launch))
    except Exception as exc:
        return precision.err("ready_error", str(exc))


@mcp.tool()
def roblox_plan(intent: str) -> str:
    """Deterministic ordered step list for an edit intent."""
    try:
        return precision.ok(planner.build_plan(intent))
    except Exception as exc:
        return precision.err("plan_error", str(exc))


@mcp.tool()
def roblox_search(query: str, scope: str = "game") -> str:
    """Search instances in the open Studio place."""
    try:
        query = validate_text(query, "query")
        return precision.ok(world.search(query, scope))
    except Exception as exc:
        return precision.err("search_error", str(exc))


@mcp.tool()
def roblox_read(instance_path: str) -> str:
    """Read properties of one instance by path."""
    try:
        instance_path = validate_text(instance_path, "instance_path", 512)
        return precision.ok(world.read(instance_path))
    except Exception as exc:
        return precision.err("read_error", str(exc))


@mcp.tool()
def roblox_edit(instance_path: str, properties: dict | None = None, dry_run: bool = True) -> str:
    """Set instance properties. Dry-run by default; back up first for real edits."""
    try:
        instance_path = validate_text(instance_path, "instance_path", 512)
        props = properties or {}
        if len(props) > precision.MAX_PROPERTIES:
            raise ValueError("too many properties")
        result = world.set_properties(instance_path, props, dry_run=dry_run)
        if dry_run:
            result = {**result, "hint": "re-run with dry_run=False after roblox_backup"}
        return precision.ok(result)
    except Exception as exc:
        return precision.err("edit_error", str(exc))


@mcp.tool()
def roblox_exec(source: str, domain: str = "edit", confirm: bool = False) -> str:
    """Execute Luau in edit/server/client domain."""
    try:
        if len(source) > MAX_EXEC_LEN:
            raise ValueError(f"source exceeds {MAX_EXEC_LEN} chars")
        if domain in ("server", "client") and not confirm:
            return precision.err(
                "confirm_required",
                "server/client execution needs confirm=True",
            )
        result = official.execute_luau(source, domain)
        if isinstance(result, dict) and "error" in result:
            return precision.err(result.get("error", "exec_error"), result.get("message", ""), result)
        return precision.ok(result)
    except Exception as exc:
        return precision.err("exec_error", str(exc))


@mcp.tool()
def roblox_build(prompt: str) -> str:
    """Generate a model from a text prompt via the bridge."""
    try:
        prompt = validate_text(prompt, "prompt")
        result = official.generate_model(prompt)
        if isinstance(result, dict) and "error" in result:
            return precision.err(result.get("error", "build_error"), result.get("message", ""), result)
        return precision.ok(result)
    except Exception as exc:
        return precision.err("build_error", str(exc))


@mcp.tool()
def roblox_toolbox(
    query: str = "",
    limit: int = 10,
    preview_id: int = 0,
    insert_ids: list | None = None,
    parent: str = "Workspace",
) -> str:
    """Toolbox gateway: insert ids, preview one asset, or search by query."""
    try:
        parent = validate_parent(parent)
        if insert_ids:
            ids = [validate_asset_id(i) for i in insert_ids]
            result = toolbox.insert_bulk(ids, parent)
            if result.get("skipped"):
                result["warning"] = f"{len(result['skipped'])} ids skipped (max 5 per call)"
            result["hint"] = "preview each asset before inserting untrusted content"
            return precision.ok(result)
        if preview_id:
            return precision.ok(toolbox.preview(validate_asset_id(preview_id)))
        return precision.ok(
            toolbox.search_assets(validate_text(query or "model", "query"), validate_limit(limit))
        )
    except Exception as exc:
        return precision.err("toolbox_error", str(exc))


@mcp.tool()
def roblox_playtest(instance_id: str = "", cursor: str = "") -> str:
    """Screenshot + runtime logs, then verify verdict."""
    try:
        shot = official.screenshot()
        logs = official.get_logs(instance_id, cursor)
        if isinstance(shot, dict) and "error" in shot:
            return precision.err("bridge_error", shot.get("message", ""), shot)
        if isinstance(logs, dict) and "error" in logs:
            return precision.err("bridge_error", logs.get("message", ""), logs)
        logs_text = json.dumps(logs, ensure_ascii=False)
        verdict = verifier.decide(logs_text, scene_ok=True, screenshot_ok=True)
        return precision.ok({"screenshot": shot, "logs": logs, "verdict": verdict})
    except Exception as exc:
        return precision.err("playtest_error", str(exc))


@mcp.tool()
def roblox_profile(memory_mb: float = 0, micro_s: float = 0) -> str:
    """Flag profiler readings over budget."""
    try:
        return precision.ok(verifier.check_profilers(memory_mb, micro_s))
    except Exception as exc:
        return precision.err("profile_error", str(exc))


@mcp.tool()
def roblox_backup() -> str:
    """Save current project structure to a dated JSON file."""
    try:
        backup_dir = precision.ensure_backup_dir()
        structure = world.get_structure()
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        path = Path(backup_dir) / f"structure-{stamp}.json"
        if path.exists():
            return precision.err("backup_error", "timestamp collision, retry")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(structure, fh, indent=2, ensure_ascii=False)
        try:
            path.chmod(0o600)
        except OSError:
            pass
        return precision.ok({"path": str(path), "backup_dir": backup_dir})
    except Exception as exc:
        return precision.err("backup_error", str(exc))


def main():
    mcp.run()


def _wrap(result, err_code: str) -> str:
    if isinstance(result, dict) and "error" in result:
        return precision.err(
            result.get("error", err_code), result.get("message", ""), result
        )
    return precision.ok(result)


@mcp.tool()
def roblox_script_get(instance_path: str, start: int = 0, end: int = 0) -> str:
    """Get script source, optionally a line range."""
    try:
        return _wrap(
            scripts.get_source(validate_text(instance_path, "instance_path", 512), start, end),
            "script_error",
        )
    except Exception as exc:
        return precision.err("script_error", str(exc))


@mcp.tool()
def roblox_script_set(instance_path: str, source: str, dry_run: bool = True) -> str:
    """Set script source. Dry-run by default."""
    try:
        if len(source) > MAX_EXEC_LEN:
            raise ValueError(f"source exceeds {MAX_EXEC_LEN} chars")
        return _wrap(
            scripts.set_source(validate_text(instance_path, "instance_path", 512), source, dry_run),
            "script_error",
        )
    except Exception as exc:
        return precision.err("script_error", str(exc))


@mcp.tool()
def roblox_script_edit(instance_path: str, old_string: str, new_string: str, start_line: int = 0) -> str:
    """Replace first occurrence of old_string in a script."""
    try:
        return _wrap(
            scripts.edit_lines(validate_text(instance_path, "instance_path", 512), old_string, new_string, start_line),
            "script_error",
        )
    except Exception as exc:
        return precision.err("script_error", str(exc))


@mcp.tool()
def roblox_script_lines(instance_path: str, action: str = "insert", start_line: int = 0, end_line: int = 0, content: str = "") -> str:
    """Insert (after start_line) or delete (start_line..end_line) script lines."""
    try:
        path = validate_text(instance_path, "instance_path", 512)
        if action == "delete":
            result = scripts.delete_lines(path, start_line, end_line)
        else:
            result = scripts.insert_lines(path, start_line, content)
        return _wrap(result, "script_error")
    except Exception as exc:
        return precision.err("script_error", str(exc))


@mcp.tool()
def roblox_grep(pattern: str, limit: int = 20) -> str:
    """Grep script sources across the place."""
    try:
        return _wrap(scripts.grep(validate_text(pattern, "pattern"), validate_limit(limit)), "search_error")
    except Exception as exc:
        return precision.err("search_error", str(exc))


@mcp.tool()
def roblox_replace(pattern: str, replacement: str, dry_run: bool = True) -> str:
    """Find and replace across scripts. Dry-run by default."""
    try:
        return _wrap(
            scripts.find_replace(validate_text(pattern, "pattern"), replacement, dry_run),
            "search_error",
        )
    except Exception as exc:
        return precision.err("search_error", str(exc))


@mcp.tool()
def roblox_place() -> str:
    """Place info: id, name, data model."""
    try:
        return _wrap(insp.place_info(), "place_error")
    except Exception as exc:
        return precision.err("place_error", str(exc))


@mcp.tool()
def roblox_tree(path: str = "game") -> str:
    """Project structure / file tree."""
    try:
        if path == "game":
            return _wrap(insp.structure(), "tree_error")
        return _wrap(insp.file_tree(validate_text(path, "path", 512)), "tree_error")
    except Exception as exc:
        return precision.err("tree_error", str(exc))


@mcp.tool()
def roblox_attrs(instance_path: str) -> str:
    """Get instance attributes."""
    try:
        return _wrap(insp.attributes(validate_text(instance_path, "instance_path", 512)), "read_error")
    except Exception as exc:
        return precision.err("read_error", str(exc))


@mcp.tool()
def roblox_selection(paths: list | None = None) -> str:
    """Get selection, or set it when paths are given."""
    try:
        if paths:
            return _wrap(insp.selection_set(list(paths)), "edit_error")
        return _wrap(insp.selection_get(), "read_error")
    except Exception as exc:
        return precision.err("selection_error", str(exc))


@mcp.tool()
def roblox_class(class_name: str) -> str:
    """Class info: properties and events."""
    try:
        return _wrap(insp.class_info(validate_text(class_name, "class_name", 128)), "read_error")
    except Exception as exc:
        return precision.err("read_error", str(exc))


@mcp.tool()
def roblox_export(instance_path: str, output: str = "") -> str:
    """Export instance to .rbxm file (0600)."""
    try:
        return _wrap(
            insp.export_rbxm(validate_text(instance_path, "instance_path", 512), output or None),
            "export_error",
        )
    except Exception as exc:
        return precision.err("export_error", str(exc))


@mcp.tool()
def roblox_import(file: str, parent: str = "Workspace") -> str:
    """Import .rbxm file (max 37.5MB)."""
    try:
        return _wrap(insp.import_rbxm(validate_text(file, "file", 1024), validate_parent(parent)), "import_error")
    except Exception as exc:
        return precision.err("import_error", str(exc))


@mcp.tool()
def roblox_capture(kind: str = "scene", seconds: float = 5) -> str:
    """scene | memory | script-profiler | micro-profiler."""
    try:
        kind = kind.lower()
        if kind == "memory":
            return _wrap(insp.memory(), "profile_error")
        if kind == "script":
            return _wrap(insp.script_profiler(min(15.0, seconds)), "profile_error")
        if kind == "micro":
            return _wrap(insp.micro_profiler(min(5.0, seconds)), "profile_error")
        return _wrap(insp.scene_analysis(), "profile_error")
    except Exception as exc:
        return precision.err("profile_error", str(exc))


@mcp.tool()
def roblox_solo(mode: str = "play") -> str:
    """Start/stop solo playtest: mode play|stop."""
    try:
        if mode == "stop":
            return _wrap(runtime.playtest_stop(), "playtest_error")
        return _wrap(runtime.playtest_start(mode), "playtest_error")
    except Exception as exc:
        return precision.err("playtest_error", str(exc))


@mcp.tool()
def roblox_multiplayer(action: str = "state", players: int = 2) -> str:
    """Multiplayer playtest: start|add|leave|end|state."""
    try:
        action = action.lower()
        if action == "start":
            return _wrap(runtime.multiplayer_start(max(1, min(8, players))), "playtest_error")
        if action == "add":
            return _wrap(runtime.multiplayer_add_players(max(1, players)), "playtest_error")
        if action == "leave":
            return _wrap(runtime.multiplayer_leave(""), "playtest_error")
        if action == "end":
            return _wrap(runtime.multiplayer_end("ended_by_mcp"), "playtest_error")
        return _wrap(runtime.multiplayer_state(), "playtest_error")
    except Exception as exc:
        return precision.err("playtest_error", str(exc))


@mcp.tool()
def roblox_breakpoints(action: str = "list", data: dict | None = None) -> str:
    """List/set/clear script breakpoints."""
    try:
        return _wrap(runtime.breakpoints(action, data or {}), "exec_error")
    except Exception as exc:
        return precision.err("exec_error", str(exc))


@mcp.tool()
def roblox_input(kind: str = "mouse", action: str = "click", x: int = 0, y: int = 0, key: str = "") -> str:
    """Simulate mouse/keyboard input in Studio."""
    try:
        if kind == "keyboard":
            return _wrap(runtime.input_keyboard(key, action), "input_error")
        return _wrap(runtime.input_mouse(action, x, y), "input_error")
    except Exception as exc:
        return precision.err("input_error", str(exc))


@mcp.tool()
def roblox_docs(name: str, category: str = "classes") -> str:
    """Roblox engine reference docs (public, no Studio needed)."""
    try:
        return _wrap(adv.get_roblox_doc(validate_text(name, "name", 128), validate_text(category, "category", 64)), "docs_error")
    except Exception as exc:
        return precision.err("docs_error", str(exc))


@mcp.tool()
def roblox_network(profile: str = "default") -> str:
    """Set playtest network profile via Luau."""
    try:
        return _wrap(adv.set_network_profile(validate_text(profile, "profile", 64)), "network_error")
    except Exception as exc:
        return precision.err("network_error", str(exc))


@mcp.tool()
def roblox_device(action: str = "state", device: str = "") -> str:
    """Device simulator state/set."""
    try:
        if action == "set":
            return _wrap(adv.set_device_simulator("edit", device), "device_error")
        return _wrap(adv.get_device_simulator_state("edit", device or None), "device_error")
    except Exception as exc:
        return precision.err("device_error", str(exc))


if __name__ == "__main__":
    main()
