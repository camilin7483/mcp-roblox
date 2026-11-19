"""Advanced backend: docs, simulation, device, instances (plain dicts).

Verified against @chrrxs/robloxstudio-mcp 3.1.0 dist/index.js. Only what
exists there is implemented, with the same mechanisms:
- get_roblox_docs: public HTTPS GET on
  https://create.roblox.com/docs/reference/engine/{category}/{name}.md
  (Accept markdown, 15s timeout, 50k char cap, ## section extract).
- get_roblox_skills: LOCAL installed Studio Assistant.rbxm bundle
  (ROBLOX_STUDIO_ASSISTANT_BUNDLE override or Studio install search).
  The binary rbxm parse is not ported here; bundle resolution is exact.
- set_network_profile / get_simulation_state / reset_simulation_state /
  set_device_simulator / get_device_simulator_state: NO dedicated /api
  endpoints exist; the bridge runs generated Luau through
  /api/execute-luau against NetworkSettings / StudioDeviceSimulatorService.
  This module builds equivalent Luau with the same keys and validation.
- manage_instance (launch|authorize|complete|close|status|
  list_place_versions): EXISTS. Only list_place_versions is portable: Open
  Cloud REST GET https://apis.roblox.com/assets/v1/assets/{id}/versions
  with x-api-key. launch/authorize/complete/close/status manage local OS
  processes (StudioInstanceManager), no bridge endpoint: not in backend.
- get_place_info: EXISTS via proxy /api/place-info.

Not in 3.1.0 (48 tools, no match): manage_monetization, any monetization
or game-pass/developer-product endpoint.
"""

import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from precision import proxy

DOC_CATEGORIES = ("classes", "enums", "datatypes", "libraries", "globals")
DOCS_BASE_URL = "https://create.roblox.com/docs/reference/engine"
DOCS_TIMEOUT_S = 15
MAX_DOC_CHARS = 50000

NETWORK_PROFILE_KEYS = (
    "InboundNetworkMinDelayMs",
    "OutboundNetworkMinDelayMs",
    "InboundNetworkJitterMs",
    "OutboundNetworkJitterMs",
    "InboundNetworkLossPercent",
    "OutboundNetworkLossPercent",
)
NETWORK_PROFILES = {
    "great": {
        "InboundNetworkMinDelayMs": 15,
        "OutboundNetworkMinDelayMs": 15,
        "InboundNetworkJitterMs": 0,
        "OutboundNetworkJitterMs": 0,
        "InboundNetworkLossPercent": 0,
        "OutboundNetworkLossPercent": 0,
    },
    "good": {
        "InboundNetworkMinDelayMs": 50,
        "OutboundNetworkMinDelayMs": 50,
        "InboundNetworkJitterMs": 10,
        "OutboundNetworkJitterMs": 10,
        "InboundNetworkLossPercent": 0,
        "OutboundNetworkLossPercent": 0,
    },
    "poor": {
        "InboundNetworkMinDelayMs": 150,
        "OutboundNetworkMinDelayMs": 150,
        "InboundNetworkJitterMs": 100,
        "OutboundNetworkJitterMs": 100,
        "InboundNetworkLossPercent": 0.5,
        "OutboundNetworkLossPercent": 0.5,
    },
}
ZERO_NETWORK_PROFILE = {key: 0 for key in NETWORK_PROFILE_KEYS}
MAX_NETWORK_PACKET_LOSS_PERCENT = 0.5

OPEN_CLOUD_BASE = "https://apis.roblox.com"
OPEN_CLOUD_KEY_ENV = "ROBLOX_OPEN_CLOUD_API_KEY"
OPEN_CLOUD_TIMEOUT_S = 30

SKILLS_BUNDLE_ENV = "ROBLOX_STUDIO_ASSISTANT_BUNDLE"

MAX_DEVICE_MATRIX_ENTRIES = 6

PERSISTENCE_NOTES = (
    "Normal Play client changes can write back to edit state.",
    "Multiplayer clients inherit baseline at startup but are isolated afterward.",
    "StudioTestService client device simulator state may appear stale on fresh "
    "clients, so reset after client startup is required.",
)

