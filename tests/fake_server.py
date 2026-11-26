"""A tiny in-process MCP server for the kit's tests, as an httpx transport.

`FakeServer()` conforms to every implemented rule; each name in `defects` breaks one of them.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

FORMS = {"KRAS", "ENSG00000133703", "HGNC:6407", "NCBIGene:3845"}
BRCA1 = {"BRCA1", "ENSG00000012048", "HGNC:1100", "NCBIGene:672"}  # a source without KRAS
ROWS = [
    {"hgnc_id": f"HGNC:{n}", "symbol": f"KRAS{n}", "biotype": "protein_coding"} for n in range(5)
]
MODES = ["minimal", "compact", "standard", "full"]


def prop(description: str, examples: list[Any] | None = None, **extra: Any) -> dict[str, Any]:
    out = {"type": "string", "description": description, **extra}
    if examples:
        out["examples"] = examples
    return out


class FakeServer(httpx.MockTransport):
    def __init__(self, *defects: str) -> None:
        self.defects = set(defects)
        super().__init__(self.handle)

    def has(self, defect: str) -> bool:
        return defect in self.defects

    # ------------------------------------------------------------------ tool list
    def tools(self) -> list[dict[str, Any]]:
        symbol = "BRCA1" if self.has("holds_brca1_only") else "KRAS"
        gene = prop("Gene symbol or identifier.", [symbol])
        search = {
            "name": "search_genes",
            "description": "Search genes. Returns matching gene records.",
            "inputSchema": {
                "type": "object",
                "required": ["gene_symbol"],
                "properties": {
                    "gene_symbol": gene,
                    "biotype": prop("Biotype filter."),
                    "category": prop("Category.", enum=["a", "b"]),
                    "limit": {"type": "integer", "description": "Page size."},
                    "cursor": prop("Opaque cursor."),
                    "response_mode": prop("Detail level.", enum=MODES),
                },
            },
        }
        resolve = {
            "name": "resolve_gene",
            "description": "Resolve one gene symbol to its record; for several use resolve_genes_batch.",
            "inputSchema": {
                "type": "object",
                "required": ["gene_symbol"],
                "properties": {"gene_symbol": gene},
            },
        }
        batch = {
            "name": "resolve_genes_batch",
            "description": "Resolve several gene symbols. Returns one record per symbol.",
            "inputSchema": {
                "type": "object",
                "required": ["gene_symbols"],
                "properties": {
                    "gene_symbols": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Gene symbols.",
                        "examples": [[symbol]],
                    }
                },
            },
        }
        if self.has("write_tool"):
            batch["annotations"] = {"readOnlyHint": False}
        if self.has("no_description"):
            del search["inputSchema"]["properties"]["biotype"]["description"]
        if self.has("no_examples"):
            del batch["inputSchema"]["properties"]["gene_symbols"]["examples"]
        if self.has("fat_tool"):
            search["outputSchema"] = {"description": "x" * 6000}
        if self.has("vague_lead"):
            search["description"] = "Use with care."
        if self.has("no_batch_pointer"):
            resolve["description"] = "Resolve one gene symbol to its record."
        if self.has("bad_tool_name"):
            batch["name"] = "Resolve-Genes"
        if self.has("self_prefix"):
            batch["name"] = "fake_resolve_genes_batch"
        if self.has("odd_verb"):
            batch["name"] = "fetch_genes_batch"
        tools = [search, resolve, batch]
        if self.has("compat_tools"):  # OpenAI deep-research compatibility tools
            for name, param, example in (("search", "query", "KRAS"), ("fetch", "id", "HGNC:6407")):
                tools.append(
                    {
                        "name": name,
                        "description": f"OpenAI {name}. Returns OpenAI's document shape.",
                        "inputSchema": {
                            "type": "object",
                            "required": [param],
                            "properties": {param: prop("Query or identifier.", [example])},
                        },
                    }
                )
        if self.has("handle_tool"):  # documented with a placeholder id, as record handles are
            examples = ["HGNC:999", "HGNC:1"] if self.has("second_example") else ["HGNC:999"]
            tools.append(
                {
                    "name": "get_gene",
                    "description": "Get one gene by HGNC id. Returns its record.",
                    "inputSchema": {
                        "type": "object",
                        "required": ["hgnc_id"],
                        "properties": {"hgnc_id": prop("HGNC id of search_genes.", examples)},
                    },
                }
            )
        return tools

    # ------------------------------------------------------------------ tool calls
    def error(self, code: str, field: str | None = None, **extra: Any) -> dict[str, Any]:
        env: dict[str, Any] = {
            "success": False,
            "error_code": "bad_request" if self.has("open_error_code") else code,
            "message": "The call cannot be answered as sent.",
            "retryable": False,
            "_meta": {"source": "fake", "request_id": "r", "elapsed_ms": 1},
            **extra,
        }
        if field:
            env.update(field=field, allowed_values=["see the tool schema"])
        return self.result(env, is_error=not self.has("no_is_error"))

    def result(self, env: dict[str, Any], is_error: bool = False) -> dict[str, Any]:
        text = "not json" if self.has("no_mirror") else json.dumps(env)
        return {
            "content": [{"type": "text", "text": text}],
            "structuredContent": env,
            "isError": is_error,
        }

    def call(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        tool = next(t for t in self.tools() if t["name"] == name)
        if (tool.get("annotations") or {}).get("readOnlyHint") is False:
            assert self.has("write_called_once"), "write tool called"
            self.defects.remove("write_called_once")
        props = tool["inputSchema"]["properties"]
        if self.has("unknown_arg_dropped"):
            args = {k: v for k, v in args.items() if k in props}
        for arg in tool["inputSchema"]["required"]:
            if arg not in args:
                return self.error("invalid_input", arg)
        for arg, value in args.items():
            if arg not in props:
                return self.error(
                    "not_found" if self.has("bad_arg_not_found") else "invalid_input", arg
                )
            if (
                "enum" in props[arg]
                and value not in props[arg]["enum"]
                and not self.has("enum_ignored")
            ):
                return self.error("invalid_input", arg)
        if name == "search":
            return self.result({"results": [{"id": "HGNC:6407", "title": "KRAS", "url": "u"}]})
        if name == "fetch":
            doc = {"id": args["id"], "title": "KRAS", "text": "word " * 200, "url": "u"}
            return self.result({**doc, "metadata": {"source": "fake"}})
        meta = {
            "source": "fake",
            "data_version": "2026-11-01",
            "retrieved_at": "2026-11-25T09:30:00Z",
            "request_id": "r",
            "elapsed_ms": 1,
        }
        for key in list(meta):
            if self.has(f"no_{key}"):
                del meta[key]
        if name == "get_gene":
            row = next((r for r in ROWS if r["hgnc_id"] == args["hgnc_id"]), None)
            return (
                self.result({"success": True, "result": row, "_meta": meta})
                if row
                else self.error("not_found")
            )
        genes = args.get("gene_symbols") or [args.get("gene_symbol")]
        known = all(g in (BRCA1 if self.has("holds_brca1_only") else FORMS) for g in genes)
        if self.has("ensembl_silent") and "ENSG00000133703" in genes:
            return self.result(
                {
                    "success": True,
                    "results": [],
                    "_meta": {**meta, "pagination": {"total_count": 0}},
                }
            )
        if name == "resolve_gene":
            if self.has("flat_record"):
                return self.result({"success": True, **ROWS[0], "_meta": meta})
            if known or self.has("miss_is_success"):
                return self.result(
                    {"success": True, "result": ROWS[0] if known else {}, "_meta": meta}
                )
            return self.error(
                "not_found", _meta={**meta, "next_commands": [{"tool": "search_genes"}]}
            )
        if not known:
            return self.error("not_found")
        if name == "resolve_genes_batch":
            page = {"total_count": 1, "has_more": False, "next_cursor": None}
            return self.result(
                {"success": True, "results": ROWS[:1], "_meta": {**meta, "pagination": page}}
            )
        # search_genes
        if "biotype" in args and args["biotype"] != "protein_coding":
            if not self.has("silent_filter"):
                return self.error("invalid_input", "biotype")
            return self.result(
                {
                    "success": True,
                    "results": [],
                    "_meta": {**meta, "pagination": {"total_count": 0}},
                }
            )
        if "cursor" in args and not self.has("cursor_ignored"):
            return self.error("invalid_input", "cursor")
        limit = args.get("limit", 3)
        mode = args.get("response_mode", "compact")
        keep = {"minimal": 1, "compact": 2}.get(mode, 3)
        rows = [dict(list(r.items())[:keep]) for r in ROWS[:limit]]
        if mode == "minimal" and self.has("minimal_empties"):
            rows = []
        page = {
            "total_count": len(rows) if self.has("total_is_page") else len(ROWS),
            "has_more": limit < len(ROWS),
            "next_cursor": None,
        }
        if self.has("bad_fence"):
            rows[0]["summary"] = {"kind": "untrusted_text", "text": "no provenance"}
        if self.has("long_text"):
            rows[0]["summary"] = "word " * 200
        if self.has("no_pagination"):
            return self.result(
                {"success": True, "results": rows, "total": page["total_count"], "_meta": meta}
            )
        return self.result(
            {"success": True, "results": rows, "_meta": {**meta, "pagination": page}}
        )

    # ------------------------------------------------------------------ HTTP
    def handle(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            body = {"status": "ok", "version": "1.2.3", "transport": "streamable-http"}
            if self.has("health_version"):
                body["version"] = "9.9.9"
            if self.has("health_no_transport"):
                del body["transport"]
            return httpx.Response(200, json=body)
        if request.method == "GET":
            return httpx.Response(307 if self.has("get_redirect") else 405)
        if request.headers.get("mcp-protocol-version") == "1999-01-01" and not self.has(
            "any_version"
        ):
            return httpx.Response(400)
        message = json.loads(request.content)
        method, params = message["method"], message.get("params") or {}
        headers = {"mcp-session-id": "s1"} if self.has("session_id") else {}
        if method == "initialize":
            name = "Fake_Server" if self.has("bad_server_name") else "fake"
            version = "three" if self.has("bad_version") else "1.2.3"
            result: dict[str, Any] = {
                "protocolVersion": "2025-06-18",
                "serverInfo": {"name": name, "version": version},
            }
        elif method == "tools/list":
            result = {"tools": self.tools()}
        else:
            result = self.call(params["name"], params.get("arguments") or {})
        return httpx.Response(
            200, json={"jsonrpc": "2.0", "id": message["id"], "result": result}, headers=headers
        )
