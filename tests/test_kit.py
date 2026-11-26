"""One passing and one failing case per implemented rule, against the in-process fake server."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

import pytest
from fake_server import FakeServer

from gts_conformance import behaviour, cli, identifiers
from gts_conformance.report import NOT_CHECKED, RULES, Report, render

ROOT = Path(__file__).resolve().parents[1]
IMPLEMENTED = {rule for rule, reason in RULES.items() if not reason}
ARGS = {"namespace": "fake", "entrypoints": ["search_genes", "resolve_gene"]}


def statuses(*defects: str, **kwargs: object) -> dict[str, str]:
    report = cli.run("http://fake.test/mcp", transport=FakeServer(*defects), **{**ARGS, **kwargs})
    return {r["id"]: r["status"] for level in report["levels"].values() for r in level["rules"]}


def test_rule_list_is_the_specification() -> None:
    # the specification text is not published yet; GTS_SPEC points at a local copy
    spec_path = Path(os.environ.get("GTS_SPEC", ROOT / "spec/gts-v1.md"))
    if not spec_path.exists():
        pytest.skip("specification text not available")
    spec = spec_path.read_text()
    assert list(RULES) == list(
        dict.fromkeys(re.findall(r"^\| (GTS-[A-Z]+-[A-Z]+-\d+) \|", spec, re.MULTILINE))
    )


def test_conforming_server_passes_every_implemented_rule() -> None:
    got = statuses()
    assert {rule for rule, status in got.items() if status == "PASS"} == IMPLEMENTED
    assert {status for rule, status in got.items() if rule not in IMPLEMENTED} == {NOT_CHECKED}


@pytest.mark.parametrize(
    ("defect", "rule", "status"),
    [
        ("get_redirect", "GTS-CORE-TRN-01", "FAIL"),
        ("session_id", "GTS-CORE-TRN-02", "FAIL"),
        ("any_version", "GTS-CORE-TRN-03", "FAIL"),
        ("bad_tool_name", "GTS-CORE-NAM-01", "FAIL"),
        ("self_prefix", "GTS-CORE-NAM-02", "FAIL"),
        ("no_description", "GTS-CORE-SCH-01", "FAIL"),
        ("no_examples", "GTS-CORE-SCH-02", "FAIL"),
        ("no_examples", "GTS-CORE-ENV-01", "UNGATED"),
        ("enum_ignored", "GTS-CORE-SCH-03", "FAIL"),
        ("no_mirror", "GTS-CORE-ENV-01", "FAIL"),
        ("flat_record", "GTS-CORE-ENV-02", "FAIL"),
        ("no_source", "GTS-CORE-ENV-03", "FAIL"),
        ("no_data_version", "GTS-CORE-ENV-03", "FAIL"),
        ("no_retrieved_at", "GTS-CORE-ENV-03", "FAIL"),
        ("no_request_id", "GTS-CORE-ENV-03", "FAIL"),
        ("bad_fence", "GTS-CORE-TXT-01", "FAIL"),
        ("no_is_error", "GTS-CORE-ERR-01", "FAIL"),
        ("open_error_code", "GTS-CORE-ERR-02", "FAIL"),
        ("bad_arg_not_found", "GTS-CORE-ERR-03", "FAIL"),
        ("unknown_arg_dropped", "GTS-CORE-ERR-03", "FAIL"),
        ("long_text", "GTS-CORE-TXT-01", "WARN"),
        ("bad_server_name", "GTS-CORE-VER-01", "FAIL"),
        ("bad_version", "GTS-CORE-VER-02", "FAIL"),
        ("health_version", "GTS-CORE-VER-02", "FAIL"),
        ("silent_filter", "GTS-REC-BEH-01", "FAIL"),
        ("minimal_empties", "GTS-REC-BEH-02", "FAIL"),
        ("total_is_page", "GTS-REC-BEH-03", "FAIL"),
        ("miss_is_success", "GTS-REC-BEH-04", "WARN"),
        ("ensembl_silent", "GTS-REC-BEH-05", "FAIL"),
        ("no_pagination", "GTS-REC-ENV-01", "WARN"),
        ("cursor_ignored", "GTS-REC-ENV-01", "FAIL"),
        ("fat_tool", "GTS-REC-BUD-01", "FAIL"),
        ("fat_tool", "GTS-REC-BUD-03", "FAIL"),
        ("vague_lead", "GTS-REC-SRCH-01", "WARN"),
        ("odd_verb", "GTS-REC-SRCH-03", "WARN"),
        ("no_batch_pointer", "GTS-REC-PIN-02", "FAIL"),
        ("health_no_transport", "GTS-OPS-HLT-01", "FAIL"),
        ("health_version", "GTS-OPS-HLT-01", "FAIL"),
    ],
)
def test_defect_is_reported_under_its_rule(defect: str, rule: str, status: str) -> None:
    assert statuses(defect)[rule] == status


def test_a_missing_provenance_field_fails_only_its_rule_and_is_named() -> None:
    for field in ("source", "data_version", "retrieved_at"):
        report = cli.run("http://fake.test/mcp", transport=FakeServer(f"no_{field}"), **ARGS)
        failed = {
            r["id"]: r["findings"]
            for r in report["levels"]["core"]["rules"]
            if r["status"] == "FAIL"
        }
        assert list(failed) == ["GTS-CORE-ENV-03"]
        assert all(field in f["detail"] for f in failed["GTS-CORE-ENV-03"] if f["status"] == "FAIL")


COMPAT_RULES = ("GTS-CORE-ENV-02", "GTS-CORE-ENV-03", "GTS-CORE-TXT-01")


def test_openai_compatibility_tools_are_exempt_not_failed() -> None:
    report = cli.run("http://fake.test/mcp", transport=FakeServer("compat_tools"), **ARGS)
    assert report["conformant_so_far"]
    core = {r["id"]: r for r in report["levels"]["core"]["rules"]}
    for rule in COMPAT_RULES:
        assert core[rule]["status"] == "PASS"  # the three data tools still pass
        exempt = [f["detail"] for f in core[rule]["findings"] if f["status"] == "EXEMPT"]
        assert [d.split(":")[0] for d in exempt] == ["search", "fetch"]
    # Only the envelope rules are waived: the mirror and the error frame are still checked.
    assert core["GTS-CORE-ENV-01"]["status"] == core["GTS-CORE-ERR-03"]["status"] == "PASS"
    assert any("fetch" in f["detail"] for f in core["GTS-CORE-ERR-03"]["findings"])
    text = render(report["levels"])
    assert "EXEMPT fetch: results" in text
    assert "exempt" not in text.split("Core:")[1].splitlines()[0]  # no rule is EXEMPT as a whole


def test_the_exemption_is_by_exact_name_and_hides_no_defect() -> None:
    # A defect in a data tool is still found beside the exempt tools.
    assert statuses("compat_tools", "no_source")["GTS-CORE-ENV-03"] == "FAIL"
    assert statuses("compat_tools", "bad_arg_not_found")["GTS-CORE-ERR-03"] == "FAIL"
    rep = Report()
    for rule in COMPAT_RULES:
        rep.exempt("fetch: results", "why", rule)
    assert rep.status("GTS-CORE-ENV-02") == "EXEMPT"  # a rule with only exempt findings
    assert not rep.failed(["core"])
    report = rep.to_dict(["core"])
    assert report["core"]["counts"]["EXEMPT"] == 3
    assert re.search(r"GTS-CORE-ENV-02\s+EXEMPT\s+fetch: results", render(report))
    assert "26 not checked, 3 exempt, of 29 rules" in render(report)
    assert behaviour.COMPAT_TOOLS == ("search", "fetch")  # `search_genes` is a data tool


def test_vendored_envelope_schema_is_the_released_file() -> None:
    # update together with a genefoundry-envelope release
    path = ROOT / "gts_conformance/envelope-v1.2.schema.json"
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert digest == "c3c47e20d7dd189aac2568fc963b5514d7a5ac2c3e5f21d126f42c96d1ad1ae3"


def test_rules_that_need_an_option() -> None:
    assert statuses(namespace="Fake-NS")["GTS-CORE-NAM-03"] == "FAIL"
    assert statuses(entrypoints=["search_genes", "get_nothing"])["GTS-REC-PIN-01"] == "FAIL"
    assert statuses(entrypoints=None)["GTS-REC-PIN-01"] == NOT_CHECKED


def test_a_tool_that_declares_writes_is_never_called() -> None:
    assert statuses("write_tool")["GTS-CORE-ENV-01"] == "PASS"  # the fake asserts on such a call


def coverage(*defects: str, **kwargs: object) -> dict[str, str]:
    report = cli.run("http://fake.test/mcp", transport=FakeServer(*defects), **{**ARGS, **kwargs})
    return {c["tool"]: c["reason"] for c in report["coverage"] if not c["validated"]}


def test_every_tool_is_in_the_coverage_list_with_its_reason() -> None:
    assert coverage() == {}
    assert "readOnlyHint" in coverage("write_tool")["resolve_genes_batch"]
    assert "examples" in coverage("no_examples")["resolve_genes_batch"]
    assert coverage("compat_tools").keys() == {"search", "fetch"}


def test_a_placeholder_example_is_replaced_by_a_documented_or_returned_value() -> None:
    assert coverage("handle_tool") == {}  # the id that search_genes returned
    assert coverage("handle_tool", "second_example") == {}
    args = behaviour.better_args(
        {"inputSchema": {"properties": {"id": {"examples": ["x", "y"]}}}},
        {"id": "x"},
        [{"results": [{"id": "a", "nested": {"id": "a"}}, {"id": 7}, {"id": "b"}]}],
    )
    assert args == [{"id": "y"}, {"id": "a"}, {"id": "b"}]


def test_a_stated_call_replaces_the_examples_and_calls_a_write_tool_once() -> None:
    assert (
        "not_found"
        in coverage("handle_tool", calls={"get_gene": {"hgnc_id": "HGNC:77"}})["get_gene"]
    )
    calls = {"resolve_genes_batch": {"gene_symbols": ["KRAS"]}}
    assert coverage("write_tool", "write_called_once", calls=calls) == {}


def test_surface_budget_of_the_whole_server(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("gts_conformance.surface.MAX_SERVER_TOKENS", 10)
    assert statuses()["GTS-REC-BUD-02"] == "FAIL"


def test_level_core_runs_and_reports_core_only() -> None:
    got = statuses("silent_filter", level="core")
    assert all(rule.startswith("GTS-CORE-") for rule in got)
    assert "FAIL" not in got.values()


def test_long_strings_without_spaces_are_not_free_text() -> None:
    env = {"image_base64": "QUJD" * 300, "note": "word " * 200, "_meta": {"x": "word " * 200}}
    assert behaviour.unfenced_long_strings(env) == ["note"]


def test_a_core_rule_does_not_depend_on_the_level() -> None:
    assert statuses("health_version", level="core")["GTS-CORE-VER-02"] == "FAIL"


def test_budget_rule_three_needs_a_tool_over_budget() -> None:
    assert statuses("no_description")["GTS-REC-BUD-03"] == "PASS"


def test_hgnc_id_is_a_gene_parameter() -> None:
    tool = {"inputSchema": {"properties": {"hgnc_id": {"type": "string", "description": "CURIE"}}}}
    assert identifiers.entity_params(tool) == {"hgnc_id": "gene"}


def test_the_probe_gene_comes_from_the_parameters_own_examples() -> None:
    # A source that does not hold KRAS documents a gene it holds; the probe uses that one.
    got = statuses("holds_brca1_only")
    assert got["GTS-REC-BEH-05"] == "PASS"
    assert {rule for rule, status in got.items() if status == "PASS"} == IMPLEMENTED
    forms = identifiers.gene_forms
    assert forms({"examples": ["XYZ1", "AAGAB"]})["hgnc"] == "HGNC:25662"  # the first known one
    assert forms({"examples": [["hgnc:1100"]]})["symbol"] == "BRCA1"  # any form, any case, nested
    assert forms({})["symbol"] == forms({"examples": ["XYZ1"]})["symbol"] == "KRAS"  # fallback
    # A search box documented with a cytoband borrows the gene of the server's other tools.
    assert forms({"examples": ["1p36"]}, {"examples": ["BRCA1"]})["symbol"] == "BRCA1"
    assert forms({"examples": ["TP53"]}, {"examples": ["BRCA1"]})["symbol"] == "TP53"
    assert all(len(set(ids)) == 3 for ids in identifiers.GENES.values())


def test_a_declared_free_text_parameter_is_skipped_not_passed() -> None:
    every = [
        "search_genes.gene_symbol",
        "resolve_gene.gene_symbol",
        "resolve_genes_batch.gene_symbols",
    ]
    assert statuses("ensembl_silent", free_text=every)["GTS-REC-BEH-05"] == "SKIP"
    assert statuses("ensembl_silent", free_text=every[:1])["GTS-REC-BEH-05"] == "FAIL"


def test_cli_text_json_and_exit_codes(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    server = FakeServer("no_is_error")
    real = cli.run
    monkeypatch.setattr(cli, "run", lambda url, **kw: real(url, **{**kw, "transport": server}))
    assert cli.main(["http://fake.test", "--json", "--level", "core"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["server"] == {"name": "fake", "version": "1.2.3"}
    assert report["levels"]["core"]["counts"]["FAIL"] == 1

    assert cli.main(["http://fake.test"]) == 1
    text = capsys.readouterr().out
    assert re.search(r"GTS-CORE-ERR-01\s+FAIL", text)
    assert "Core: NOT CONFORMANT (1 failed" in text
    assert re.search(r"GTS-OPS-DEP-01\s+NOT-CHECKED", text)

    assert "Envelope schema: 3 of 3 tools validated" in text

    assert cli.main(["http://fake.test", "--call", 'resolve_gene={"gene_symbol": "NOPE"}']) == 1
    assert "not validated: resolve_gene — no data: not_found" in capsys.readouterr().out

    assert cli.main(["http://fake.test", "--name", "another-server"]) == 2
    server.defects.clear()
    assert cli.main(["http://fake.test", "--level", "core"]) == 0
    # Unchecked rules remain, so a clean run is never announced as conformant.
    assert "conformance NOT established" in capsys.readouterr().out


def test_surface_budget_exemption_is_capped_and_only_for_pubtator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gts_conformance import surface

    assert surface.SERVER_TOKEN_CAPS == {"pubtator-link": 13_000}
    tools = [{"name": "get_x", "description": "Returns x. " + "a" * 400}]  # ~100 tokens
    monkeypatch.setattr(surface, "MAX_SERVER_TOKENS", 50)

    def bud02(server: str, cap: int) -> str:
        monkeypatch.setitem(surface.SERVER_TOKEN_CAPS, "pubtator-link", cap)
        rep = Report()
        surface.check_surface(rep, tools, recommended=True, server=server)
        return rep.status("GTS-REC-BUD-02")

    assert bud02("pubtator-link", 1_000) == "EXEMPT"  # over the limit, under the cap
    assert bud02("pubtator-link", 60) == "FAIL"  # over the hard cap
    assert bud02("other-link", 1_000) == "FAIL"  # no other server is exempt
