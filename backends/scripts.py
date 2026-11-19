"""Script backend: read/write/search Luau sources via /proxy."""

from precision import proxy


def _call(endpoint: str, payload: dict, role: str = "edit") -> dict:
    try:
        return proxy(endpoint, payload, role=role)
    except Exception as exc:
        return {"error": "bridge_error", "message": str(exc)}


def get_source(path: str, start: int = 0, end: int = 0) -> dict:
    return _call(
        "/api/get-script-source",
        {"instancePath": path, "startLine": start, "endLine": end},
    )


def set_source(path: str, source: str, dry_run: bool = True) -> dict:
    if dry_run:
        return {"dry_run": True, "path": path, "would_set": source}
    return _call("/api/set-script-source", {"instancePath": path, "source": source})


def edit_lines(
    path: str, old_string: str, new_string: str, start_line=None
) -> dict:
    payload: dict = {
        "instancePath": path,
        "old_string": old_string,
        "new_string": new_string,
    }
    if start_line is not None:
        payload["startLine"] = start_line
    return _call("/api/edit-script-lines", payload)


def insert_lines(path: str, after_line: int = 0, new_content: str = "") -> dict:
    return _call(
        "/api/insert-script-lines",
        {"instancePath": path, "afterLine": after_line, "newContent": new_content},
    )


def delete_lines(path: str, start_line: int = 0, end_line: int = 0) -> dict:
    return _call(
        "/api/delete-script-lines",
        {"instancePath": path, "startLine": start_line, "endLine": end_line},
    )


def grep(pattern: str, limit: int = 20) -> dict:
    return _call("/api/grep-scripts", {"pattern": pattern, "maxResults": limit})


def find_replace(pattern: str, replacement: str, dry_run: bool = True) -> dict:
    if dry_run:
        return {
            "dry_run": True,
            "pattern": pattern,
            "would_replace_with": replacement,
        }
    return _call(
        "/api/find-and-replace-in-scripts",
        {"pattern": pattern, "replacement": replacement, "dryRun": False},
    )
