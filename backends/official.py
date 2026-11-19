"""Official/generation backend (plain functions returning dicts)."""

from precision import proxy

_EVAL_ENDPOINT = {
    "edit": "/api/execute-luau",
    "server": "/api/eval-runtime",
    "client": "/api/eval-runtime",
}


def _call(endpoint: str, payload: dict, role: str = "edit") -> dict:
    try:
        return proxy(endpoint, payload, role=role)
    except Exception as exc:
        return {"error": "bridge_error", "message": str(exc)}


def execute_luau(source: str, domain: str = "edit") -> dict:
    endpoint = _EVAL_ENDPOINT.get(domain)
    if endpoint is None:
        return {
            "error": "invalid_domain",
            "message": "domain must be one of edit, server, client",
            "domain": domain,
        }
    role = domain if domain in ("server", "client") else "edit"
    return _call(endpoint, {"code": source}, role=role)


def generate_model(prompt: str) -> dict:
    return _call("/api/generate-model", {"prompt": prompt})


def screenshot() -> dict:
    return _call("/api/capture-screenshot", {})


def get_logs(instance_id: str = "", cursor: str = "") -> dict:
    payload: dict = {"tail": 100}
    if cursor:
        payload["since"] = cursor
    return _call("/api/get-runtime-logs", payload)
