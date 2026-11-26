"""`gts-check <url>`: run the kit against a live MCP server and print a per-rule report."""

from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
from pathlib import Path
from typing import Any

import httpx

from . import SPEC_VERSION, __version__, behaviour, identifiers, repo, surface
from .report import LEVELS, NEEDS_REPO, RULES, Report, render
from .transport import ProbeError, _parse_body, check_transport

CLAIM_KEY = "org.genefoundry/gts"


def check_claim(rep: Report, claim: Any, levels: list[str], where: str) -> None:
    """GTS-CORE-VER-04: the declared claim has its fields, and this run does not contradict it."""
    rep.rule = "GTS-CORE-VER-04"
    if claim is None:
        rep.reasons[rep.rule] = (
            "the server declares no conformance claim (the rule binds a server that claims one)"
        )
        return
    claim = claim if isinstance(claim, dict) else {}
    level = claim.get("level")
    claimed = list(LEVELS)[: list(LEVELS).index(level) + 1] if level in LEVELS else []
    total = sum(r.split("-")[1] in [LEVELS[x] for x in claimed] for r in RULES)
    bad = [
        key
        for key, ok in (
            ("spec", isinstance(claim.get("spec"), str) and claim["spec"]),
            ("level", bool(claimed)),
            ("kit", isinstance(claim.get("kit"), str) and claim["kit"]),
            (
                "rules_checked",
                type(claim.get("rules_checked")) is int and 0 <= claim["rules_checked"] <= total,
            ),
            ("report", isinstance(claim.get("report", ""), str)),
        )
        if not ok
    ]
    rep.check(f"{where} declares spec, level, kit, rules_checked", not bad, f"bad {bad}")
    if claimed and set(claimed) <= set(levels):
        # The failure itself is already reported under its rule; this only flags the claim.
        if rep.failed(claimed):
            rep.warn(f"the claimed level {level!r}", "this run finds a FAIL or UNGATED rule there")
        else:
            rep.check(f"the claimed level {level!r} has no failure in this run", True)


