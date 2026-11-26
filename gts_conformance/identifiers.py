"""Foreign-identifier probe (GTS-REC-BEH-05), gene parameters only.

For every tool parameter that takes a gene, the probe sends each well-formed form of one known
gene (symbol, Ensembl, HGNC and NCBI Gene id) and classifies the answer. The gene is the first
one the kit's table knows among the parameter's own `examples`, then among the examples of the
server's other gene parameters, else KRAS. The first form
answered with a non-empty success is the positive control; its rows are what every other form is
compared against.

  PASS  resolved (the control's rows, or rows / `resolved_from` naming the gene), rejected
        (`invalid_input` with `field`, `allowed_values` and a converter in `_meta.next_commands`)
        or flagged (a success listing the value under an unsupported/invalid/rejected key)
  FAIL  silent_empty, wrong_entity, absence, internal, self_loop, unactionable
  UNGATED  no form produced a control, so nothing about the parameter was verified
  SKIP  the upstream is unreachable

Adapted from genefoundry-router (docs/conformance/identifiers.py), MIT License,
Copyright (c) 2026 Bernt Popp. Changes: findings are recorded per GTS rule ID in the kit's
Report; fleet-only configuration and the command-line entry point are removed.
"""

from __future__ import annotations

import json
import re
from typing import Any, NamedTuple

from .behaviour import (
    META_TOOLS,
    Probe,
    ProtocolError,
    callable_safely,
    count_of,
    envelope,
    is_error_result,
    is_stringy,
    properties,
    rows,
    takes_array,
)
from .report import Report

RULE = "GTS-REC-BEH-05"
# ponytail: one entity. Add disease, variant and phenotype forms here as data when those checks
# are written.
ENTITIES: dict[str, Any] = {
    "gene": {
        "param_name": r"^((candidate_)?genes?(_symbols?|_ids?)?|hgnc_ids?)$",
        "param_description": r"^(an? )?(hgnc |approved |mouse )?(gene|marker) symbols?\b",
    }
}
# symbol: (Ensembl gene, HGNC, NCBI Gene), from the HGNC complete set. The probe gene is the first
# of these among the parameter's own `examples`, then among the examples of the server's other
# gene parameters: a gene the server documents is one its source holds (ClinGen has no dosage
# curation for KRAS). The first entry is the fallback.
# ponytail: a fixed table. A server whose examples name only other genes is probed with the
# fallback and may report UNGATED; add its gene here.
GENES: dict[str, tuple[str, str, str]] = {
    "KRAS": ("ENSG00000133703", "HGNC:6407", "NCBIGene:3845"),
    "BRCA1": ("ENSG00000012048", "HGNC:1100", "NCBIGene:672"),
    "BRCA2": ("ENSG00000139618", "HGNC:1101", "NCBIGene:675"),
    "TP53": ("ENSG00000141510", "HGNC:11998", "NCBIGene:7157"),
    "CFTR": ("ENSG00000001626", "HGNC:1884", "NCBIGene:1080"),
    "AAGAB": ("ENSG00000103591", "HGNC:25662", "NCBIGene:79719"),
    "SCN1A": ("ENSG00000144285", "HGNC:10585", "NCBIGene:6323"),
    "BRAF": ("ENSG00000157764", "HGNC:1097", "NCBIGene:673"),
    "UMOD": ("ENSG00000169344", "HGNC:12559", "NCBIGene:7369"),
    "PCSK9": ("ENSG00000169174", "HGNC:20001", "NCBIGene:255738"),
    "MEFV": ("ENSG00000103313", "HGNC:6998", "NCBIGene:4210"),
    "PAX6": ("ENSG00000007372", "HGNC:8620", "NCBIGene:5080"),
}


def gene_forms(*props: dict[str, Any]) -> dict[str, str]:
    """The four forms of the probe gene: from the `examples` of `props` in order, else KRAS."""

    def flat(value: Any) -> list[str]:
        if isinstance(value, list):
            return [item for part in value for item in flat(part)]
        return [value.lower()] if isinstance(value, str) else []

    table = {symbol: (symbol, *ids) for symbol, ids in GENES.items()}
    examples = [example for prop in props for example in flat(prop.get("examples"))]
    forms = next(
        (
            forms
            for example in examples
            for forms in table.values()
            if example in map(str.lower, forms)
        ),
        next(iter(table.values())),
    )
    return dict(zip(("symbol", "ensembl", "hgnc", "ncbigene"), forms, strict=True))


