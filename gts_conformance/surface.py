"""Checks on the advertised tool list: surface budget, schema documentation, naming, pins.

Tokens are estimated as `len(json.dumps(x)) / 4`: a comparative heuristic, not a tokenizer.

Adapted from genefoundry-router (scripts/surface.py, scripts/check_tool_surface.py,
scripts/check_batch_pointers.py and check_leaf_name in genefoundry_router/cli.py), MIT License,
Copyright (c) 2026 Bernt Popp. Changes: findings are recorded per GTS rule ID in the kit's
Report; fleet-only configuration and the command-line entry point are removed.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .report import Report

MAX_TOOL_TOKENS = 1_200  # GTS-REC-BUD-01
MAX_SERVER_TOKENS = 10_000  # GTS-REC-BUD-02
# Documented exemptions to GTS-REC-BUD-02 (spec section 3.3): serverInfo.name -> hard cap.
SERVER_TOKEN_CAPS = {"pubtator-link": 13_000}

# GTS-REC-SRCH-01 (description lead).
LEAD_CHARS = 300
_LEAD_VERBS = [
    "get",
    "fetch",
    "retrieve",
    "list",
    "look",
    "lookup",
    "search",
    "find",
    "resolve",
    "report",
    "read",
    "predict",
    "annotate",
    "compute",
    "calculate",
    "count",
    "summarize",
    "summarise",
    "map",
    "translate",
    "convert",
    "describe",
    "show",
    "check",
    "validate",
    "classify",
    "score",
    "rank",
    "query",
    "browse",
    "discover",
    "explain",
    "compare",
    "diff",
    "normalize",
    "normalise",
    "expand",
    "evaluate",
    "assess",
    "enumerate",
    "identify",
    "locate",
    "export",
    "download",
    "match",
    "suggest",
    "recommend",
    "inspect",
    "generate",
    "render",
    "estimate",
]
# "Get X" / "Retrieves X" / "Use this to get X": the verb's object is what comes back.
_VERB_LEAD = re.compile(
    rf"^(?:use this (?:tool )?to )?(?:{'|'.join(_LEAD_VERBS)})(?:s|es|ies)?\b", re.IGNORECASE
)
# "Returns X" / "→ X"; not "does not return", not a size ("Returns ~7kB").
_RETURNS = re.compile(
    r"(?<!not )(?<!n't )(?<!n\u2019t )(?<!never )\breturn(?:s|ed|ing)?\b(?!\s*[~<\d])|→|->",
    re.IGNORECASE,
)
# "Use this for a gene dossier: constraint, transcripts, ..." — a labelled field list.
_FIELD_LIST = re.compile(r"\w+\W+\w+[^:]*:\s+[^.;:]+,")
_SENTENCE_END = re.compile(r"(?<!e\.g\.)(?<!i\.e\.)(?<=[.!?])\s+")


def tokens(obj: Any) -> int:
    """Approximate token cost of a JSON-serialisable object (chars/4)."""
    return len(json.dumps(obj)) // 4


def description_lead(description: str | None) -> str:
    """The lead a reranker or client shows: the first sentence, capped at LEAD_CHARS."""
    text = " ".join((description or "").split())
    return _SENTENCE_END.split(text, maxsplit=1)[0][:LEAD_CHARS]


def lead_states_return(description: str | None) -> bool:
    """D1: does the first sentence say what the tool returns?

    Passes on any of: an output verb first ("Get/Retrieves/Resolve ..."), a returns
    statement ("Returns ...", "→ ..."), or a labelled field list ("...: a, b, c").
    It checks form, not quality: "Get data." passes, so review still reads the words.
    """
    lead = description_lead(description)
    return bool(_VERB_LEAD.match(lead) or _RETURNS.search(lead) or _FIELD_LIST.search(lead))


def properties(tool: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Every input property of a tool, by name."""
    schema = tool.get("inputSchema") or {}
    return dict(schema.get("properties") or {})


def declares_enum(prop: dict[str, Any]) -> bool:
    """True if a property constrains its value to a closed set.

    An enum may sit directly on the property, or inside an `anyOf` branch — which is how
    pydantic renders `Literal[...] | None`, the fleet's usual shape for an optional filter.
    """
    if prop.get("enum"):
        return True
    return any(
        isinstance(branch, dict) and branch.get("enum") for branch in prop.get("anyOf") or []
    )