_CLIENT_RE = re.compile(r"^client-\d+$")
_VERSION_RE = re.compile(r"/versions/(\d+)$")


def _call(endpoint: str, payload: dict, role: str = "edit") -> dict:
    try:
        return proxy(endpoint, payload, role=role)
    except Exception as exc:
        return {"error": "bridge_error", "message": str(exc)}


def _invalid(message: str) -> dict:
    return {"error": "invalid_argument", "message": message}


# --- Docs (public HTTPS, no bridge, no key) ---


def _doc_url(category: str, name: str) -> str:
    return f"{DOCS_BASE_URL}/{category}/{urllib.parse.quote(name)}.md"


def _list_sections(markdown: str) -> list:
    return [m.group(1) for m in re.finditer(r"^##\s+(.+?)\s*$", markdown, re.M)][:200]


def _extract_section(markdown: str, section: str) -> str | None:
    lines = markdown.split("\n")
    wanted = section.strip().lower()
    start = next(
        (
            i
            for i, line in enumerate(lines)
            if (m := re.match(r"^##\s+(.+?)\s*$", line))
            and m.group(1).lower() == wanted
        ),
        -1,
    )
    if start == -1:
        return None
    end = next(
        (i for i in range(start + 1, len(lines)) if re.match(r"^##?\s+", lines[i])),
        len(lines),
    )
    return "\n".join(lines[start:end]).rstrip()


def get_roblox_doc(
    name: str, doc_type: str = "classes", section: str | None = None
) -> dict:
    if not name or not name.strip():
        return _invalid('get_roblox_docs requires a name (e.g. "ProximityPrompt")')
    category = doc_type or "classes"
    if category not in DOC_CATEGORIES:
        return _invalid(
            f'Invalid doc_type "{category}". '
            f"Valid categories: {', '.join(DOC_CATEGORIES)}"
        )
    url = _doc_url(category, name.strip())
    req = urllib.request.Request(url, headers={"Accept": "text/markdown, text/plain"})
    try:
        with urllib.request.urlopen(req, timeout=DOCS_TIMEOUT_S) as resp:
            markdown = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return {"error": "doc_not_found", "name": name, "doc_type": category}
        return {"error": "docs_error", "message": f"HTTP {exc.code}"}
    except Exception as exc:
        return {"error": "docs_error", "message": str(exc)}
    sections = _list_sections(markdown)
    if section:
        extracted = _extract_section(markdown, section)
        if extracted is None:
            return {
                "error": "section_not_found",
                "name": name,
                "section": section,
                "sections": sections,
            }
        markdown = extracted
    truncated = len(markdown) > MAX_DOC_CHARS
    return {
        "name": name.strip(),
        "doc_type": category,
        "content": markdown[:MAX_DOC_CHARS],
        "truncated": truncated,
        "sections": sections,
    }


# --- Skills (local bundle file, no HTTP) ---


def resolve_assistant_bundle_path() -> str:
    override = os.environ.get(SKILLS_BUNDLE_ENV)
    if override:
        if not Path(override).exists():
            raise FileNotFoundError(
                f"{SKILLS_BUNDLE_ENV} does not exist: {override}"
            )
        return override
    raise FileNotFoundError(
        "Studio Assistant bundle not found. Set "
        f"{SKILLS_BUNDLE_ENV} to the installed Assistant.rbxm path."
    )


def _bundle_metadata(path: str) -> dict:
    raw = Path(path).read_bytes()
    stat = Path(path).stat()
    match = re.search(r"version-[a-z0-9]+", path, re.I)
    return {
        "source": "installed-studio-assistant",
        "bundlePath": path,
        "bundleSha256": hashlib.sha256(raw).hexdigest(),
        "studioVersion": match.group(0) if match else None,
        "bundleSize": stat.st_size,
    }


