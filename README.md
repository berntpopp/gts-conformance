# gts-conformance

`gts-check`, the conformance kit for the Genetics Tool Server Specification (GTS) v1: it
checks a Model Context Protocol (MCP) server against the specification's rules (IDs
`GTS-*`). The specification text will be published separately.

**Status:** kit 0.3.0 checks 42 of the 65 rules (Core 28 of 29, Recommended 13 of 18,
Operational 1 of 18): 41 against the live server, GTS-CORE-VER-03 from the server's repository
(`--repo`). GTS-CORE-TXT-03 cannot be observed and is printed as `MANUAL`, for the maintainer
to attest. The other 22 are printed as `NOT-CHECKED` with the reason. Every rule line shows its
mode: `runtime`, `repo`, `manual` or `none` (no check yet). The package is `gts_conformance`; it needs `httpx` and
`jsonschema`, carries the envelope schema of
[genefoundry-envelope](https://github.com/berntpopp/genefoundry-envelope) v1.2.0 (its
sha256 is verified on import), and does not depend on the `genefoundry-router` package, from which its probes are adapted
(MIT, notice kept in each adapted module).

## Use

```bash
pip install git+https://github.com/berntpopp/gts-conformance@v0.3.0
gts-check https://my-server.example.org --level core
```

From a clone:

```bash
uv sync                                             # once
uv run gts-check https://my-server.example.org      # all three levels
uv run gts-check https://my-server.example.org --level core
uv run gts-check https://my-server.example.org --json > report.json
uv run pytest                                       # the kit's own tests
```

| Option | Meaning |
|---|---|
| `--level core\|recommended\|operational` | Highest level to check; each includes the ones below. Default `operational`. |
| `--name NAME` | Expected `serverInfo.name`. The run stops (exit 2) on another server. |
| `--namespace TOKEN` | The server's documented namespace (GTS-CORE-NAM-02, -03). Default: `serverInfo.name` without a `-link`, `-mcp` or `-server` suffix. |
| `--entrypoints a,b` | The nominated entry-point tools. Without it GTS-REC-PIN-01 and -02 are not checked. |
| `--free-text tool.param,…` | Search boxes that take free text, not one gene. They are left out of GTS-REC-BEH-05 and listed as `SKIP`. |
| `--call TOOL=JSON` | The arguments of one tool's control call, in place of its examples. Repeatable. The tool's result is validated even if it is an ops/meta tool; a tool that declares `readOnlyHint: false` is then called exactly once. |
| `--repo PATH` | The server's repository, read statically: `CHANGELOG.md` for GTS-CORE-VER-03, `README.md` for the writing tools of GTS-CORE-RO-01. Without it GTS-CORE-VER-03 is `NOT-CHECKED`. |
| `--token TOKEN` | Static service token, sent as a Bearer token. |
| `--delay SECONDS` | Wait before each tool request. Use it against a production server. |
| `--json` | The full report: every finding of every rule, with counts per level. |

The URL is the server's base URL, with or without `/mcp`. Only Streamable HTTP is
supported; stdio is not.

**The kit calls the server's tools.** It calls every tool once with the `examples` of its schema
and once with the same call plus an unknown argument, then with invalid enum values, filter values,
cursors, each `response_mode`, two `limit` values and four forms of one gene. A server
with 35 tools received fewer than 250 requests in four minutes at `--delay 1`. A tool that declares
`annotations.readOnlyHint: false` is never called, unless `--call` names it. A tool whose first
example answers `not_found` is called again with its later examples, then with up to three values
that an earlier tool of the same server returned under the parameter's own name (a record or
content id in place of a placeholder). Run it against a production server
only with the operator's consent.

Output: one line per rule, grouped by level, then a verdict per level. Exit code `0` no
failure in the requested levels, `1` at least one `FAIL` or `UNGATED`, `2` transport or
probe error.

```text
CORE
  GTS-CORE-TRN-01  runtime  PASS
  GTS-CORE-ERR-01  runtime  FAIL         get_record: an error envelope carries MCP isError:true — …
  GTS-CORE-TXT-03  manual   MANUAL       the kit cannot make an upstream return oversized text; …
  GTS-CORE-VER-03  repo     NOT-CHECKED  pass --repo with the server's repository
  …
Core: NOT CONFORMANT (1 failed, 0 ungated; 25 pass, 0 warn, 0 inconclusive, 2 not checked, 1 manual, of 29 rules)
```

