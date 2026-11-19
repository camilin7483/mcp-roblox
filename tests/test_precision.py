"""Contracts: precision ok/err, world dry_run, planner steps, verifier verdicts."""

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
ROOT = _HERE.parents[1]  # tests/test_precision.py -> project root
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import planner
import precision
import verifier
from backends import world


def test_ok_roundtrip():
    payload = {"a": 1}
    assert json.loads(precision.ok(payload)) == payload


def test_err_shape():
    parsed = json.loads(precision.err("boom", "went wrong", {"x": 1}))
    assert parsed["error"] == "boom"
    assert parsed["message"] == "went wrong"
    assert parsed["details"] == {"x": 1}
    parsed2 = json.loads(precision.err("boom", "went wrong"))
    assert "details" not in parsed2


def test_dry_run_short_circuits_without_bridge():
    # Must not touch the network when dry_run=True.
    result = world.set_properties("Workspace.Part", {"Size": 1}, dry_run=True)
    assert result["dry_run"] is True
    assert result["path"] == "Workspace.Part"
    assert result["would_set"] == {"Size": 1}


def test_planner_base_steps():
    plan = planner.build_plan("move a part")
    ops = [s["op"] for s in plan["steps"]]
    assert ops == ["search", "read", "edit", "verify"]


def test_planner_toolbox_and_playtest_steps():
    plan = planner.build_plan("insert toolbox model and playtest the obby")
    ops = [s["op"] for s in plan["steps"]]
    assert ops == ["search", "toolbox_insert", "read", "edit", "playtest", "verify"]
    ids = [s["id"] for s in plan["steps"]]
    assert ids == sorted(ids)


def test_verifier_rollback_beats_retry():
    # Error logs win even when scene/screenshot also fail.
    decision = verifier.decide("Script error: stack overflow", scene_ok=False, screenshot_ok=False)
    assert decision["verdict"] == "rollback"


def test_verifier_retry_then_ok():
    retry = verifier.decide("all quiet", scene_ok=False, screenshot_ok=True)
    assert retry["verdict"] == "retry"
    assert retry["reasons"]
    good = verifier.decide("all quiet", scene_ok=True, screenshot_ok=True)
    assert good["verdict"] == "ok"
    assert good["reasons"] == []


if __name__ == "__main__":
    cases = [
        test_ok_roundtrip,
        test_err_shape,
        test_dry_run_short_circuits_without_bridge,
        test_planner_base_steps,
        test_planner_toolbox_and_playtest_steps,
        test_verifier_rollback_beats_retry,
        test_verifier_retry_then_ok,
    ]
    failed = 0
    for case in cases:
        try:
            case()
            print(f"PASS {case.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL {case.__name__}: {exc}")
    sys.exit(1 if failed else 0)