def list_skills() -> dict:
    try:
        path = resolve_assistant_bundle_path()
    except FileNotFoundError as exc:
        return {"error": "skills_unavailable", "message": str(exc)}
    return {
        **_bundle_metadata(path),
        "error": "skills_unavailable",
        "message": "Assistant.rbxm binary skill parse is not ported to this backend",
    }


def get_skill(name: str) -> dict:
    if not name or not name.strip():
        return _invalid('get_roblox_skills action="get" requires a skill name')
    result = list_skills()
    return {**result, "requested": name.strip()}


# --- Network profiles (Luau via /api/execute-luau, no dedicated endpoint) ---


def normalize_network_profile(profile: str, overrides: dict | None) -> dict:
    if profile not in ("great", "good", "poor", "custom"):
        raise ValueError('profile must be "great", "good", "poor", or "custom"')
    values = {} if profile == "custom" else dict(NETWORK_PROFILES[profile])
    if overrides is not None:
        if not isinstance(overrides, dict) or isinstance(overrides, list):
            raise ValueError("overrides must be an object when provided")
        allowed = set(NETWORK_PROFILE_KEYS)
        for key, value in overrides.items():
            if key not in allowed:
                raise ValueError(
                    f'Unsupported network override "{key}". '
                    f"Allowed: {', '.join(NETWORK_PROFILE_KEYS)}"
                )
            if not isinstance(value, (int, float)) or value != value:
                raise ValueError(f'Network override "{key}" must be a finite number')
            if value < 0:
                raise ValueError(
                    f'Network override "{key}" must be greater than or equal to 0'
                )
            if key.endswith("LossPercent") and value > MAX_NETWORK_PACKET_LOSS_PERCENT:
                raise ValueError(
                    f'Network override "{key}" cannot exceed '
                    f"{MAX_NETWORK_PACKET_LOSS_PERCENT}; Roblox engine limits "
                    "packet loss simulation to 0.5%."
                )
            values[key] = value
    if not values:
        raise ValueError("custom profile requires at least one override")
    return values


def _network_apply_luau(profile: str, values: dict) -> str:
    return (
        'local HttpService = game:GetService("HttpService")\n'
        'local ns = settings():GetService("NetworkSettings")\n'
        f"local keys = HttpService:JSONDecode({json.dumps(json.dumps(list(NETWORK_PROFILE_KEYS)))})\n"
        f"local desired = HttpService:JSONDecode({json.dumps(json.dumps(values))})\n"
        "local before = {}\n"
        "for _, key in ipairs(keys) do\n\tbefore[key] = ns[key]\nend\n"
        "for key, value in pairs(desired) do\n\tns[key] = value\nend\n"
        "local after = {}\n"
        "for _, key in ipairs(keys) do\n\tafter[key] = ns[key]\nend\n"
        "return HttpService:JSONEncode({\n"
        f"\tprofile = {json.dumps(profile)},\n"
        "\tapplied = desired,\n\tbefore = before,\n\tafter = after,\n})"
    )


def _network_state_luau(operation: str) -> str:
    return (
        'local HttpService = game:GetService("HttpService")\n'
        'local ns = settings():GetService("NetworkSettings")\n'
        f"local operation = {json.dumps(operation)}\n"
        f"local keys = HttpService:JSONDecode({json.dumps(json.dumps(list(NETWORK_PROFILE_KEYS)))})\n"
        f"local resetValues = HttpService:JSONDecode({json.dumps(json.dumps(ZERO_NETWORK_PROFILE))})\n"
        "local function readState()\n\tlocal state = {}\n"
        "\tfor _, key in ipairs(keys) do\n\t\tstate[key] = ns[key]\n\tend\n"
        "\treturn state\nend\n"
        'if operation == "get" then\n'
        "\treturn HttpService:JSONEncode({\n\t\tsuccess = true,\n\t\tstate = readState(),\n\t})\nend\n"
        'if operation == "reset" then\n\tlocal before = readState()\n'
        "\tfor key, value in pairs(resetValues) do\n\t\tns[key] = value\n\tend\n"
        "\treturn HttpService:JSONEncode({\n\t\tsuccess = true,\n"
        "\t\tapplied = resetValues,\n\t\tbefore = before,\n\t\tafter = readState(),\n\t})\nend\n"
        'error("Unsupported network simulation operation: " .. tostring(operation), 0)'
    )