| Status | Meaning |
|---|---|
| `PASS` | Every finding of the rule passed. |
| `FAIL` | At least one finding failed. Fails the level. |
| `UNGATED` | A tool could not be verified at all (a required parameter without `examples`). Fails the level. |
| `WARN` | A failed SHOULD or a heuristic hit (GTS-CORE-ENV-04, GTS-CORE-TXT-01, GTS-CORE-VER-03 `Removed`/`Added`, a claim of GTS-CORE-VER-04 that this run contradicts, GTS-REC-BEH-04, GTS-REC-ENV-01, GTS-REC-SRCH-01, -03). Does not fail the level. |
| `SKIP` | Inconclusive: the upstream was unreachable, or no call returned rows to test against. |
| `EXEMPT` | The specification puts the tool outside the rule: the OpenAI deep-research compatibility tools named exactly `search` and `fetch`, for GTS-CORE-ENV-02, -03 and GTS-CORE-TXT-01; and `pubtator-link`'s tool surface for GTS-REC-BUD-02 up to its 13,000-token hard cap. Listed under the rule, counted neither as a pass nor as a failure. |
| `NOT-CHECKED` | The kit has no check for the rule, lacks an option it needs, or the server has nothing that exercises it. |
| `MANUAL` | The rule cannot be observed by the kit; the server's maintainer attests it. Never a pass. A level whose only open rules are manual is reported "CONFORMANT if the manual rule is attested". |

In `--json` every rule carries `mode`, `counts` carries `MANUAL`, and the report carries
`repo` (whether `--repo` was given). The report ends with the coverage list (`coverage` in `--json`): for every tool, whether its
result was validated against the envelope schema, and the reason if it was not.

Report semantics:

- **UNGATED fails.** A tool for which no valid call can be built has not passed.
- **An unreachable upstream skips, never passes.**
- **Identity first.** With `--name`, the kit stops if `serverInfo.name` differs.
- **Never "conformant" on a partial check.** A level with a rule that is not checked or
  inconclusive is reported as "no failure found, conformance NOT established".
- **Format, not meaning.** As with the Beacon verifier, the kit checks the frame and the
  behaviour, not whether a variant classification is right.

## Limits

- The static mode (`--repo`) reads the changelog and the README only. Rules that read the
  Compose file, the image or the server's outbound HTTP code are not checked (all Operational
  rules but GTS-OPS-HLT-01).
- GTS-CORE-VER-03 trusts `CHANGELOG.md` (Keep a Changelog headings): a `BREAKING` heading in a
  step that does not raise MAJOR fails; `### Removed` outside a MAJOR step and `### Added` in a
  PATCH step warn, as those headings also cover changes outside the tool surface. Steps from a
  0.x version are skipped. The kit does not diff the tool surfaces of two releases.
- GTS-CORE-TRN-04 sends `initialize` with `Origin: https://gts-check.invalid` and expects a 4xx.
- GTS-CORE-SCH-04 checks that a published `outputSchema` names `success`, `result(s)` and
  `_meta`, and validates the control result against it. A tool without one passes (it MAY omit it).
- GTS-CORE-ENV-04 is a heuristic and warns: a record (of `results`, or the `result`) needs a
  value that looks like an identifier (a CURIE, an accession, an rsID, or a key `id`, `*_id`,
  `accession`, `pmid`) and another string beside it as the label. It cannot tell which
  identifier is the source's own.
- GTS-CORE-ENV-05 accepts `unsafe_for_clinical_use: true` at the top level (the example of the
  specification) or in `_meta`, as the rule text does not say where the flag sits.
- GTS-CORE-TXT-02 checks that fenced `text` is NFC; the forbidden code points and the
  `raw_sha256` format are checked by the envelope schema. That NFKC was not applied and no prose
  was deleted cannot be observed. A server whose results carry no `untrusted_text` object is
  `NOT-CHECKED`.
- GTS-CORE-TXT-03 is `MANUAL`: the kit cannot make an upstream send oversized text. A result it
  sees over the default bounds without a `truncated: true` fails the rule.
