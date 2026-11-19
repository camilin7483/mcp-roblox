"""Contracts: advanced backend shapes, validation and offline behavior.

Verifiable without network or Studio: proxy and urlopen are stubbed.
Covers docs URL mechanism, network/device validation, simulation guards,
place versions (missing_api_key short-circuit) and the 3.1.0 docstring.
"""

import io
import os
import sys
import urllib.error
from pathlib import Path

_HERE = Path(__file__).resolve()
ROOT = _HERE.parents[1]  # tests/test_advanced.py -> project root
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backends import advanced


class _Resp:
    def __init__(self, body: bytes):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _stub_proxy(calls, result=None, error=None):
    def fake(endpoint, data, role="edit", timeout=30):
        calls.append({"endpoint": endpoint, "data": data, "role": role})
        if error is not None:
            raise RuntimeError(error)
        return dict(result or {"ok": True})

    return fake


def test_docstring_marks_absent_features():
    assert "not in 3.1.0" in advanced.__doc__.lower()
    assert "manage_monetization" in advanced.__doc__


def test_docs_url_mechanism_exact():
    seen = {}

    def fake_urlopen(req, timeout=None):
        seen["url"] = req.full_url
        seen["accept"] = req.get_header("Accept")
        seen["timeout"] = timeout
        return _Resp(b"## Props\n\ntext")

    advanced.urllib.request.urlopen = fake_urlopen
    try:
        result = advanced.get_roblox_doc("Part")
    finally:
        import urllib.request as _u

        advanced.urllib.request.urlopen = _u.urlopen
    assert seen["url"] == (
        "https://create.roblox.com/docs/reference/engine/classes/Part.md"
    )
    assert "text/markdown" in seen["accept"]
    assert seen["timeout"] == 15
    assert result["sections"] == ["Props"]
    assert result["truncated"] is False


def test_docs_section_and_invalid_category():
    def fake_urlopen(req, timeout=None):
        return _Resp(b"## Alpha\n\na\n## Beta\n\nb")

    advanced.urllib.request.urlopen = fake_urlopen
    try:
        result = advanced.get_roblox_doc("X", section="beta")
    finally:
        import urllib.request as _u

        advanced.urllib.request.urlopen = _u.urlopen
    assert result["content"].startswith("## Beta")
    bad = advanced.get_roblox_doc("X", doc_type="nope")
    assert bad["error"] == "invalid_argument"


def test_docs_404_maps_to_not_found():
    def fake_urlopen(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 404, "nf", {}, io.BytesIO(b""))

    advanced.urllib.request.urlopen = fake_urlopen
    try:
        result = advanced.get_roblox_doc("Missing")
    finally:
        import urllib.request as _u

        advanced.urllib.request.urlopen = _u.urlopen
    assert result["error"] == "doc_not_found"


def test_network_profile_values_match_dist():
    assert advanced.NETWORK_PROFILES["poor"]["InboundNetworkLossPercent"] == 0.5
    assert advanced.MAX_NETWORK_PACKET_LOSS_PERCENT == 0.5
    assert set(advanced.NETWORK_PROFILE_KEYS) == {
        "InboundNetworkMinDelayMs",
        "OutboundNetworkMinDelayMs",
        "InboundNetworkJitterMs",
        "OutboundNetworkJitterMs",
        "InboundNetworkLossPercent",
        "OutboundNetworkLossPercent",
    }


def test_network_validation_errors():
    assert advanced.set_network_profile("bad")["error"] == "invalid_argument"
    custom = advanced.set_network_profile("custom")
    assert custom["error"] == "invalid_argument"
    capped = advanced.set_network_profile(
        "custom", overrides={"InboundNetworkLossPercent": 0.6}
    )
    assert capped["error"] == "invalid_argument"
    unknown = advanced.set_network_profile("good", overrides={"Nope": 1})
    assert unknown["error"] == "invalid_argument"
    target = advanced.set_network_profile("good", target="server")
    assert "client-N" in target["message"]


def test_network_sends_luau_over_execute():
    calls = []
    advanced.proxy = _stub_proxy(calls)
    try:
        result = advanced.set_network_profile("good")
    finally:
        from precision import proxy as _real

        advanced.proxy = _real
    assert result["profile"] == "good"
    assert result["target"] == "client-1"
    assert calls[0]["endpoint"] == "/api/execute-luau"
    assert calls[0]["role"] == "client-1"
    assert "NetworkSettings" in calls[0]["data"]["code"]


def test_bridge_error_shape():
    advanced.proxy = _stub_proxy([], error="down")
    try:
        assert advanced.get_place_info()["error"] == "bridge_error"
        assert advanced.set_network_profile("good")["error"] == "bridge_error"
    finally:
        from precision import proxy as _real

        advanced.proxy = _real