def set_network_profile(
    profile: str, target: str = "client-1", overrides: dict | None = None
) -> dict:
    try:
        values = normalize_network_profile(profile, overrides)
    except ValueError as exc:
        return _invalid(str(exc))
    selected = target or "client-1"
    if selected != "all-clients" and not _CLIENT_RE.match(selected):
        return _invalid(
            f'set_network_profile target must be "client-N" or "all-clients" '
            f"(got: {selected})"
        )
    if selected == "all-clients":
        return {
            "error": "unsupported_target",
            "message": "all-clients fan-out needs multi-peer routing; "
            "call once per client-N",
        }
    code = _network_apply_luau(profile, values)
    result = _call("/api/execute-luau", {"code": code}, role=selected)
    if "error" in result:
        return result
    return {
        "profile": profile,
        "target": selected,
        "applied": values,
        "targets": {selected: result},
    }


# --- Device simulator (Luau via /api/execute-luau, no dedicated endpoint) ---


def normalize_device_settings(
    device_id: str | None = None,
    orientation: str | None = None,
    resolution: dict | None = None,
    pixel_density: float | None = None,
    scaling_mode: str | None = None,
) -> dict:
    settings: dict = {}
    if device_id is not None:
        if not isinstance(device_id, str) or not device_id.strip():
            raise ValueError("deviceId must be a non-empty string")
        settings["deviceId"] = device_id
    if orientation is not None:
        if not isinstance(orientation, str) or not orientation.strip():
            raise ValueError("orientation must be a non-empty string")
        settings["orientation"] = orientation
    if resolution is not None:
        if not isinstance(resolution, dict):
            raise ValueError(
                "resolution must be an object with positive integer width and height"
            )
        width, height = resolution.get("width"), resolution.get("height")
        if (
            not isinstance(width, int)
            or not isinstance(height, int)
            or width <= 0
            or height <= 0
        ):
            raise ValueError(
                "resolution.width and resolution.height must be positive integers"
            )
        settings["resolution"] = {"width": width, "height": height}
    if pixel_density is not None:
        if (
            not isinstance(pixel_density, (int, float))
            or pixel_density != pixel_density
            or pixel_density <= 0
        ):
            raise ValueError("pixelDensity must be a positive finite number")
        settings["pixelDensity"] = pixel_density
    if scaling_mode is not None:
        if not isinstance(scaling_mode, str) or not scaling_mode.strip():
            raise ValueError("scalingMode must be a non-empty string")
        settings["scalingMode"] = scaling_mode
    return settings


