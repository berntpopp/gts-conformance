"""Transport, identity and health checks.

Adapted from genefoundry-router (docs/conformance/conformance.py), MIT License,
Copyright (c) 2026 Bernt Popp. Changes: findings are recorded per GTS rule ID; the router
profile, the tier option and the require-auth mode are removed; version checks are added.
"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx

from .report import Report

SUPPORTED_PROTOCOL = "2025-06-18"
UNSUPPORTED_PROTOCOL = "1999-01-01"
FOREIGN_ORIGIN = "https://gts-check.invalid"  # a reserved name: never a server's own origin
NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.+-]+)?$")
HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
_INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": SUPPORTED_PROTOCOL,
        "capabilities": {},
        "clientInfo": {"name": "gts-check", "version": "1.0.0"},
    },
}
_TOOLS_LIST = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}


class ProbeError(RuntimeError):
    """The kit cannot report on this endpoint (exit code 2)."""


def _parse_body(resp: httpx.Response) -> dict[str, Any]:
    """Return the JSON payload, tolerating an SSE-framed body."""
    try:
        if "text/event-stream" in resp.headers.get("content-type", ""):
            raw = next(
                (line[5:].strip() for line in resp.text.splitlines() if line.startswith("data:")),
                "{}",
            )
            parsed = json.loads(raw)
        else:
            parsed = resp.json()
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def check_transport(
    rep: Report,
    client: httpx.Client,
    base: str,
    *,
    token: str | None = None,
    expected_name: str | None = None,
    health: bool = True,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Run the transport checks; return `serverInfo` and the headers that reach the server."""
    headers = dict(HEADERS)
    init = client.post(f"{base}/mcp", json=_INIT, headers=headers)
    if init.status_code in (401, 403):
        if not token:
            raise ProbeError(
                f"initialize answered {init.status_code}; pass --token if the server takes a "
                "static service token"
            )
        headers["Authorization"] = f"Bearer {token}"
        init = client.post(f"{base}/mcp", json=_INIT, headers=headers)
        rep.skip(
            "initialize without credentials",
            "the server wants a token, and the kit cannot tell a service token from a user's",
            "GTS-CORE-TRN-05",
        )
    elif init.status_code == 200:
        rep.check("initialize works without credentials", True, rule="GTS-CORE-TRN-05")

    result = _parse_body(init).get("result")
    info = result.get("serverInfo") if isinstance(result, dict) else None
    if init.status_code != 200 or not isinstance(info, dict):
        raise ProbeError(
            f"POST {base}/mcp initialize answered {init.status_code} "
            f"(Location={init.headers.get('location')!r}) without a serverInfo"
        )
    name, version = info.get("name"), info.get("version")
    # Identity first: a report is never written against the wrong server.
    if expected_name and name != expected_name:
        raise ProbeError(f"expected serverInfo.name {expected_name!r} at {base}, found {name!r}")

    rep.rule = "GTS-CORE-TRN-01"
    rep.check("POST /mcp → 200, no redirect", True)
    with client.stream(
        "GET", f"{base}/mcp", headers={**headers, "Accept": "text/event-stream"}
    ) as get:
        rep.check(
            "GET /mcp does not redirect", not 300 <= get.status_code < 400, f"got {get.status_code}"
        )

    rep.rule = "GTS-CORE-TRN-02"
    rep.check(
        "initialize Content-Type is application/json",
        init.headers.get("content-type", "").startswith("application/json"),
        init.headers.get("content-type", ""),
    )
    rep.check(
        "no Mcp-Session-Id header",
        "mcp-session-id" not in init.headers,
        "a session id is assigned (a stateful server MUST document why)",
    )

    rep.rule = "GTS-CORE-TRN-03"
    rep.check(
        "initialize negotiates protocolVersion",
        isinstance(result.get("protocolVersion"), str),
        f"got {result.get('protocolVersion')!r}",
    )
    # A stateful server needs its session id here, or the 400 would be about the session.
    session = init.headers.get("mcp-session-id")
    bad = client.post(
        f"{base}/mcp",
        json=_TOOLS_LIST,
        headers={
            **headers,
            **({"mcp-session-id": session} if session else {}),
            "MCP-Protocol-Version": UNSUPPORTED_PROTOCOL,
        },
    )
    rep.check(
        "unsupported MCP-Protocol-Version → 400", bad.status_code == 400, f"got {bad.status_code}"
    )

    foreign = client.post(f"{base}/mcp", json=_INIT, headers={**headers, "Origin": FOREIGN_ORIGIN})
    rep.check(
        f"initialize with Origin {FOREIGN_ORIGIN} is rejected (4xx)",
        400 <= foreign.status_code < 500,
        f"got {foreign.status_code}",
        rule="GTS-CORE-TRN-04",
    )

    rep.check(
        f"serverInfo.name {name!r} matches ^[a-z0-9]+(-[a-z0-9]+)*$",
        isinstance(name, str) and bool(NAME_RE.match(name)),
        "it does not",
        rule="GTS-CORE-VER-01",
    )

    # Read at every level: GTS-CORE-VER-02 compares with it, whatever --level asks for.
    got = client.get(f"{base}/health")
    body = _parse_body(got) if got.status_code == 200 else {}
    if health:
        rep.rule = "GTS-OPS-HLT-01"
        rep.check("GET /health → 200", got.status_code == 200, f"got {got.status_code}")
        missing = [key for key in ("status", "version", "transport") if key not in body]
        rep.check("/health has status, version, transport", not missing, f"missing {missing}")
        if "version" in body:
            rep.check(
                "/health version equals serverInfo.version",
                body["version"] == version,
                f"/health {body['version']!r}, serverInfo {version!r}",
            )

    rep.rule = "GTS-CORE-VER-02"
    rep.check(
        f"serverInfo.version {version!r} is a semantic version",
        isinstance(version, str) and bool(SEMVER_RE.match(version)),
        "it is not",
    )
    if "version" in body:
        rep.check(
            "serverInfo.version equals /health version",
            body["version"] == version,
            f"/health {body['version']!r}, serverInfo {version!r}",
        )
    return info, headers
