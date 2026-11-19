"""Toolbox (asset) backend: public catalog search + plugin preview/insert."""

import json
import urllib.parse
import urllib.request

from precision import proxy

_CATALOG = "https://apis.roblox.com/toolbox-service/v2"
_THUMBS = "https://thumbnails.roblox.com/v1/assets"

MAX_BULK_INSERT = 5  # Studio allows at most 5 parallel inserts


def _public_get(url: str, params: dict | None = None, timeout: int = 15) -> dict:
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def search_assets(query: str, limit: int = 10, category: str = "Model") -> dict:
    return _public_get(
        f"{_CATALOG}/assets:search",
        {
            "query": query,
            "maxPageSize": max(1, min(50, limit)),
            "searchCategoryType": category,
        },
    )


def asset_details(asset_id: int) -> dict:
    return _public_get(f"{_CATALOG}/assets/{asset_id}")


def asset_thumbnail(asset_id: int, size: str = "420x420") -> dict:
    return _public_get(
        _THUMBS, {"assetIds": asset_id, "size": size, "format": "Png"}
    )


def preview(asset_id: int) -> dict:
    # Security scan result passes through untouched inside the response.
    return proxy(
        "/api/preview-asset",
        {"assetId": asset_id, "includeProperties": False},
    )


def insert(asset_id: int, parent: str = "Workspace") -> dict:
    # sanitize is always on; no public opt-out (H2).
    return proxy(
        "/api/insert-asset",
        {"assetId": asset_id, "parentPath": parent},
    )


def insert_bulk(asset_ids: list, parent: str = "Workspace") -> dict:
    ids = asset_ids or []
    inserted: list = []
    failed: list = []
    for asset_id in ids[:MAX_BULK_INSERT]:
        try:
            inserted.append(insert(asset_id, parent))
        except Exception as exc:
            failed.append({"asset_id": asset_id, "error": str(exc)})
    return {"inserted": inserted, "failed": failed, "skipped": ids[MAX_BULK_INSERT:]}