def _device_luau(operation: str, options: dict) -> str:
    opts = json.dumps({"operation": operation, **options})
    return (
        'local HttpService = game:GetService("HttpService")\n'
        'local simulator = game:GetService("StudioDeviceSimulatorService")\n'
        f"local opts = HttpService:JSONDecode({json.dumps(opts)})\n"
        "local function plain(value)\n"
        '\tlocal t = typeof(value)\n'
        '\tif t == "Vector2" then\n'
        "\t\treturn { x = value.X, y = value.Y, width = value.X, height = value.Y }\n\tend\n"
        '\tif t == "EnumItem" then\n\t\treturn value.Name\n\tend\n'
        '\tif type(value) == "table" then\n\t\tlocal out = {}\n'
        "\t\tfor k, v in pairs(value) do\n\t\t\tout[tostring(k)] = plain(v)\n\t\tend\n"
        "\t\treturn out\n\tend\n\treturn value\nend\n"
        "local function readState(includeList)\n"
        '\tlocal id = tostring(simulator:GetDeviceAsync())\n'
        "\tlocal state = { activeDeviceId = id, isSimulating = id ~= \"default\" }\n"
        "\tif includeList then\n"
        "\t\tlocal ok, list = pcall(function() return simulator:GetDeviceListAsync() end)\n"
        "\t\tif ok then state.devices = plain(list) end\n\tend\n"
        "\tif state.isSimulating then\n"
        "\t\tlocal getters = { resolution = \"GetResolutionAsync\", "
        "pixelDensity = \"GetPixelDensityAsync\", "
        "orientation = \"GetOrientationAsync\", scalingMode = \"GetScalingModeAsync\" }\n"
        "\t\tfor key, fn in pairs(getters) do\n"
        "\t\t\tlocal ok, v = pcall(function() return simulator[fn](simulator) end)\n"
        "\t\t\tif ok then state[key] = plain(v) end\n\t\tend\n\tend\n"
        "\treturn state\nend\n"
        'if opts.operation == "get" then\n'
        "\treturn readState(opts.includeDeviceList ~= false)\nend\n"
        'if opts.operation == "set" then\n'
        "\tlocal before = readState(false)\n\tlocal applied\n"
        "\tif opts.stopSimulation == true then\n"
        "\t\tsimulator:StopSimulationAsync()\n"
        "\t\tapplied = { stopSimulation = true }\n\telse\n"
        "\t\tapplied = {}\n\t\tlocal s = opts.settings or {}\n"
        "\t\tif s.deviceId ~= nil then\n"
        "\t\t\tsimulator:SetDeviceAsync(s.deviceId)\n"
        "\t\t\tapplied.deviceId = s.deviceId\n\t\tend\n"
        "\t\tif s.orientation ~= nil then\n"
        "\t\t\tlocal item = Enum.ScreenOrientation[s.orientation]\n"
        "\t\t\tassert(item, \"unknown orientation: \" .. tostring(s.orientation))\n"
        "\t\t\tsimulator:SetOrientationAsync(item)\n"
        "\t\t\tapplied.orientation = s.orientation\n\t\tend\n"
        "\t\tif s.resolution ~= nil then\n"
        "\t\t\tsimulator:SetResolutionAsync(s.resolution.width, s.resolution.height)\n"
        "\t\t\tapplied.resolution = s.resolution\n\t\tend\n"
        "\t\tif s.pixelDensity ~= nil then\n"
        "\t\t\tsimulator:SetPixelDensityAsync(s.pixelDensity)\n"
        "\t\t\tapplied.pixelDensity = s.pixelDensity\n\t\tend\n"
        "\t\tif s.scalingMode ~= nil then\n"
        "\t\t\tlocal item = Enum.DeviceSimulatorScalingMode[s.scalingMode]\n"
        "\t\t\tassert(item, \"unknown scalingMode: \" .. tostring(s.scalingMode))\n"
        "\t\t\tsimulator:SetScalingModeAsync(item)\n"
        "\t\t\tapplied.scalingMode = s.scalingMode\n\t\tend\n"
        "\tend\n"
        "\treturn { success = true, applied = applied, before = before, after = readState(false) }\nend\n"
        'error("Unsupported device simulator operation: " .. tostring(opts.operation), 0)'
    )


def get_device_simulator_state(
    target: str = "edit",
    device_id: str | None = None,
    include_device_list: bool = True,
) -> dict:
    if device_id is not None and (
        not isinstance(device_id, str) or not device_id.strip()
    ):
        return _invalid("deviceId must be a non-empty string when provided")
    role = target or "edit"
    options: dict = {"includeDeviceList": include_device_list}
    if device_id is not None:
        options["deviceId"] = device_id
    result = _call(
        "/api/execute-luau", {"code": _device_luau("get", options)}, role=role
    )
    if "error" in result:
        return result
    if isinstance(result, dict):
        return {"target": role, "role": role, **result}
    return {"target": role, "role": role, "result": result}