PASSING = {"resolved", "rejected", "flagged"}
TRANSIENT = {"upstream_unavailable", "rate_limited"}
# A success may carry the value under a key like these instead of failing the whole call. Keys
# that only claim absence (`not_found`, `unresolved`) do not count: that is the failure itself.
_FLAGGED_KEY = re.compile(r"unsupported|unaccepted|invalid|reject")
# Top-level fields of a single-record answer that restate the request rather than answer it.
_ECHO_KEY = re.compile(r"query|input|identifier|applied|filter|message|hint|note|warning|success$")


class Verdict(NamedTuple):
    kind: str  # one of PASSING, a FAIL class from the module docstring, or "inconclusive"
    detail: str = ""


def _mentions(value: Any, ids: list[str]) -> bool:
    text = json.dumps(value)
    return any(
        re.search(rf"(?<![A-Za-z0-9]){re.escape(i)}(?![A-Za-z0-9])", text, re.IGNORECASE)
        for i in ids
    )


def body(env: dict[str, Any], param: str, sent: str) -> list[Any]:
    """The answer itself: the result rows, or a single-record tool's own non-echo fields.

    Mentions are only ever looked for here, never in `_meta`, messages or echo blocks
    (`query`, `applied_filters`): an echo of the request identifies nothing.
    """
    found = rows(env)
    if found is not None:
        return found
    record = {
        k: v
        for k, v in env.items()
        if not k.startswith("_")
        and k not in (param, "resolved_from")
        and not _ECHO_KEY.match(k)
        and v not in (None, False, 0, "", [], {})
        and not (isinstance(v, str) and v.lower() == sent.lower())
    }
    return [record] if record else []


def answered(result: dict[str, Any], param: str, sent: str) -> list[Any] | None:
    """The body of a non-empty success — what makes a form the positive control — else None."""
    env = envelope(result)
    if is_error_result(result, env) or count_of(env) == 0:
        return None
    return body(env, param, sent) or None


def classify(
    tool: str,
    param: str,
    sent: str,
    result: dict[str, Any],
    ids: list[str],
    control: list[Any] | None = None,
    namespace: str = "",
) -> Verdict:
    """Classify one answer to `tool(param=sent)` against the control's rows. Pure: no I/O."""
    env = envelope(result)
    if is_error_result(result, env):
        code = env.get("error_code")
        if code in TRANSIENT:
            return Verdict("inconclusive", f"upstream inconclusive ({code})")
        if code == "internal":
            return Verdict("internal", "internal error for a well-formed identifier")
        if code != "invalid_input":
            return Verdict("absence", f"{code!r} for a well-formed identifier of a gene it holds")
        steps = [
            s for s in (env.get("_meta") or {}).get("next_commands") or [] if isinstance(s, dict)
        ]

        def loops(step: dict[str, Any]) -> bool:
            value = (step.get("arguments") or {}).get(param)
            value = value[0] if isinstance(value, list) and len(value) == 1 else value
            same_tool = step.get("tool") in (tool, f"{namespace}_{tool}")
            return same_tool and isinstance(value, str) and value.lower() == sent.lower()

        def is_meta(step: dict[str, Any]) -> bool:
            return any(m in str(step.get("tool")) for m in META_TOOLS)

        if steps and all(loops(s) for s in steps):
            return Verdict("self_loop", f"every next_commands entry repeats {tool}({param}=...)")
        missing = [
            what
            for what, present in (
                ("field", env.get("field")),
                ("allowed_values", env.get("allowed_values")),
                # §2b: the converter belongs in next_commands; a meta tool is not one.
                (
                    "a converter in _meta.next_commands",
                    [s for s in steps if not loops(s) and not is_meta(s)],
                ),
            )
            if not present
        ]
        if missing:
            return Verdict("unactionable", "invalid_input without " + ", ".join(missing))
        return Verdict("rejected")

    answer = body(env, param, sent)
    others = [i for i in ids if i.lower() != sent.lower()]
    if answer and count_of(env) != 0:
        if answer == control:
            return Verdict("resolved", "same rows as the control")
        if _mentions(env.get("resolved_from") or "", others):
            return Verdict("resolved", "resolved_from names the gene")
        if _mentions(answer, others):
            return Verdict("resolved", "" if "resolved_from" in env else "no resolved_from")
    for key, value in env.items():
        if _FLAGGED_KEY.search(key) and _mentions(value, [sent]):
            return Verdict("flagged", f"listed under {key}")
    if not answer or count_of(env) == 0:
        return Verdict("silent_empty", "success with no rows and no unsupported-identifier marker")
    return Verdict(
        "wrong_entity", "a non-empty answer that is not the control's and never names the gene"
    )


