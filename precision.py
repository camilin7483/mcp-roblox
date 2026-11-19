"""Shared precision limits and bridge helpers for mcp-roblox."""

import json
import os
import urllib.request
from pathlib import Path

MAX_PARALLEL = 5
MAX_IMPORT_MB = 37.5
MICRO_PROF_MAX_S = 5
MEMORY_MAX_MB = 500
MAX_TEXT_LEN = 4096
MAX_EXEC_LEN = 16384
MAX_PROPERTIES = 50
ALLOWED_PARENTS = frozenset(
    {"Workspace", "ServerScriptService", "ReplicatedStorage", "StarterGui", "SoundService"}
)
BRIDGE_URL = "http://127.0.0.1:58741"
TOKEN_FILE = str(Path.home() / ".robloxstudio-mcp" / "auth-token")
BACKUP_DIR = str(Path.home() / ".cache" / "mcp-roblox" / "backups")


def ok(payload: dict) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False)


def err(code: str, message: str, details: dict | None = None) -> str:
    out: dict = {"error": code, "message": message}
    if details is not None:
        out["details"] = details
    return json.dumps(out, indent=2, ensure_ascii=False)


def load_bridge_config() -> tuple[str, str | None]:
    base_url = os.environ.get("ROBLOX_BRIDGE_URL", BRIDGE_URL)
    token_file = os.environ.get("ROBLOX_BRIDGE_TOKEN_FILE", TOKEN_FILE)
    # ponytail: loopback-only by default; set ROBLOX_BRIDGE_ALLOW_REMOTE=1 + https for remote.
    lowered = base_url.lower()
    is_loopback = (
        "127.0.0.1" in lowered or "localhost" in lowered or "[::1]" in lowered
    )
    if not is_loopback and os.environ.get("ROBLOX_BRIDGE_ALLOW_REMOTE") != "1":
        raise ValueError("bridge host not loopback; set ROBLOX_BRIDGE_ALLOW_REMOTE=1 for remote")
    if not lowered.startswith(("http://", "https://")):
        raise ValueError("bridge URL must be http(s)")
    try:
        token = Path(token_file).read_text(encoding="utf-8").strip() or None
    except OSError:
        token = None
    return base_url, token


def validate_text(value: str, name: str, limit: int = MAX_TEXT_LEN) -> str:
    if not value or not value.strip():
        raise ValueError(f"{name} must not be empty")
    if len(value) > limit:
        raise ValueError(f"{name} exceeds {limit} chars")
    return value.strip()


def validate_limit(limit: int) -> int:
    return max(1, min(50, int(limit)))


def validate_asset_id(asset_id: int) -> int:
    asset_id = int(asset_id)
    if asset_id <= 0:
        raise ValueError("asset_id must be positive")
    return asset_id


def validate_parent(parent: str) -> str:
    if parent not in ALLOWED_PARENTS:
        raise ValueError(f"parent must be one of {sorted(ALLOWED_PARENTS)}")
    return parent


def bridge_post(endpoint: str, payload: dict, timeout: int = 20) -> dict:
    import urllib.error

    base_url, token = load_bridge_config()
    url = base_url.rstrip("/") + endpoint
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        # The bridge answers 400 + JSON (e.g. missing_ready_fields on
        # /ready) while up; surface the body instead of only raising.
        try:
            parsed = json.loads(exc.read().decode("utf-8"))
        except (ValueError, OSError):
            raise ValueError(f"bridge HTTP {exc.code}") from exc
        if isinstance(parsed, dict):
            parsed["_http_status"] = exc.code
            return parsed
        raise ValueError(f"bridge HTTP {exc.code}") from exc
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid bridge response: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("invalid bridge response: expected object")
    return parsed


def ensure_backup_dir() -> str:
    path = Path(BACKUP_DIR)
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        path.chmod(0o700)
    except OSError:
        pass
    return BACKUP_DIR


def get_status() -> dict:
    """No-auth bridge status: pluginConnected, versions, instances."""
    base_url, _ = load_bridge_config()
    url = base_url.rstrip("/") + "/status"
    with urllib.request.urlopen(url, timeout=5) as resp:
        parsed = json.loads(resp.read().decode("utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("invalid status response")
    return parsed


def get_topology() -> dict:
    base_url, token = load_bridge_config()
    url = base_url.rstrip("/") + "/topology"
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=5) as resp:
        parsed = json.loads(resp.read().decode("utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("invalid topology response")
    return parsed


def pick_peer(role: str = "edit") -> dict:
    """Pick a connected Studio peer, preferring the given role."""
    topo = get_topology()
    peers = topo.get("peers") or []
    for peer in peers:
        if peer.get("role") == role and peer.get("peerId"):
            return peer
    for peer in peers:
        if peer.get("peerId"):
            if role != "edit":
                raise ValueError(f'no connected peer with role "{role}"')
            return peer
    raise ValueError("no connected Studio peer (open Studio + press Connect)")


def proxy(endpoint: str, data: dict, role: str = "edit", timeout: int = 30) -> dict:
    """Send one request through the bridge WS queue via POST /proxy."""
    peer = pick_peer(role)
    parsed = bridge_post(
        "/proxy",
        {"endpoint": endpoint, "data": data, "targetPeerId": peer["peerId"]},
        timeout=timeout,
    )
    if isinstance(parsed, dict) and "response" in parsed:
        response = parsed["response"]
        return response if isinstance(response, dict) else {"result": response}
    return parsed
