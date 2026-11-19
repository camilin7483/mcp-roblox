"""World (instance) backend: search, read, edit and structure via /proxy."""

from precision import proxy


def search(query: str, scope: str = "game") -> dict:
    return proxy("/api/search-objects", {"query": query, "searchType": "name"})


def read(instance_path: str) -> dict:
    return proxy(
        "/api/instance-properties",
        {"instancePath": instance_path, "excludeSource": False},
    )


def set_properties(instance_path: str, properties: dict, dry_run: bool = True) -> dict:
    if dry_run:
        return {"dry_run": True, "path": instance_path, "would_set": properties}
    return proxy(
        "/api/set-properties",
        {"instancePath": instance_path, "properties": properties},
    )


def get_structure() -> dict:
    return proxy("/api/project-structure", {})