def is_array(prop: dict[str, Any]) -> bool:
    """True if a property accepts a JSON array (directly or via an `anyOf` branch)."""
    if prop.get("type") == "array":
        return True
    return any(
        isinstance(branch, dict) and branch.get("type") == "array"
        for branch in prop.get("anyOf") or []
    )


# --------------------------------------------------------------------------- checks

NAME_RE = re.compile(r"^[a-z0-9_]{1,50}$")
NAMESPACE_RE = re.compile(r"^[a-z0-9]+$")
VERBS = {
    "get",
    "search",
    "list",
    "resolve",
    "find",
    "compare",
    "compute",
    "map",
    "predict",
    "annotate",
    "recode",
    "liftover",
    "analyze",
    "score",
    "submit",
    "export",
    "generate",
    "download",
}


def _file(rep: Report, rule: str, label: str, bad: list[str], warn: bool = False) -> None:
    """One PASS for a clean rule, else one finding per offender."""
    if not bad:
        rep.check(label, True, rule=rule)
    for detail in bad:
        rep.warn(label, detail, rule) if warn else rep.check(label, False, detail, rule=rule)


def tags_of(tool: dict[str, Any]) -> set[str]:
    meta = tool.get("_meta") or tool.get("meta") or {}
    fastmcp = meta.get("_fastmcp") or meta.get("fastmcp") or {}
    return set(fastmcp.get("tags") or meta.get("tags") or [])


def check_surface(
    rep: Report, tools: list[dict[str, Any]], *, recommended: bool, server: str = ""
) -> None:
    """Schema documentation (Core) and the surface budget and description lead (Recommended)."""
    s1, s2, b1, d1 = [], [], [], []
    for tool in tools:
        name = tool.get("name", "?")
        cost = tokens(tool)
        if cost > MAX_TOOL_TOKENS:
            out = tokens(tool.get("outputSchema") or {})
            b1.append(f"{name} is {cost:,} tokens ({round(100 * out / cost)}% outputSchema)")
        if not lead_states_return(tool.get("description")):
            d1.append(f"{name}: first sentence does not say what it returns")
        required = set((tool.get("inputSchema") or {}).get("required") or [])
        for prop_name, prop in properties(tool).items():
            if not prop.get("description"):
                s1.append(f"{name}.{prop_name} has no description")
            if prop_name in required and not prop.get("examples"):
                s2.append(f"{name}.{prop_name} is required but has no examples")
            elif is_array(prop) and not prop.get("examples"):
                s2.append(f"{name}.{prop_name} takes an array but has no examples")
    _file(rep, "GTS-CORE-SCH-01", "every input property has a description", s1)
    _file(rep, "GTS-CORE-SCH-02", "required and array properties carry examples", s2)
    if not recommended:
        return
    total = tokens(tools)
    cap = SERVER_TOKEN_CAPS.get(server, MAX_SERVER_TOKENS)
    b2 = [f"{total:,} tokens"] if total > cap else []
    _file(rep, "GTS-REC-BUD-01", f"every tool definition ≤ {MAX_TOOL_TOKENS:,} tokens", b1)
    if MAX_SERVER_TOKENS < total <= cap:
        why = f"documented exemption for {server}, hard cap {cap:,} tokens"
        rep.exempt(f"tool surface ({total:,} tokens)", why, "GTS-REC-BUD-02")
    else:
        _file(rep, "GTS-REC-BUD-02", f"tool surface ({total:,} tokens) ≤ {cap:,}", b2)
    # Only a tool over budget can break this rule: by keeping its outputSchema, or by an
    # undocumented parameter. Being over budget is GTS-REC-BUD-01/-02, undocumented GTS-CORE-SCH-01.
    over = [t for t in tools if tokens(t) > MAX_TOOL_TOKENS or total > MAX_SERVER_TOKENS]
    kept = [f"{t['name']} still publishes outputSchema" for t in over if t.get("outputSchema")]
    bare = [
        f"{t['name']}.{p} has no description"
        for t in over
        for p, spec in properties(t).items()
        if not spec.get("description")
    ]
    _file(
        rep,
        "GTS-REC-BUD-03",
        "a tool over budget drops outputSchema and keeps its parameter documentation",
        kept + bare,
    )
    # The lead test reads form, not meaning, so a miss is a warning.
    _file(rep, "GTS-REC-SRCH-01", "description lead says what the tool returns", d1, warn=True)