def test_device_validation_exact():
    both = advanced.set_device_simulator(device_id="Phone", stop_simulation=True)
    assert both["error"] == "invalid_argument"
    empty = advanced.set_device_simulator()
    assert empty["error"] == "invalid_argument"
    res = advanced.set_device_simulator(resolution={"width": -1, "height": 2})
    assert res["error"] == "invalid_argument"
    bad_state = advanced.get_device_simulator_state(device_id="  ")
    assert bad_state["error"] == "invalid_argument"


def test_device_set_uses_verified_api_names():
    calls = []
    advanced.proxy = _stub_proxy(calls)
    try:
        result = advanced.set_device_simulator(
            device_id="Phone", orientation="Portrait"
        )
    finally:
        from precision import proxy as _real

        advanced.proxy = _real
    code = calls[0]["data"]["code"]
    assert "StudioDeviceSimulatorService" in code
    assert "SetDeviceAsync" in code
    assert calls[0]["endpoint"] == "/api/execute-luau"
    assert result["targets"]["edit"] == {"ok": True}


def test_simulation_guards():
    bad = advanced.get_simulation_state(include="all")
    assert "deviceSimulator" in bad["message"]
    reset = advanced.reset_simulation_state(network=False, device_simulator=False)
    assert reset["error"] == "invalid_argument"
    fan = advanced.get_simulation_state(target="all-clients")
    assert fan["error"] == "unsupported_target"


def test_simulation_state_merges_single_role():
    calls = []
    advanced.proxy = _stub_proxy(calls)
    try:
        result = advanced.get_simulation_state()
    finally:
        from precision import proxy as _real

        advanced.proxy = _real
    assert result["include"] == "both"
    assert set(result["roles"]["edit"]) == {"network", "deviceSimulator"}
    assert len(calls) == 2


def test_place_versions_require_key_without_calling():
    called = []

    def fake_urlopen(req, timeout=None):
        called.append(req.full_url)
        return _Resp(b"{}")

    old = os.environ.pop("ROBLOX_OPEN_CLOUD_API_KEY", None)
    advanced.urllib.request.urlopen = fake_urlopen
    try:
        result = advanced.list_place_versions(123)
    finally:
        if old is not None:
            os.environ["ROBLOX_OPEN_CLOUD_API_KEY"] = old
        import urllib.request as _u

        advanced.urllib.request.urlopen = _u.urlopen
    assert result["error"] == "missing_api_key"
    assert called == []


def test_place_versions_shape_and_clamp():
    seen = {}

    def fake_urlopen(req, timeout=None):
        seen["url"] = req.full_url
        seen["key"] = req.get_header("X-api-key")
        return _Resp(
            b'{"assetVersions": [{"path": "assets/1/versions/7", '
            b'"createTime": "t", "moderationResult": {"moderationState": "ok"}}], '
            b'"nextPageToken": "n"}'
        )

    os.environ["ROBLOX_OPEN_CLOUD_API_KEY"] = "k"
    advanced.urllib.request.urlopen = fake_urlopen
    try:
        result = advanced.list_place_versions(1, max_page_size=500)
    finally:
        del os.environ["ROBLOX_OPEN_CLOUD_API_KEY"]
        import urllib.request as _u

        advanced.urllib.request.urlopen = _u.urlopen
    assert seen["url"].startswith("https://apis.roblox.com/assets/v1/assets/1/versions")
    assert "maxPageSize=50" in seen["url"]
    assert seen["key"] == "k"
    assert result["versions"][0]["version"] == 7
    assert result["versions"][0]["moderation_state"] == "ok"
    assert result["next_page_token"] == "n"
    assert advanced.list_place_versions(0)["error"] == "invalid_argument"


def test_skills_missing_bundle_is_offline_error(tmp_path=None):
    old = os.environ.get("ROBLOX_STUDIO_ASSISTANT_BUNDLE")
    os.environ["ROBLOX_STUDIO_ASSISTANT_BUNDLE"] = "/nonexistent/Assistant.rbxm"
    try:
        result = advanced.list_skills()
        assert result["error"] == "skills_unavailable"
        one = advanced.get_skill("  ")
        assert one["error"] == "invalid_argument"
    finally:
        if old is None:
            os.environ.pop("ROBLOX_STUDIO_ASSISTANT_BUNDLE", None)
        else:
            os.environ["ROBLOX_STUDIO_ASSISTANT_BUNDLE"] = old


def test_skills_bundle_metadata_without_network(tmp_path):
    bundle = tmp_path / "Assistant.rbxm"
    bundle.write_bytes(b"fake")
    os.environ["ROBLOX_STUDIO_ASSISTANT_BUNDLE"] = str(bundle)
    try:
        result = advanced.list_skills()
    finally:
        os.environ.pop("ROBLOX_STUDIO_ASSISTANT_BUNDLE", None)
    assert result["source"] == "installed-studio-assistant"
    assert len(result["bundleSha256"]) == 64
    assert result["error"] == "skills_unavailable"


def test_matrix_entry_cap():
    result = advanced.capture_device_matrix([{}] * 7)
    assert result["error"] == "invalid_argument"
    empty = advanced.capture_device_matrix([])
    assert empty["error"] == "invalid_argument"
