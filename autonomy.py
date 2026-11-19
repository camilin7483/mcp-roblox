"""Bridge/plugin readiness checks (never launches processes)."""

import os
from pathlib import Path

from precision import get_status


_DOWN_HINT = "open Studio + check MCPPlugin.rbxmx version match, reopen Studio"
_DEFAULT_PLUGINS_DIR = str(
    Path.home()
    / ".local/share/vinegar/prefixes/studio/drive_c/users"
    / os.environ.get("USER", "cam")
    / "AppData/Local/Roblox/Plugins"
)
_VINEGAR_CMD = "vinegar studio"


def _ready_get() -> dict | None:
    # Legacy GET fallback (pre-3.x bridges); current bridges use /status.
    return None


def health() -> dict:
    try:
        status = get_status()
    except Exception:
        return {"bridge": "down", "hint": _DOWN_HINT}
    if not status.get("pluginConnected"):
        return {
            "bridge": "up",
            "plugin_connected": False,
            "hint": "bridge is up but Studio plugin is not connected; reopen Studio",
        }
    return {
        "bridge": "up",
        "plugin_connected": True,
        "peers": status.get("peerCount", 0),
        "server_version": status.get("serverVersion"),
    }


def ensure_plugin() -> dict:
    plugins_dir = os.environ.get("MCP_PLUGINS_DIR", _DEFAULT_PLUGINS_DIR)
    path = os.path.join(plugins_dir, "MCPPlugin.rbxmx")
    if not os.path.exists(path):
        return {"installed": False, "path": path, "size_bytes": 0}
    try:
        size = os.path.getsize(path)
    except OSError:
        return {"installed": False, "path": path, "size_bytes": 0}
    return {"installed": size > 0, "path": path, "size_bytes": size}


def ensure_ready(auto_launch: bool = False) -> dict:
    plugin = ensure_plugin()
    bridge = health()
    ready = bool(plugin.get("installed")) and bridge.get("bridge") == "up"
    out: dict = {"ready": ready, "plugin": plugin, "bridge": bridge}
    if auto_launch and not ready:
        out["hint"] = (
            "auto_launch requested but no processes are launched automatically; "
            f"start Studio manually, e.g. `{_VINEGAR_CMD}`"
        )
    return out