def entity_params(tool: dict[str, Any]) -> dict[str, str]:
    """`{param: entity}` for one tool, derived from parameter names and descriptions."""
    found: dict[str, str] = {}
    for param, prop in properties(tool).items():
        if not is_stringy(prop):
            continue
        for entity, spec in ENTITIES.items():
            if re.search(spec["param_name"], param) or re.search(
                spec["param_description"], prop.get("description") or "", re.IGNORECASE
            ):
                found[param] = entity
                break
    return found


def base_args(
    tool: dict[str, Any], param: str, same_entity: dict[str, Any]
) -> dict[str, Any] | None:
    """A valid call around `param`: examples for the other required parameters.

    `param` itself needs no example (the probe fills it), and a required sibling that takes the
    same entity gets the probe gene, not its example — `gene_symbol=SCN1A, hgnc_id=HGNC:6407`
    would be a contradiction, not a probe. None when a remaining parameter has no example.
    """
    args: dict[str, Any] = {}
    props = properties(tool)
    for name in (tool.get("inputSchema") or {}).get("required") or []:
        if name == param:
            continue
        examples = (props.get(name) or {}).get("examples")
        if name in same_entity:
            args[name] = same_entity[name]
        elif examples:
            args[name] = examples[0]
        else:
            return None
    return args


def run(
    rep: Report,
    probe: Probe,
    tools: list[dict[str, Any]],
    namespace: str = "",
    free_text: frozenset[str] = frozenset(),
) -> None:
    """Probe every gene parameter; `free_text` names `tool.param` search boxes to leave out."""
    documented = [properties(t)[p] for t in tools for p in entity_params(t)]
    for tool in tools:
        name = tool["name"]
        if any(marker in name for marker in META_TOOLS) or not callable_safely(tool):
            continue
        params = entity_params(tool)
        props = properties(tool)

        def shaped(param: str, value: str, props: dict[str, Any] = props) -> Any:
            return [value] if takes_array(props[param]) else value

        for param, entity in params.items():
            if f"{name}.{param}" in free_text:
                # Reported, never silent: an exclusion the reader cannot see is a hidden pass.
                rep.skip(f"{name}.{param}", "declared free text with --free-text", RULE)
                continue
            forms = gene_forms(props[param], *documented)
            ids = list(forms.values())
            gene = ids[0]
            siblings = {p: shaped(p, gene) for p, e in params.items() if e == entity and p != param}
            base = base_args(tool, param, siblings)
            if base is None:
                rep.ungate(f"{name}.{param}", "another required parameter has no example", RULE)
                continue
            results: dict[str, dict[str, Any] | str] = {}
            for form, value in forms.items():
                try:
                    results[form] = probe.call(name, {**base, param: shaped(param, value)})
                except ProtocolError as exc:
                    results[form] = f"JSON-RPC error: {str(exc)[:80]}"
            control_form, control = next(
                (
                    (form, rows_)
                    for form, res in results.items()
                    if isinstance(res, dict) and (rows_ := answered(res, param, forms[form]))
                ),
                (None, None),
            )
            for form, res in results.items():
                label = f"{name}.{param}:{form}"
                if isinstance(res, str):
                    verdict = Verdict("unactionable", res)
                elif form == control_form:
                    verdict = Verdict("resolved", f"positive control ({gene})")
                else:
                    verdict = classify(name, param, forms[form], res, ids, control, namespace)
                text = f"[{verdict.kind}] {verdict.detail}"
                if verdict.kind == "inconclusive":
                    rep.skip(label, text, RULE)
                elif control_form is None:
                    rep.ungate(label, f"no form of {gene} gave a non-empty success; {text}", RULE)
                else:
                    rep.check(label, verdict.kind in PASSING, text, rule=RULE)
