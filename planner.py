"""Deterministic build plan for mcp-roblox edits."""

import re

_TOOLBOX_RE = re.compile(r"\b(toolbox|asset|assets|model|mesh)\b", re.IGNORECASE)
_PLAYTEST_RE = re.compile(r"\b(tests?|playtests?|play|obby)\b", re.IGNORECASE)

_VALID_OPS = (
    "search",
    "read",
    "edit",
    "exec",
    "toolbox_insert",
    "playtest",
    "verify",
)


def build_plan(intent: str, toolbox_hits: list | None = None) -> dict:
    """Build an ordered step list for the given intent.

    Always includes search -> read -> edit (dry_run) -> verify.
    Inserts toolbox_insert after search when the intent mentions
    toolbox assets, and playtest before verify when it mentions testing.
    """
    text = intent or ""
    hits = toolbox_hits or []
    steps: list[dict] = []
    step_id = 1

    def add(op: str, detail: str) -> None:
        nonlocal step_id
        steps.append({"id": step_id, "op": op, "detail": detail})
        step_id += 1

    add("search", f"search scope for: {text}")
    if _TOOLBOX_RE.search(text):
        if hits:
            detail = f"insert toolbox asset ({len(hits)} hit(s)) for: {text}"
        else:
            detail = f"insert toolbox asset for: {text}"
        add("toolbox_insert", detail)
    add("read", f"read targets for: {text}")
    add("edit", f"edit (dry_run) for: {text}")
    if _PLAYTEST_RE.search(text):
        add("playtest", f"playtest for: {text}")
    add("verify", f"verify change for: {text}")
    return {"intent": intent, "steps": steps[:8]}