def set_device_simulator(
    target: str = "edit",
    device_id: str | None = None,
    orientation: str | None = None,
    resolution: dict | None = None,
    pixel_density: float | None = None,
    scaling_mode: str | None = None,
    stop_simulation: bool = False,
) -> dict:
    try:
        settings = normalize_device_settings(
            device_id, orientation, resolution, pixel_density, scaling_mode
        )
    except ValueError as exc:
        return _invalid(str(exc))
    if stop_simulation is True and settings:
        return _invalid(
            "stopSimulation=true cannot be combined with deviceId, orientation, "
            "resolution, pixelDensity, or scalingMode"
        )
    if stop_simulation is not True and not settings:
        return _invalid(
            "set_device_simulator requires stopSimulation=true or at least "
            "one simulator setting"
        )
    role = target or "edit"
    options: dict = (
        {"stopSimulation": True} if stop_simulation is True else {"settings": settings}
    )
    result = _call(
        "/api/execute-luau", {"code": _device_luau("set", options)}, role=role
    )
    if "error" in result:
        return result
    return {"target": role, "targets": {role: result}}


def capture_device_matrix(
    entries: list, target: str = "edit", restore_after: bool = True
) -> dict:
    if not isinstance(entries, list) or not entries:
        return _invalid("capture_device_matrix requires a non-empty entries array")
    if len(entries) > MAX_DEVICE_MATRIX_ENTRIES:
        return _invalid(
            f"capture_device_matrix supports at most {MAX_DEVICE_MATRIX_ENTRIES} "
            "entries per call; split larger matrices into multiple calls"
        )
    role = target or "edit"
    normalized = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            return _invalid(f"entries[{index}] must be an object")
        try:
            settings = normalize_device_settings(
                entry.get("deviceId"),
                entry.get("orientation"),
                entry.get("resolution"),
                entry.get("pixelDensity"),
                entry.get("scalingMode"),
            )
        except ValueError as exc:
            return _invalid(f"entries[{index}]: {exc}")
        normalized.append({"label": entry.get("label"), "settings": settings})
    before = get_device_simulator_state(role, include_device_list=False)
    if "error" in before:
        return before
    captures = []
    try:
        for item in normalized:
            applied = set_device_simulator(role, **_pythonize(item["settings"]))
            if "error" in applied:
                captures.append({"label": item["label"], **applied})
                continue
            shot = _call("/api/capture-screenshot", {})
            captures.append({"label": item["label"], "device": applied, "shot": shot})
    finally:
        if restore_after:
            saved = {
                k: before[k]
                for k in (
                    "activeDeviceId",
                    "orientation",
                    "resolution",
                    "pixelDensity",
                    "scalingMode",
                )
                if k in before
            }
            if before.get("isSimulating") is True and saved.get("activeDeviceId") not in (
                None,
                "default",
            ):
                set_device_simulator(
                    role,
                    device_id=saved.get("activeDeviceId"),
                    orientation=saved.get("orientation"),
                    resolution=saved.get("resolution"),
                    pixel_density=saved.get("pixelDensity"),
                    scaling_mode=saved.get("scalingMode"),
                )
            else:
                set_device_simulator(role, stop_simulation=True)
    return {"target": role, "captures": captures}


def _pythonize(settings: dict) -> dict:
    rename = {
        "deviceId": "device_id",
        "orientation": "orientation",
        "resolution": "resolution",
        "pixelDensity": "pixel_density",
        "scalingMode": "scaling_mode",
    }
    return {rename[k]: v for k, v in settings.items() if k in rename}


# --- Simulation state (single role; fan-out needs multi-peer routing) ---