def check_naming(
    rep: Report, tools: list[dict[str, Any]], namespace: str, *, recommended: bool
) -> None:
    names = [t.get("name", "") for t in tools]
    _file(
        rep,
        "GTS-CORE-NAM-01",
        "tool names match ^[a-z0-9_]{1,50}$",
        [repr(n) for n in names if not NAME_RE.match(n)],
    )
    _file(
        rep,
        "GTS-CORE-NAM-02",
        f"no tool name carries the server's prefix {namespace + '_'!r}",
        [n for n in names if n.startswith(namespace + "_")],
    )
    rep.rule = "GTS-CORE-NAM-03"
    rep.check(
        f"namespace {namespace!r} matches ^[a-z0-9]+$",
        bool(NAMESPACE_RE.match(namespace)),
        "it does not",
    )
    long = [n for n in names if len(namespace) + 1 + len(n) > 64]
    rep.check("<namespace>_<tool> is at most 64 characters", not long, ", ".join(long))
    if recommended:
        odd = [
            f"{t['name']} starts with {t['name'].split('_', 1)[0]!r}"
            for t in tools
            if t.get("name", "").split("_", 1)[0] not in VERBS and not tags_of(t) & {"ops", "meta"}
        ]
        _file(rep, "GTS-REC-SRCH-03", "tool names are verb_noun with a listed verb", odd, warn=True)


def check_read_only(rep: Report, tools: list[dict[str, Any]], readme: str | None) -> None:
    """GTS-CORE-RO-01: every tool declares readOnlyHint; a writing tool is in the README.

    Whether a tool really leaves state alone is not observable; the kit checks the declaration.
    """
    bad = []
    for tool in tools:
        hint = (tool.get("annotations") or {}).get("readOnlyHint")
        if hint is False and readme is not None and tool["name"] not in readme:
            bad.append(
                f"{tool['name']} declares readOnlyHint: false but the README does not list it"
            )
        elif not isinstance(hint, bool):
            bad.append(f"{tool['name']} declares no annotations.readOnlyHint")
    _file(rep, "GTS-CORE-RO-01", "every tool declares annotations.readOnlyHint", bad)


def check_output_schemas(rep: Report, tools: list[dict[str, Any]]) -> None:
    """GTS-CORE-SCH-04, the declared half: a published outputSchema describes the envelope.

    The results are validated against it in `behaviour`. Omitting the schema is allowed.
    """
    bad = []
    for tool in tools:
        schema = tool.get("outputSchema")
        text = json.dumps(schema)
        if schema and not all(key in text for key in ('"success"', '"_meta"', '"result')):
            bad.append(f"{tool['name']}: outputSchema names no success, result(s) and _meta")
    _file(rep, "GTS-CORE-SCH-04", "a published outputSchema describes the envelope", bad)


def _stem(name: str) -> tuple[str, ...]:
    words = [w for w in name.split("_") if w not in ("batch", "bulk")]
    return tuple(w.removesuffix("s") for w in words)


def check_pins(
    rep: Report, tools: list[dict[str, Any]], entrypoints: list[str], namespace: str
) -> None:
    """Entry points exist (GTS-REC-PIN-01) and name their batch sibling (GTS-REC-PIN-02).

    ponytail: siblings are derived from names only (`resolve_symbol` -> `resolve_symbols_batch`);
    a set-level sibling with an unrelated name is not found.
    """
    by_name = {t["name"]: t for t in tools}
    rep.rule = "GTS-REC-PIN-01"
    rep.check("one to four entry points", 1 <= len(entrypoints) <= 4, f"{len(entrypoints)} given")
    absent = [e for e in entrypoints if e not in by_name]
    rep.check("every entry point is in tools/list", not absent, ", ".join(absent))
    missing = []
    for pinned in entrypoints:
        description = (by_name.get(pinned) or {}).get("description") or ""
        for sibling in (t for t in by_name if t != pinned and _stem(t) == _stem(pinned)):
            # A whole name, optionally namespaced: `get_variants` is not named by `get_variants_by_gene`.
            named = rf"(?<![A-Za-z0-9_])(?:{namespace}_)?{re.escape(sibling)}(?![A-Za-z0-9_])"
            if not re.search(named, description):
                missing.append(f"{pinned} does not name {sibling}")
    _file(rep, "GTS-REC-PIN-02", "entry points name their batch sibling", missing)