- GTS-CORE-TXT-04 sends instruction-like prose, with a bell and a bidirectional override, in
  one free string parameter of every tool and fails if `message`, `field`, `allowed_values`,
  `candidates`, `hint`, `recovery_action` or `_meta.next_commands` carries it back. An echoed
  upstream error body cannot be provoked.
- GTS-CORE-VER-04 reads `_meta."org.genefoundry/gts"` of `initialize`, else `gts` of
  `/health`. A server that declares nothing is `NOT-CHECKED`: the rule binds a server that
  claims conformance, and whether it claims one elsewhere is not observable.
- GTS-CORE-RO-01 checks the declared `readOnlyHint`, not whether a tool really leaves state
  alone; with `--repo`, a tool that declares `false` must be named in the README.
- GTS-CORE-TRN-05: when the server wants a token, the kit cannot tell a service token
  from a user's and reports `SKIP`.
- GTS-CORE-TXT-01 is a scan for strings over 500 characters that contain a space, outside
  an `untrusted_text` object in the example results; it warns and proves nothing when it
  passes.
- GTS-REC-BEH-05 probes gene parameters only (named `gene*` or `hgnc_id`, or described as a
  gene symbol). The probe gene is the first one that the kit's table of twelve genes knows (as
  symbol or identifier) among the parameter's own `examples`, then among the examples of the
  server's other gene parameters; otherwise it is KRAS. A free-text search box that the heuristic takes for a gene
  parameter is named with `--free-text`. A source that does not hold the probe gene
  is reported `UNGATED`.
- GTS-REC-PIN-02 finds a batch sibling by name (`resolve_symbol`, `resolve_symbols_batch`).
- A redirect or a non-200 answer to the first `POST /mcp` ends the run with exit 2 and the
  status in the message, not as a `FAIL` line of GTS-CORE-TRN-01.

## What exists (paths in [genefoundry-router](https://github.com/berntpopp/genefoundry-router))

| Check name | Source | Runs against | Notes |
|---|---|---|---|
| `transport` | `docs/conformance/conformance.py` | live server | httpx only |
| `behaviour` | `docs/conformance/behaviour.py` | live server | httpx only; probes derived from the server's own schema |
| `identifiers` | `docs/conformance/identifiers.py`, `identifiers.json` | live server | reuses the `behaviour` client; gene forms only so far |
| `surface` | `scripts/surface.py`, `scripts/check_tool_surface.py` | pinned baseline file | `scripts/mcp_survey.py` already applies the same measures to a live `tools/list` |
| `batch-pointers` | `scripts/check_batch_pointers.py` | baseline and registry | |
| `naming` | `check_leaf_name` in `genefoundry_router/cli.py` | registry and live names (`doctor --strict-naming`) | |
| `registry` | `genefoundry_router/registry.py`, `make validate` | registry entry | |
| `drift` | `scripts/snapshot_fleet.py`, `genefoundry_router/data/fleet-baseline.json` | live `tools/list` against a pinned snapshot | |
| `fencing` | `docs/conformance/untrusted-text-inventory.yml` and each server's hostile test | inventory and per-server tests | not a live probe |
| `http-policy` | `ci/http-policy-v1-conformance.py`, `ci/http-policy-v1.json` | the server's code, through an adapter fixture | seven named cases |
| `deploy` | `scripts/container_release.py validate-deployed-overlay` | Compose file | |
| `release-controls` | `scripts/audit_container_controls.py`, `scripts/validate_container_controls.py` | repository settings | needs repository API access |
| `data-identity` | `docs/conformance/runtime_data_identity.py` | data directory | |
| `image-scan` | per-repository scan workflow (Trivy evidence gate) | image | |
| `readme` | `scripts/check_readme.py` | repository | checks the fleet's fixed layout |
| `metadata` | `scripts/check_fleet_metadata.py` | `fleet-metadata.yaml` | |

`docs/conformance/contract_truth.py` (documentation examples call real parameters) is
useful to a server author and stays outside the rule set.

## Rule-to-check map

"Exists" means the check runs today in the router or the fleet; "partial" means it
exists but needs the change stated; "TBW" means to be written. "Kit" says whether
`gts-check` 0.3.0 checks the rule: `yes` against a live server, `repo` from the repository
(`--repo`), `manual` printed for the maintainer to attest.

### Core