def get_simulation_state(include: str = "both", target: str = "edit") -> dict:
    selected_include = include or "both"
    if selected_include not in ("network", "deviceSimulator", "both"):
        return _invalid(
            'get_simulation_state include must be "network", '
            f'"deviceSimulator", or "both" (got: {selected_include})'
        )
    role = target or "edit"
    if role not in ("edit", "all-clients", "edit-and-clients") and not _CLIENT_RE.match(
        role
    ):
        return _invalid(
            f"get_simulation_state target must be \"edit\", \"client-N\", "
            f'"all-clients", or "edit-and-clients" (got: {role})'
        )
    if role in ("all-clients", "edit-and-clients"):
        return {
            "error": "unsupported_target",
            "message": f"{role} fan-out needs multi-peer routing; "
            "call once per edit or client-N",
        }
    state: dict = {}
    errors: dict = {}
    if selected_include in ("network", "both"):
        net = _call(
            "/api/execute-luau", {"code": _network_state_luau("get")}, role=role
        )
        if "error" in net:
            errors["network"] = net.get("message", "")
        else:
            state["network"] = net
    if selected_include in ("deviceSimulator", "both"):
        dev = _call(
            "/api/execute-luau",
            {"code": _device_luau("get", {"includeDeviceList": False})},
            role=role,
        )
        if "error" in dev:
            errors["deviceSimulator"] = dev.get("message", "")
        else:
            state["deviceSimulator"] = dev
    if errors:
        state["errors"] = errors
    return {
        "include": selected_include,
        "target": role,
        "roles": {role: state},
        "warnings": [],
        "persistenceNotes": list(PERSISTENCE_NOTES),
    }


def reset_simulation_state(
    target: str = "edit", network: bool = True, device_simulator: bool = True
) -> dict:
    if network is False and device_simulator is False:
        return _invalid(
            "reset_simulation_state requires network=true and/or "
            "deviceSimulator=true; both default to true"
        )
    role = target or "edit"
    result: dict = {}
    errors: dict = {}
    if network is not False:
        net = _call(
            "/api/execute-luau", {"code": _network_state_luau("reset")}, role=role
        )
        if "error" in net:
            errors["network"] = net.get("message", "")
        else:
            result["network"] = net
    if device_simulator is not False:
        dev = _call(
            "/api/execute-luau",
            {"code": _device_luau("set", {"stopSimulation": True})},
            role=role,
        )
        if "error" in dev:
            errors["deviceSimulator"] = dev.get("message", "")
        else:
            result["deviceSimulator"] = dev
    if errors:
        result["errors"] = errors
    return {
        "success": True,
        "target": role,
        "network": network is not False,
        "deviceSimulator": device_simulator is not False,
        "roles": {role: result},
        "warnings": [],
    }


# --- Place info + versioning ---


def get_place_info() -> dict:
    return _call("/api/place-info", {})


def _opencloud_get(path: str, params: dict) -> dict:
    key = os.environ.get(OPEN_CLOUD_KEY_ENV, "")
    if not key:
        return {
            "error": "missing_api_key",
            "message": f"{OPEN_CLOUD_KEY_ENV} is required",
        }
    url = OPEN_CLOUD_BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"x-api-key": key})
    try:
        with urllib.request.urlopen(req, timeout=OPEN_CLOUD_TIMEOUT_S) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8")
        except OSError:
            detail = ""
        return {
            "error": "opencloud_error",
            "message": f"Open Cloud API error ({exc.code}): {detail}",
        }
    except Exception as exc:
        return {"error": "opencloud_error", "message": str(exc)}


def list_place_versions(
    place_id: int, max_page_size: int = 10, page_token: str | None = None
) -> dict:
    try:
        pid = int(place_id)
    except (TypeError, ValueError):
        return _invalid("place_id must be a positive integer")
    if pid <= 0:
        return _invalid("place_id must be a positive integer")
    size = max(1, min(50, int(max_page_size or 10)))
    params: dict = {"maxPageSize": size}
    if page_token:
        params["pageToken"] = page_token
    response = _opencloud_get(f"/assets/v1/assets/{pid}/versions", params)
    if "error" in response:
        return response
    versions = []
    for entry in response.get("assetVersions", []) or []:
        path = entry.get("path", "")
        match = _VERSION_RE.search(path)
        versions.append(
            {
                "version": int(match.group(1)) if match else None,
                "created_at": entry.get("createTime"),
                "path": path,
                "moderation_state": (entry.get("moderationResult") or {}).get(
                    "moderationState"
                ),
            }
        )
    body: dict = {"versions": versions}
    if response.get("nextPageToken"):
        body["next_page_token"] = response["nextPageToken"]
    return body
