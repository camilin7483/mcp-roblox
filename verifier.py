"""Post-change verdict and profiler checks for mcp-roblox."""

import re

from precision import MEMORY_MAX_MB, MICRO_PROF_MAX_S

_ERROR_RE = re.compile(
    r"\b(errors?|failed|failure|stack trace|exception)\b", re.IGNORECASE
)
MICRO_MAX_S = MICRO_PROF_MAX_S


def decide(logs_text: str = "", scene_ok: bool = True, screenshot_ok: bool = True) -> dict:
    """Decide verdict from bridge logs and scene evidence."""
    reasons: list[str] = []
    text = logs_text or ""
    if _ERROR_RE.search(text):
        reasons.append("logs contain error/failed/stack")
        return {"verdict": "rollback", "reasons": reasons}
    if not scene_ok:
        reasons.append("scene check failed")
    if not screenshot_ok:
        reasons.append("screenshot check failed")
    if reasons:
        return {"verdict": "retry", "reasons": reasons}
    return {"verdict": "ok", "reasons": []}


def check_profilers(memory_mb: float = 0, micro_s: float = 0) -> dict:
    """Flag profiler readings over budget."""
    flags: list[str] = []
    if memory_mb > MEMORY_MAX_MB:
        flags.append(f"memory_mb {memory_mb} over {MEMORY_MAX_MB}")
    if micro_s > MICRO_MAX_S:
        flags.append(f"micro_s {micro_s} over {MICRO_MAX_S}")
    return {
        "memory_mb": memory_mb,
        "micro_s": micro_s,
        "flags": flags,
        "ok": not flags,
    }
