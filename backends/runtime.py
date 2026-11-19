"""Runtime/playtest backend (plain functions returning dicts).

Payloads mirror the real bridge calls in
``@chrrxs/robloxstudio-mcp/dist/index.js`` (class ``RobloxStudioTools``):

- ``startPlaytest`` -> ``POST /api/start-playtest`` with ``{"mode": "play"|"run"}``
- ``stopPlaytest`` -> ``POST /api/stop-playtest`` with ``{}`` (edit peer)
- ``multiplayerTestStart`` -> ``POST /api/multiplayer-test-start``
  with ``{"numPlayers": n, "testArgs": {}}`` (edit peer)
- ``multiplayerTestAddPlayers`` -> ``POST /api/multiplayer-test-add-players``
  with ``{"numPlayers": n, "timeout": 10}`` (server peer)
- ``multiplayerTestLeaveClient`` -> ``POST /api/multiplayer-test-leave-client``
  with ``{}`` (client-N peer, defaults to ``client-1``)
- ``multiplayerTestEnd`` -> ``POST /api/multiplayer-test-end``
  with ``{"value": "ended_by_mcp"}`` (server peer)
- ``_buildMultiplayerState`` -> ``POST /api/multiplayer-test-state`` with ``{}``
- ``breakpoints`` -> ``POST /api/breakpoints`` with ``{**request, "action"}``
  (actions ``set|remove|clear|list``)
- ``simulateMouseInput`` -> ``POST /api/simulate-mouse-input``
  with ``{"action", "x", "y", "button"}`` (upstream accepts but drops
  ``scrollDirection`` from the wire payload, so it is omitted here too)
- ``simulateKeyboardInput`` -> ``POST /api/simulate-keyboard-input``
  with ``{"keyCode", "action", "duration", "text"}``
- ``focusViewport`` -> ``POST /api/focus-viewport``
  with ``{"path", "from", "padding", "angleY"}``

All requested endpoints exist in the dist; none were omitted.
"""

from precision import proxy

_LONG_TIMEOUT = 120

_BREAKPOINT_ACTIONS = frozenset({"set", "remove", "clear", "list"})


def _call(endpoint: str, payload: dict, role: str = "edit", timeout: int = 30) -> dict:
    try:
        return proxy(endpoint, payload, role=role, timeout=timeout)
    except Exception as exc:
        return {"error": "bridge_error", "message": str(exc)}


def _invalid_arg(message: str) -> dict:
    return {"error": "invalid_arg", "message": message}


def playtest_start(mode: str = "play") -> dict:
    if mode not in ("play", "run"):
        return _invalid_arg('mode must be "play" or "run"')
    return _call("/api/start-playtest", {"mode": mode}, timeout=_LONG_TIMEOUT)


def playtest_stop() -> dict:
    return _call("/api/stop-playtest", {}, timeout=_LONG_TIMEOUT)


def multiplayer_start(player_count: int = 2) -> dict:
    if not isinstance(player_count, int) or not 1 <= player_count <= 8:
        return _invalid_arg("player_count must be an integer from 1 to 8")
    payload = {"numPlayers": player_count, "testArgs": {}}
    return _call("/api/multiplayer-test-start", payload, timeout=_LONG_TIMEOUT)


def multiplayer_add_players(count: int = 1) -> dict:
    if not isinstance(count, int) or not 1 <= count <= 8:
        return _invalid_arg("count must be an integer from 1 to 8")
    payload = {"numPlayers": count, "timeout": 10}
    return _call(
        "/api/multiplayer-test-add-players", payload, role="server",
        timeout=_LONG_TIMEOUT,
    )


def multiplayer_leave(client: str = "") -> dict:
    target = client or "client-1"
    return _call(
        "/api/multiplayer-test-leave-client", {}, role=target,
        timeout=_LONG_TIMEOUT,
    )


def multiplayer_end(value: str = "ended_by_mcp") -> dict:
    return _call(
        "/api/multiplayer-test-end", {"value": value}, role="server",
        timeout=_LONG_TIMEOUT,
    )


def multiplayer_state() -> dict:
    return _call("/api/multiplayer-test-state", {})


def breakpoints(action: str = "list", data: dict | None = None) -> dict:
    if action not in _BREAKPOINT_ACTIONS:
        return _invalid_arg("action must be one of set, remove, clear, list")
    payload = dict(data or {})
    payload["action"] = action
    return _call("/api/breakpoints", payload)


def input_mouse(
    action: str = "click",
    x: float = 0,
    y: float = 0,
    button: str = "Left",
    target: str = "",
) -> dict:
    payload = {"action": action, "x": x, "y": y, "button": button}
    return _call("/api/simulate-mouse-input", payload, role=target or "edit")


def input_keyboard(
    key_code: str = "",
    action: str = "tap",
    duration: float = 0.1,
    text: str | None = None,
    target: str = "",
) -> dict:
    payload: dict = {"keyCode": key_code, "action": action, "duration": duration}
    if text is not None:
        payload["text"] = text
    return _call("/api/simulate-keyboard-input", payload, role=target or "edit")


def focus_viewport(
    path: str = "",
    from_angle: float | None = None,
    padding: float | None = None,
    angle_y: float | None = None,
) -> dict:
    if not path:
        return _invalid_arg("path must not be empty")
    payload: dict = {"path": path}
    if from_angle is not None:
        payload["from"] = from_angle
    if padding is not None:
        payload["padding"] = padding
    if angle_y is not None:
        payload["angleY"] = angle_y
    return _call("/api/focus-viewport", payload)