| Rule | Check | State | Kit |
|---|---|---|---|
| GTS-CORE-TRN-01 | `transport`: `POST /mcp` returns 200, no 307; `GET /mcp` no 307 | exists | yes |
| GTS-CORE-TRN-02 | `transport`: JSON content type, no `Mcp-Session-Id` (tier `stateless`) | exists | yes |
| GTS-CORE-TRN-03 | `transport`: unsupported `MCP-Protocol-Version` returns 400 | exists | yes |
| GTS-CORE-TRN-04 | `transport`: `initialize` with a foreign `Origin` is rejected (4xx) | exists | yes |
| GTS-CORE-TRN-05 | `transport` accepts a service token; assert that `initialize` works without a user token | partial | yes |
| GTS-CORE-NAM-01 | `naming`: `check_leaf_name` charset and length | exists (move to live `tools/list`) | yes |
| GTS-CORE-NAM-02 | `naming`: no self-prefix | exists | yes |
| GTS-CORE-NAM-03 | `registry`: namespace pattern, qualified name at most 64 | exists | yes |
| GTS-CORE-SCH-01 | `surface` S1 | exists | yes |
| GTS-CORE-SCH-02 | `surface` S2, S3 | exists | yes |
| GTS-CORE-SCH-03 | `behaviour`: `check_declared_enums` | exists | yes |
| GTS-CORE-SCH-04 | a published `outputSchema` names the envelope; the control result validates against it | exists | yes |
| GTS-CORE-ENV-01 | `behaviour`: `envelope()` reads it; assert object and text mirror | partial | yes |
| GTS-CORE-ENV-02 | `behaviour`: `check_envelope_schema`, envelope schema v1.2 on every successful data result (`success`, top-level `results` or `result`) | exists | yes |
| GTS-CORE-ENV-03 | `behaviour`: `check_envelope_schema`, envelope schema v1.2 on every successful data result (`_meta.source`, `data_version`, `retrieved_at`, `request_id`, `elapsed_ms`); error results are not checked | exists | yes |
| GTS-CORE-ENV-04 | each record carries an identifier and a label (heuristic, warns) | exists | yes |
| GTS-CORE-ENV-05 | `unsafe_for_clinical_use: true` at the top level or in `_meta` | exists | yes |
| GTS-CORE-ERR-01 | `behaviour`: `_record_error_frame` (`isError`, frame keys) | exists | yes |
| GTS-CORE-ERR-02 | `behaviour`: `ERROR_CODES` | exists | yes |
| GTS-CORE-ERR-03 | `behaviour`: `check_argument_error` | exists | yes |
| GTS-CORE-TXT-01 | `fencing` inventory and per-server hostile test; live scan for long unfenced strings | partial | yes |
| GTS-CORE-TXT-02 | fenced `text` is NFC; code points and `raw_sha256` by the envelope schema | exists | yes |
| GTS-CORE-TXT-03 | not observable; an observed silent breach of the bounds fails | manual | manual |
| GTS-CORE-TXT-04 | hostile-input probe on one free string parameter per tool | exists | yes |
| GTS-CORE-VER-01 | `transport`: `serverInfo.name` equals `--name`; add the pattern | exists | yes |
| GTS-CORE-VER-02 | per-server `test_version_single_source.py`; live: version is SemVer and equals `/health` | partial | yes |
| GTS-CORE-VER-03 | `CHANGELOG.md` release steps against the version rule (`--repo`) | exists | repo |
| GTS-CORE-VER-04 | read the claim from `initialize` `_meta` (or `/health`), check its fields, compare with the run | exists | yes |
| GTS-CORE-RO-01 | every tool declares `annotations.readOnlyHint`; with `--repo` a writing tool is in the README | exists | yes |

### Recommended