def run(
    url: str,
    *,
    level: str = "operational",
    name: str | None = None,
    namespace: str | None = None,
    entrypoints: list[str] | None = None,
    free_text: list[str] | None = None,
    token: str | None = None,
    calls: dict[str, dict[str, Any]] | None = None,
    delay: float = 0.0,
    timeout: float = 60.0,
    transport: httpx.BaseTransport | None = None,
    repo_path: str | None = None,
) -> dict[str, Any]:
    """Check one server and return the report as a JSON-serialisable dict."""
    levels = list(LEVELS)[: list(LEVELS).index(level) + 1]
    recommended = "recommended" in levels
    base = url.rstrip("/").removesuffix("/mcp")
    rep = Report()
    with httpx.Client(timeout=timeout, follow_redirects=False, transport=transport) as client:
        info, headers = check_transport(
            rep, client, base, token=token, expected_name=name, health="operational" in levels
        )
        probe = behaviour.Probe(base, client, headers, delay)
        init = probe.initialize()
        tools = probe.list_tools()
        if not tools:
            raise ProbeError("tools/list returned no tool")
        # The default is a guess from serverInfo.name; --namespace states the documented token.
        ns = namespace or re.sub(r"-(link|mcp|server)$", "", str(info.get("name"))).replace("-", "")
        surface.check_surface(rep, tools, recommended=recommended, server=str(info.get("name")))
        surface.check_naming(rep, tools, ns, recommended=recommended)
        root = Path(repo_path) if repo_path else None
        readme = root / "README.md" if root else None
        surface.check_read_only(
            rep, tools, readme.read_text(encoding="utf-8") if readme and readme.is_file() else None
        )
        surface.check_output_schemas(rep, tools)
        if root:
            repo.check_changelog(rep, root)
        else:
            rep.reasons["GTS-CORE-VER-03"] = NEEDS_REPO
        if recommended and entrypoints:
            surface.check_pins(rep, tools, entrypoints, ns)
        elif recommended:
            why = "pass --entrypoints with the server's nominated entry-point tools"
            rep.reasons.update({"GTS-REC-PIN-01": why, "GTS-REC-PIN-02": why})
        behaviour.run(rep, probe, tools, recommended=recommended, calls=calls)
        if recommended:
            identifiers.run(rep, probe, tools, ns, frozenset(free_text or []))
        claim = (init.get("_meta") or {}).get(CLAIM_KEY)
        where = "initialize _meta"
        if claim is None:
            claim, where = _parse_body(client.get(f"{base}/health")).get("gts"), "/health gts"
        check_claim(rep, claim, levels, where)
    return {
        "kit_version": __version__,
        "spec_version": SPEC_VERSION,
        "date": datetime.date.today().isoformat(),
        "url": base,
        "server": {"name": info.get("name"), "version": info.get("version")},
        "namespace": ns,
        "repo": bool(repo_path),
        "tools": len(tools),
        "conformant_so_far": not rep.failed(levels),
        "levels": rep.to_dict(levels),
        "coverage": [
            {"tool": tool, "validated": not why, "reason": why}
            for tool, why in rep.coverage.items()
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="gts-check",
        description="GTS v1 conformance check of a live MCP server (Streamable HTTP). "
        "It calls every tool with its documented examples and with invalid input.",
    )
    parser.add_argument("url", help="server base URL, with or without the /mcp path")
    parser.add_argument(
        "--level", choices=list(LEVELS), default="operational", help="highest level to check"
    )
    parser.add_argument("--name", help="expected serverInfo.name; the run stops on another server")
    parser.add_argument(
        "--namespace", help="the server's namespace token (default: from serverInfo.name)"
    )
    parser.add_argument(
        "--entrypoints", help="comma-separated entry-point tools (GTS-REC-PIN-01, -02)"
    )
    parser.add_argument(
        "--free-text",
        help="comma-separated tool.param search boxes that take free text, not one gene "
        "(left out of GTS-REC-BEH-05 and reported as SKIP)",
    )
    parser.add_argument(
        "--call",
        action="append",
        default=[],
        metavar="TOOL=JSON",
        help="arguments of one tool's control call, in place of its examples (repeatable); "
        "the tool is called even if it is an ops/meta tool or declares readOnlyHint: false",
    )
    parser.add_argument("--token", help="static service token, sent as a Bearer token")
    parser.add_argument(
        "--delay", type=float, default=0.0, help="seconds to wait before each tool request"
    )
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument(
        "--repo",
        metavar="PATH",
        help="the server's repository, for the rules checked statically (GTS-CORE-VER-03; "
        "the README for GTS-CORE-RO-01)",
    )
    parser.add_argument("--json", action="store_true", help="print the full report as JSON")
    args = parser.parse_args(argv)
    try:
        report = run(
            args.url,
            level=args.level,
            name=args.name,
            namespace=args.namespace,
            entrypoints=args.entrypoints.split(",") if args.entrypoints else None,
            free_text=args.free_text.split(",") if args.free_text else None,
            token=args.token,
            calls={
                tool: json.loads(value) for tool, _, value in (c.partition("=") for c in args.call)
            },
            delay=args.delay,
            timeout=args.timeout,
            repo_path=args.repo,
        )
    except (ProbeError, httpx.HTTPError, behaviour.ProtocolError) as exc:
        print(f"PROBE ERROR: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        server = report["server"]
        print(
            f"GTS {report['spec_version']} conformance, kit {report['kit_version']}, {report['date']}\n"
            f"{server['name']} {server['version']} @ {report['url']} "
            f"({report['tools']} tools, namespace {report['namespace']!r})\n"
        )
        print(render(report["levels"]))
        open_ = [c for c in report["coverage"] if not c["validated"]]
        print(
            f"\nEnvelope schema: {len(report['coverage']) - len(open_)} of {report['tools']} tools validated"
        )
        for c in open_:
            print(f"  not validated: {c['tool']} — {c['reason']}")
    return 0 if report["conformant_so_far"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
