"""The per-rule report: every finding is filed under a GTS rule ID."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

LEVELS = {"core": "CORE", "recommended": "REC", "operational": "OPS"}  # ordered, each a superset
# Worst first; the worst finding wins. A rule is EXEMPT only when every finding is.
SEVERITY = ("FAIL", "UNGATED", "WARN", "PASS", "SKIP", "EXEMPT")
NOT_CHECKED = "NOT-CHECKED"
MANUAL = "MANUAL"  # not observable by the kit: the maintainer attests it; never a pass

TBW = "check to be written"
STATIC = "needs the server's repository or deployment, not a live endpoint"
# Every rule of spec/gts-v1.md, in its order. A reason marks a rule this kit never checks; a rule
# without one is implemented and is NOT-CHECKED only when the server gave nothing to probe.
RULES: dict[str, str] = {
    "GTS-CORE-TRN-01": "",
    "GTS-CORE-TRN-02": "",
    "GTS-CORE-TRN-03": "",
    "GTS-CORE-TRN-04": "",
    "GTS-CORE-TRN-05": "",
    "GTS-CORE-NAM-01": "",
    "GTS-CORE-NAM-02": "",
    "GTS-CORE-NAM-03": "",
    "GTS-CORE-SCH-01": "",
    "GTS-CORE-SCH-02": "",
    "GTS-CORE-SCH-03": "",
    "GTS-CORE-SCH-04": "",
    "GTS-CORE-ENV-01": "",
    "GTS-CORE-ENV-02": "",
    "GTS-CORE-ENV-03": "",
    "GTS-CORE-ENV-04": "",
    "GTS-CORE-ENV-05": "",
    "GTS-CORE-ERR-01": "",
    "GTS-CORE-ERR-02": "",
    "GTS-CORE-ERR-03": "",
    "GTS-CORE-TXT-01": "",
    "GTS-CORE-TXT-02": "",
    "GTS-CORE-TXT-03": "the kit cannot make an upstream return oversized text; attest the bound "
    "and its typed flag (an observed silent breach is still reported as FAIL)",
    "GTS-CORE-TXT-04": "",
    "GTS-CORE-VER-01": "",
    "GTS-CORE-VER-02": "",
    "GTS-CORE-VER-03": "",
    "GTS-CORE-VER-04": "",
    "GTS-CORE-RO-01": "",
    "GTS-REC-BEH-01": "",
    "GTS-REC-BEH-02": "",
    "GTS-REC-BEH-03": "",
    "GTS-REC-BEH-04": "",
    "GTS-REC-BEH-05": "",
    "GTS-REC-BEH-06": TBW,
    "GTS-REC-ENV-01": "",
    "GTS-REC-ENV-02": TBW,
    "GTS-REC-ENV-03": TBW,
    "GTS-REC-BUD-01": "",
    "GTS-REC-BUD-02": "",
    "GTS-REC-BUD-03": "",
    "GTS-REC-SRCH-01": "",
    "GTS-REC-SRCH-02": TBW,
    "GTS-REC-SRCH-03": "",
    "GTS-REC-SRCH-04": TBW,
    "GTS-REC-PIN-01": "",
    "GTS-REC-PIN-02": "",
    "GTS-OPS-HLT-01": "",
    "GTS-OPS-HTTP-01": STATIC,
    "GTS-OPS-HTTP-02": STATIC,
    "GTS-OPS-HTTP-03": STATIC,
    "GTS-OPS-HTTP-04": STATIC,
    "GTS-OPS-DEP-01": STATIC,
    "GTS-OPS-DEP-02": STATIC,
    "GTS-OPS-DEP-03": STATIC,
    "GTS-OPS-CTR-01": STATIC,
    "GTS-OPS-CTR-02": STATIC,
    "GTS-OPS-CTR-03": STATIC,
    "GTS-OPS-CTR-04": STATIC,
    "GTS-OPS-CTR-05": STATIC,
    "GTS-OPS-CTR-06": STATIC,
    "GTS-OPS-CTR-07": STATIC,
    "GTS-OPS-META-01": STATIC,
    "GTS-OPS-META-02": STATIC,
    "GTS-OPS-META-03": STATIC,
}
NOTHING_TO_PROBE = "nothing on this server exercises the check"
# How the kit checks a rule: "runtime" over MCP (the default for an implemented rule), "repo"
# from the server's repository (--repo), "manual" for the maintainer to attest, "none" not yet.
MODES = {"GTS-CORE-VER-03": "repo", "GTS-CORE-TXT-03": "manual"}
NEEDS_REPO = "pass --repo with the server's repository"


def mode(rule: str) -> str:
    return MODES.get(rule) or ("none" if RULES[rule] else "runtime")


@dataclass
class Report:
    rule: str = ""  # the rule the running check files under, unless a call names another
    findings: dict[str, list[tuple[str, str]]] = field(default_factory=dict)
    reasons: dict[str, str] = field(default_factory=dict)  # per-run NOT-CHECKED reasons
    # Per tool: "" when its result was validated against the envelope schema, else why not.
    coverage: dict[str, str] = field(default_factory=dict)

    def _add(self, status: str, text: str, rule: str | None) -> None:
        self.findings.setdefault(rule or self.rule, []).append((status, text))

    def check(self, label: str, ok: bool, detail: str = "", rule: str | None = None) -> bool:
        self._add("PASS" if ok else "FAIL", label if ok else f"{label} — {detail}", rule)
        return ok

    def ungate(self, label: str, why: str, rule: str | None = None) -> None:
        """Could not be verified at all. Counts as a failure: an unverifiable tool has not passed."""
        self._add("UNGATED", f"{label} — {why}", rule)

    def skip(self, label: str, why: str, rule: str | None = None) -> None:
        """Inconclusive (an unreachable upstream). Never a pass, never a failure."""
        self._add("SKIP", f"{label} — {why}", rule)

    def exempt(self, label: str, why: str, rule: str | None = None) -> None:
        """The specification puts this tool outside the rule. Never a pass, never a failure."""
        self._add("EXEMPT", f"{label} — {why}", rule)

    def warn(self, label: str, why: str, rule: str | None = None) -> None:
        """A failed SHOULD, or a heuristic hit. Reported, does not fail the level."""
        self._add("WARN", f"{label} — {why}", rule)

    def status(self, rule: str) -> str:
        seen = {status for status, _ in self.findings.get(rule, [])}
        unseen = MANUAL if mode(rule) == "manual" else NOT_CHECKED
        return next((s for s in SEVERITY if s in seen), unseen)

    def failed(self, levels: list[str]) -> bool:
        return any(
            self.status(rule) in ("FAIL", "UNGATED")
            for rule in RULES
            if rule.split("-")[1] in [LEVELS[level] for level in levels]
        )

    def to_dict(self, levels: list[str]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for level in levels:
            rules = []
            for rule in (r for r in RULES if r.split("-")[1] == LEVELS[level]):
                status = self.status(rule)
                entry: dict[str, Any] = {"id": rule, "status": status, "mode": mode(rule)}
                if status in (NOT_CHECKED, MANUAL):
                    entry["reason"] = self.reasons.get(rule) or RULES[rule] or NOTHING_TO_PROBE
                entry["findings"] = [
                    {"status": s, "detail": text} for s, text in self.findings.get(rule, [])
                ]
                rules.append(entry)
            counts = {
                s: sum(r["status"] == s for r in rules) for s in (*SEVERITY, NOT_CHECKED, MANUAL)
            }
            out[level] = {"rules": rules, "counts": counts}
        return out


def render(report: dict[str, Any], shown: int = 3) -> str:
    """The text report from `to_dict` output: one line per rule, then one verdict per level."""
    lines: list[str] = []
    verdicts: list[str] = []
    for level, block in report.items():
        lines.append(level.upper())
        for rule in block["rules"]:
            status = rule["status"]
            head = f"  {rule['id']:<17}{rule.get('mode', ''):<9}{status:<13}"
            if status in (NOT_CHECKED, MANUAL):
                lines.append(head + rule["reason"])
                continue
            details = [f["detail"] for f in rule["findings"] if f["status"] == status]
            first = "" if status == "PASS" else details[0]
            lines.append(f"{head}{first}".rstrip())
            if status != "PASS":
                lines += [f"  {'':<39}{d}" for d in details[1:shown]]
                if len(details) > shown:
                    lines.append(f"  {'':<39}... and {len(details) - shown} more (see --json)")
            if status != "EXEMPT":
                exempt = [f["detail"] for f in rule["findings"] if f["status"] == "EXEMPT"]
                lines += [f"  {'':<39}EXEMPT {d}" for d in exempt]
        c = block["counts"]
        bad = c["FAIL"] + c["UNGATED"]
        total = len(block["rules"])
        tail = (
            f"{c['PASS']} pass, {c['WARN']} warn, {c['SKIP']} inconclusive, "
            f"{c[NOT_CHECKED]} not checked, of {total} rules"
        )
        if c["EXEMPT"]:
            tail = tail.replace(" not checked,", f" not checked, {c['EXEMPT']} exempt,")
        if c.get(MANUAL):
            tail = tail.replace(" not checked,", f" not checked, {c[MANUAL]} manual,")
        # A level with unchecked rules is never called conformant: the kit has not seen it pass.
        if bad:
            verdict = f"NOT CONFORMANT ({c['FAIL']} failed, {c['UNGATED']} ungated; {tail})"
        elif c[NOT_CHECKED] or c["SKIP"]:
            verdict = f"no failure found, conformance NOT established ({tail})"
        elif c.get(MANUAL):
            n = c[MANUAL]
            verdict = (
                f"CONFORMANT if the {n} manual rule{'s are' if n != 1 else ' is'} attested ({tail})"
            )
        else:
            verdict = f"CONFORMANT ({tail})"
        verdicts.append(f"{level.capitalize()}: {verdict}")
        lines.append("")
    return "\n".join(lines + verdicts)