| Rule | Check | State | Kit |
|---|---|---|---|
| GTS-REC-BEH-01 | `behaviour`: `check_silent_empty_filter` | exists | yes |
| GTS-REC-BEH-02 | `behaviour`: `check_response_modes` | exists | yes |
| GTS-REC-BEH-03 | `behaviour`: `check_pagination_honesty`, `check_total_is_not_the_page_size` | exists | yes |
| GTS-REC-BEH-04 | `behaviour`: `check_resolver_miss` | exists (advisory) | yes |
| GTS-REC-BEH-05 | `identifiers` | partial (gene parameters only; disease, variant, phenotype and bare numbers TBW) | yes |
| GTS-REC-BEH-06 | mixed batch probe | TBW | no |
| GTS-REC-ENV-01 | `behaviour` reads the pagination fields; invalid-cursor probe | partial | yes |
| GTS-REC-ENV-02 | null and empty blocks, result size | TBW | no |
| GTS-REC-ENV-03 | assert `recommended_citation` | TBW | no |
| GTS-REC-BUD-01 | `surface` B1 | exists | yes |
| GTS-REC-BUD-02 | `surface` B2 | exists | yes |
| GTS-REC-BUD-03 | `surface`: a tool over budget (B1, B2) publishes no `outputSchema` and has no undocumented parameter (S1) | exists | yes |
| GTS-REC-SRCH-01 | `surface` D1 (`lead_states_return`) | exists (advisory; strict by flag) | yes |
| GTS-REC-SRCH-02 | description names the source; tags present | TBW | no |
| GTS-REC-SRCH-03 | `naming` strict (`doctor --strict-naming`) | exists | yes |
| GTS-REC-SRCH-04 | flag known synonyms of the shared parameter names | TBW | no |
| GTS-REC-PIN-01 | `registry` holds the entry points; assert each one is in `tools/list` | partial | yes |
| GTS-REC-PIN-02 | `batch-pointers` D2 | exists | yes |

### Operational

| Rule | Check | State | Kit |
|---|---|---|---|
| GTS-OPS-HLT-01 | `transport`: `/health` returns 200 with `status`, `version`, `transport` | exists | yes |
| GTS-OPS-HTTP-01 | `http-policy`: `https_only`, `reject_syntactic_userinfo`, `normalized_exact_origin` | exists (needs the server's adapter fixture) | no |
| GTS-OPS-HTTP-02 | `http-policy`: `request_hook_checks_each_redirect_hop`, `redirect_limit_at_most_five` | exists | no |
| GTS-OPS-HTTP-03 | `http-policy`: `decoded_streaming_byte_cap` | exists | no |
| GTS-OPS-HTTP-04 | `http-policy`: `fixed_host_free_non_retryable_error` | exists | no |
| GTS-OPS-DEP-01 | `deploy`: `single-deployed-file`, `project-name`, `application-image`, `volume-name` | exists | no |
| GTS-OPS-DEP-02 | `release-controls`: tag ruleset | exists (needs repository access) | no |
| GTS-OPS-DEP-03 | `data-identity`; `/health` field | partial (`/health` not checked yet) | no |
| GTS-OPS-CTR-01 | Compose and Dockerfile inspection | TBW | no |
| GTS-OPS-CTR-02 | Compose inspection | TBW | no |
| GTS-OPS-CTR-03 | Compose inspection | TBW | no |
| GTS-OPS-CTR-04 | Compose inspection (no `ports` in the deployed file) | TBW | no |
| GTS-OPS-CTR-05 | secret scan of image and repository | TBW | no |
| GTS-OPS-CTR-06 | `image-scan` workflow; digest pin by Dockerfile inspection | partial | no |
| GTS-OPS-CTR-07 | log review | TBW (manual) | no |
| GTS-OPS-META-01 | `metadata` | exists | no |
| GTS-OPS-META-02 | `readme`, per-server tool-table test | partial (generalise the layout rule) | no |
| GTS-OPS-META-03 | `readme` (LICENSE); CITATION.cff present | partial | no |

### Count

| Level | Rules | Exists | Partial | Manual | TBW | In kit 0.3.0 |
|---|---|---|---|---|---|---|
| Core | 29 | 24 | 4 | 1 | 0 | 28 checked (27 runtime, 1 repo), 1 manual |
| Recommended | 18 | 10 | 3 | 0 | 5 | 13 |
| Operational | 18 | 8 | 4 | 0 | 6 | 1 |
| Total | 65 | 42 | 11 | 1 | 11 | 42 checked, 1 manual |

Not in the kit although a check exists or partly exists: eleven Operational rules that need the repository or the deployment
(GTS-OPS-HTTP-01 to -04, GTS-OPS-DEP-01 to -03, GTS-OPS-CTR-06, GTS-OPS-META-01 to -03).
