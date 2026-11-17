#!/usr/bin/env python3
"""Keep a debugging case as facts, hypotheses and the matrix between them.

A case is one append-only JSON Lines file, .rootcause/<case>.jsonl. Every command appends one
event; the state is replayed from the events. `next` says which step of the loop the case is in
and the one thing to do. `report` refuses until exactly one hypothesis explains every fact and an
adversarial review has passed it. Standard library only.

Exit codes: 0 done, 1 refused (the message says why and what to do instead), 2 bad usage.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

SOURCES = ("report", "log", "trace", "metric", "config", "repro", "git", "code", "other")
SEEN = ("variable", "both", "control")
CELLS = ("explains", "contradicts", "neutral")
TACTICS = ("reverify", "split", "merge", "combine", "new")
GATES = ("signals", "matrix", "validation")
CASE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
ID_RE = re.compile(r"^[FH][1-9][0-9]{0,4}$")
MAX_TEXT = 2000
CHANGES = {"fact", "retract", "hypo", "mark", "tactic"}

TACTIC_HELP = {
    "reverify": "Re-verify how the facts were gathered: rerun each query, check its time window, "
                "host and build. A fact gathered wrong is retracted (`retract`), then logged with "
                "`tactic CASE reverify`.",
    "split": "Split a coarse hypothesis into narrower ones (`hypo CASE TEXT --tactic split --from H1`), "
             "or log `tactic CASE split` if none is coarse.",
    "merge": "Merge hypotheses that are the same fault seen twice (`hypo ... --tactic merge --from H1,H2`), "
             "or log `tactic CASE merge` if none overlap.",
    "combine": "Combine complementary partial causes that together explain everything "
               "(`hypo ... --tactic combine --from H1,H2`), or log `tactic CASE combine`.",
    "new": "Tactics 1 to 4 are spent. Only now write an entirely new hypothesis "
           "(`hypo CASE TEXT --tactic new`).",
}


class Refused(Exception):
    pass


@dataclass
class Fact:
    id: str
    text: str
    source: str
    cite: str
    seen: str
    layer: int
    check: str | None
    seq: int
    retracted: str | None = None

    @property
    def signal(self) -> bool:
        return self.seen != "both"


@dataclass
class Hypo:
    id: str
    text: str
    tactic: str
    parents: list[str]
    seq: int
    retired_by: str | None = None


@dataclass
class Case:
    name: str
    symptom: str = ""
    control: str = ""
    facts: dict[str, Fact] = field(default_factory=dict)
    hypos: dict[str, Hypo] = field(default_factory=dict)
    cells: dict[tuple[str, str], tuple[str, str, int]] = field(default_factory=dict)
    tactics: list[tuple[str, int, str]] = field(default_factory=list)
    gaps: list[dict] = field(default_factory=list)
    reviews: list[dict] = field(default_factory=list)
    last_change: int = 0
    cycle_start: int = 0

    def active_facts(self) -> list[Fact]:
        return [f for f in self.facts.values() if not f.retracted]

    def columns(self) -> list[Hypo]:
        return [h for h in self.hypos.values() if not h.retired_by]


# ---------------------------------------------------------------- storage


def case_path(root: Path, name: str) -> Path:
    if not CASE_RE.match(name):
        raise Refused(f"case name {name!r} must be lowercase letters, digits and hyphens (max 64)")
    return root / f"{name}.jsonl"


def clean(text: str, what: str) -> str:
    text = (text or "").strip()
    if not text:
        raise Refused(f"{what} is empty")
    if len(text) > MAX_TEXT:
        raise Refused(f"{what} is over {MAX_TEXT} characters")
    if any(ord(c) < 32 and c not in "\n\t" for c in text) or "\x7f" in text:
        raise Refused(f"{what} has control characters")
    return text


def read_events(path: Path) -> list[dict]:
    if not path.exists():
        raise Refused(f"no case at {path}; start one with `new`")
    events = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError as e:
            raise Refused(f"{path}:{n} is not JSON ({e.msg})") from None
        if not isinstance(ev, dict) or "type" not in ev:
            raise Refused(f"{path}:{n} has no event type")
        events.append(ev)
    if not events or events[0]["type"] != "new":
        raise Refused(f"{path} does not start with a `new` event")
    return events


def append(path: Path, event: dict) -> None:
    event = {"type": event.pop("type"), "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), **event}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False, sort_keys=False) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def replay(name: str, events: list[dict]) -> Case:
    case = Case(name=name)
    nf = nh = 0
    for seq, ev in enumerate(events, 1):
        kind = ev["type"]
        if kind == "new":
            case.symptom, case.control = ev["symptom"], ev["control"]
        elif kind == "fact":
            nf += 1
            fid = f"F{nf}"
            case.facts[fid] = Fact(fid, ev["text"], ev["source"], ev["cite"], ev["seen"],
                                   int(ev.get("layer", 0)), ev.get("check"), seq)
            case.cycle_start = seq
        elif kind == "retract":
            case.facts[ev["fact"]].retracted = ev["why"]
            case.cycle_start = seq
        elif kind == "hypo":
            nh += 1
            hid = f"H{nh}"
            case.hypos[hid] = Hypo(hid, ev["text"], ev["tactic"], list(ev.get("parents", [])), seq)
            if ev["tactic"] in ("split", "merge"):
                for p in ev.get("parents", []):
                    parent = case.hypos[p]
                    if not parent.retired_by:
                        parent.retired_by = f"{ev['tactic']} into {hid}"
                    elif ev["tactic"] == "split":
                        parent.retired_by += f", {hid}"
            if ev["tactic"] != "new" or ev.get("as_tactic"):
                case.tactics.append((ev["tactic"], seq, f"{hid}: {ev['text']}"))
        elif kind == "mark":
            case.cells[(ev["hypo"], ev["fact"])] = (ev["verdict"], ev["why"], seq)
        elif kind == "tactic":
            case.tactics.append((ev["tactic"], seq, ev.get("note", "")))
        elif kind == "gap":
            case.gaps.append({"text": ev["text"], "layer": ev.get("layer", 0), "seq": seq})
        elif kind == "review":
            case.reviews.append({"gate": ev["gate"], "verdict": ev["verdict"], "by": ev["by"],
                                 "note": ev.get("note", ""), "seq": seq})
        else:
            raise Refused(f"event {seq} has unknown type {kind!r}")
        if kind in CHANGES:
            case.last_change = seq
    return case


def load(root: Path, name: str) -> tuple[Path, Case]:
    path = case_path(root, name)
    return path, replay(name, read_events(path))


# ---------------------------------------------------------------- the loop


def assess(case: Case) -> dict:
    """Pure: which step the case is in, and the one thing to do next."""
    facts = case.active_facts()
    signals = [f for f in facts if f.signal]
    cols = case.columns()
    discarded = {}
    for h in cols:
        for f in facts:
            cell = case.cells.get((h.id, f.id))
            if cell and cell[0] == "contradicts":
                discarded[h.id] = f.id
                break
    live = [h for h in cols if h.id not in discarded]

    fits = {f.id: [h.id for h in live if case.cells.get((h.id, f.id), ("",))[0] == "explains"] for f in signals}
    strength = {}
    for f in signals:
        n = len(fits[f.id])
        if not live:
            strength[f.id] = "unknown"
        elif n == 0:
            strength[f.id] = "unexplained"
        elif n == 1 or 3 * n <= len(live):
            strength[f.id] = "strong"
        elif 2 * n > len(live):
            strength[f.id] = "weak"
        else:
            strength[f.id] = "medium"
    explained = [f for f in signals if fits[f.id]]
    strongest = min(explained, key=lambda f: (len(fits[f.id]), f.seq)) if explained else None

    unmarked = [(h.id, f.id) for h in live for f in facts if (h.id, f.id) not in case.cells]
    satisfied = [h.id for h in live
                 if all((h.id, f.id) in case.cells for f in facts)
                 and all(case.cells[(h.id, f.id)][0] == "explains" for f in signals)]

    done_tactics = {t for t, seq, _ in case.tactics if seq > case.cycle_start}
    next_tactic = next((t for t in TACTICS if t not in done_tactics), None)

    out = {
        "case": case.name,
        "facts": len(facts),
        "signals": [{"fact": f.id, "fits": fits[f.id], "strength": strength[f.id]} for f in signals],
        "live": [h.id for h in live],
        "discarded": discarded,
        "retired": {h.id: h.retired_by for h in case.hypos.values() if h.retired_by},
        "satisfied": satisfied,
        "unmarked": [f"{h}x{f}" for h, f in unmarked],
        "strongest": None,
        "next_tactic": next_tactic,
        "reminders": reminders(case),
    }
    if strongest:
        out["strongest"] = {"fact": strongest.id, "points_to": fits[strongest.id]}

    def step(name: str, do: str) -> dict:
        out["step"], out["do"] = name, do
        return out

    if not signals:
        return step("gather", "Record facts with `fact` until at least one is seen on only one side "
                              "(--seen variable or control). If everything shows up in both, the control "
                              "is too close or broken: pick a sharper one, or gather from one layer down.")
    if not case.hypos:
        target = signals[0].id
        return step("hypothesize", f"Write ONE hypothesis that explains signal {target} (`hypo`). "
                                   "Don't list every possibility; steer by the signal.")
    signal_ids = {f.id for f in signals}
    sig_unmarked = [(h, f) for h, f in unmarked if f in signal_ids]
    if sig_unmarked:
        order = sorted(sig_unmarked, key=lambda c: (c[0] not in (out["strongest"] or {}).get("points_to", []), c))
        cells = ", ".join(f"{h} on {f}" for h, f in order[:6])
        return step("matrix", f"Mark {cells} (`mark CASE H F explains|contradicts|neutral --why ...`). "
                              "Each verdict cites the evidence.")
    if unmarked:
        cells = ", ".join(f"{h} on {f}" for h, f in unmarked[:6])
        return step("validate", f"Validate against the noise too: mark {cells}.")
    if len(satisfied) == 1:
        h = satisfied[0]
        review = latest_review(case, "validation")
        if not review or review["seq"] < case.last_change:
            return step("review", f"{h} explains every fact. Run the adversarial reviewer on the validation "
                                  "gate (references/reviewer.md), on a different model, and record it with "
                                  "`review CASE validation --verdict pass|fail --by MODEL`.")
        if review["verdict"] != "pass":
            return step("review", f"The validation review failed: {review['note'] or 'no note'}. "
                                  "Act on it (a new fact, a re-mark, a retraction), then review again.")
        out["root_cause"] = h
        return step("root-cause", f"{h} is the root cause. Write the report with `report CASE`.")
    if len(satisfied) > 1:
        return step("gather", f"Several hypotheses survive ({', '.join(satisfied)}): too few facts. "
                              "Gather a fact that one predicts and the others don't. "
                              "More facts, not more hypotheses.")
    if next_tactic:
        return step("tactics", f"Every hypothesis falls short. Tactic {TACTICS.index(next_tactic) + 1}: "
                               f"{TACTIC_HELP[next_tactic]} Rebuild the matrix after it.")
    layer = max((f.layer for f in facts), default=0) + 1
    return step("discover", f"Tactic 5 found nothing. Progressive signal discovery: gather facts from "
                            f"layer {layer} (one layer down) with `fact --layer {layer}`. If you can't "
                            "reach that layer, record it with `gap` and tell the human.")


def latest_review(case: Case, gate: str) -> dict | None:
    found = [r for r in case.reviews if r["gate"] == gate]
    return found[-1] if found else None


def reminders(case: Case) -> list[str]:
    out = []
    facts = case.active_facts()
    last_fact = max((f.seq for f in facts if f.signal), default=0)
    sig = latest_review(case, "signals")
    if last_fact and (not sig or sig["seq"] < last_fact):
        out.append("gate 1 (signals) has no review since the last signal fact: is each one absent "
                   "from the control, and is the control itself sound?")
    last_mark = max((c[2] for c in case.cells.values()), default=0)
    mat = latest_review(case, "matrix")
    if last_mark and (not mat or mat["seq"] < last_mark):
        out.append("gate 2 (matrix) has no review since the last mark: how many hypotheses fit each "
                   "signal, and were tactics 1 to 4 tried before any new hypothesis?")
    return out


# ---------------------------------------------------------------- commands


def need(case: Case, ident: str, kind: str):
    table = case.facts if kind == "F" else case.hypos
    if not ID_RE.match(ident or "") or ident[0] != kind or ident not in table:
        raise Refused(f"no {'fact' if kind == 'F' else 'hypothesis'} {ident!r} in case {case.name}")
    return table[ident]


def cmd_new(a, root):
    path = case_path(root, a.case)
    if path.exists():
        raise Refused(f"case {a.case} already exists at {path}")
    append(path, {"type": "new", "symptom": clean(a.symptom, "symptom"), "control": clean(a.control, "control")})
    print(f"opened {path}")


def cmd_fact(a, root):
    path, case = load(root, a.case)
    if a.layer < 0 or a.layer > 20:
        raise Refused("--layer is 0 (where the symptom shows) to 20")
    ev = {"type": "fact", "text": clean(a.text, "fact"), "source": a.source, "cite": clean(a.cite, "--cite"),
          "seen": a.seen, "layer": a.layer}
    if a.check:
        ev["check"] = clean(a.check, "--check")
    append(path, ev)
    print(f"F{len(case.facts) + 1} ({'signal' if a.seen != 'both' else 'noise'})")


def cmd_retract(a, root):
    path, case = load(root, a.case)
    fact = need(case, a.fact, "F")
    if fact.retracted:
        raise Refused(f"{a.fact} is already retracted")
    append(path, {"type": "retract", "fact": a.fact, "why": clean(a.why, "--why")})
    print(f"retracted {a.fact}")


def cmd_hypo(a, root):
    path, case = load(root, a.case)
    parents = [p.strip() for p in (a.parents or "").split(",") if p.strip()]
    for p in parents:
        retired = need(case, p, "H").retired_by
        if retired and not (a.tactic == "split" and retired.startswith("split")):
            raise Refused(f"{p} was already {retired}")
    if a.tactic == "split" and len(parents) != 1:
        raise Refused("a split names exactly one parent: --from H1")
    if a.tactic in ("merge", "combine") and len(parents) < 2:
        raise Refused(f"a {a.tactic} names two or more parents: --from H1,H2")
    ev = {"type": "hypo", "text": clean(a.text, "hypothesis"), "tactic": a.tactic, "parents": parents}
    if a.tactic == "new":
        if parents:
            raise Refused("a new hypothesis has no parents; use split, merge or combine")
        state = assess(case)
        if state["step"] == "tactics" and state["next_tactic"] != "new":
            raise Refused(f"every hypothesis falls short and tactic {state['next_tactic']!r} hasn't run. "
                          f"{TACTIC_HELP[state['next_tactic']]}")
        if state["step"] in ("gather", "discover") and case.hypos:
            raise Refused(f"the case needs facts, not hypotheses. {state['do']}")
        if state["step"] in ("review", "root-cause"):
            raise Refused(f"{state['satisfied'][0]} already explains every fact; a rival needs a fact it explains "
                          "and the current one doesn't. Record that fact first.")
        if state["step"] == "tactics":
            ev["as_tactic"] = True
    append(path, ev)
    hid = f"H{len(case.hypos) + 1}"
    print(f"{hid}; mark it against every fact ({len(case.active_facts())})")


def cmd_mark(a, root):
    path, case = load(root, a.case)
    hypo = need(case, a.hypo, "H")
    fact = need(case, a.fact, "F")
    if hypo.retired_by:
        raise Refused(f"{a.hypo} was {hypo.retired_by}; mark its successor instead")
    if fact.retracted:
        raise Refused(f"{a.fact} was retracted: {fact.retracted}")
    append(path, {"type": "mark", "hypo": a.hypo, "fact": a.fact, "verdict": a.verdict, "why": clean(a.why, "--why")})
    print(f"{a.hypo} {a.verdict} {a.fact}" + ("; discarded" if a.verdict == "contradicts" else ""))


def cmd_tactic(a, root):
    path, _ = load(root, a.case)
    append(path, {"type": "tactic", "tactic": a.tactic, "note": clean(a.note, "--note")})
    print(f"logged {a.tactic}; rebuild the matrix (`matrix`)")


def cmd_gap(a, root):
    path, _ = load(root, a.case)
    append(path, {"type": "gap", "text": clean(a.text, "gap"), "layer": a.layer})
    print("gap recorded; it goes in the report as infrastructure work")


def cmd_review(a, root):
    path, _ = load(root, a.case)
    append(path, {"type": "review", "gate": a.gate, "verdict": a.verdict, "by": clean(a.by, "--by"),
                  "note": (a.note or "").strip()[:MAX_TEXT]})
    print(f"{a.gate} review: {a.verdict}")


def cell_mark(case: Case, h: str, f: str) -> str:
    v = case.cells.get((h, f))
    return {"explains": "E", "contradicts": "X", "neutral": "-"}[v[0]] if v else "?"


def cmd_matrix(a, root):
    _, case = load(root, a.case)
    state = assess(case)
    cols = case.columns()
    strength = {s["fact"]: s["strength"] for s in state["signals"]}
    rows = [["fact", "seen", "layer"] + [h.id for h in cols] + ["strength"]]
    for f in case.active_facts():
        rows.append([f.id, f.seen, str(f.layer)] + [cell_mark(case, h.id, f.id) for h in cols]
                    + [strength.get(f.id, "noise")])
    status = []
    for h in cols:
        if h.id in state["discarded"]:
            status.append(f"out:{state['discarded'][h.id]}")
        elif h.id in state["satisfied"]:
            status.append("fits all")
        else:
            status.append("live")
    rows.append(["", "", ""] + status + [""])
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    for r in rows:
        print("  ".join(c.ljust(w) for c, w in zip(r, widths)).rstrip())
    print("\nE explains  X contradicts  - neutral  ? unmarked")
    for h in cols:
        print(f"{h.id}: {h.text}")


def cmd_next(a, root):
    _, case = load(root, a.case)
    state = assess(case)
    if a.json:
        print(json.dumps(state, indent=2))
        return
    print(f"case {case.name}: step {state['step']}")
    print(f"do: {state['do']}")
    if state["strongest"]:
        s = state["strongest"]
        print(f"steer: {s['fact']} is the strongest signal; it points to {', '.join(s['points_to'])}")
    for r in state["reminders"]:
        print(f"remind: {r}")


def md(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def cmd_report(a, root):
    _, case = load(root, a.case)
    state = assess(case)
    if state["step"] != "root-cause" and not a.draft:
        raise Refused(f"no root cause yet (step {state['step']}). {state['do']}")
    rc = state.get("root_cause")
    lines = [f"# Root cause: {case.name}", ""]
    if state["step"] != "root-cause":
        lines += [f"**DRAFT.** Step {state['step']}: {state['do']}", ""]
    lines += [f"**Symptom.** {case.symptom}", "", f"**Control.** {case.control}", ""]
    if rc:
        lines += [f"**Root cause ({rc}).** {case.hypos[rc].text}", ""]
    lines += ["## Evidence", "", "| Fact | Seen | Layer | Source | Cite | " + (f"{rc} | Why |" if rc else ""),
              "| --- | --- | --- | --- | --- | " + ("--- | --- |" if rc else "")]
    for f in case.active_facts():
        row = f"| {f.id}: {md(f.text)} | {f.seen} | {f.layer} | {f.source} | {md(f.cite)} |"
        if rc:
            v = case.cells[(rc, f.id)]
            row += f" {v[0]} | {md(v[1])} |"
        lines.append(row)
    out_rows = [(h, state["discarded"][h.id]) for h in case.columns() if h.id in state["discarded"]]
    if out_rows or state["retired"]:
        lines += ["", "## Ruled out", "", "| Hypothesis | Ruled out by | Why |", "| --- | --- | --- |"]
        for h, fid in out_rows:
            lines.append(f"| {h.id}: {md(h.text)} | {fid} | {md(case.cells[(h.id, fid)][1])} |")
        for hid, why in state["retired"].items():
            lines.append(f"| {hid}: {md(case.hypos[hid].text)} | {why} | |")
    retracted = [f for f in case.facts.values() if f.retracted]
    if retracted:
        lines += ["", "## Retracted facts", ""] + [f"- {f.id}: {f.text} ({f.retracted})" for f in retracted]
    if case.tactics:
        lines += ["", "## Tactics tried", ""] + [f"- {t}: {note}" for t, _, note in case.tactics]
    if case.gaps:
        lines += ["", "## Infrastructure gaps", "",
                  "Layers the agent needed and couldn't reach. Each is infrastructure work, not a skill issue.", ""]
        lines += [f"- layer {g['layer']}: {g['text']}" for g in case.gaps]
    if case.reviews:
        lines += ["", "## Reviews", ""] + [f"- {r['gate']}: {r['verdict']} by {r['by']}"
                                          + (f" ({r['note']})" if r["note"] else "") for r in case.reviews]
    checks = [f for f in case.active_facts() if f.check]
    if checks:
        lines += ["", "## Regression checks", "", "`rootcause.py recheck` runs these; a bug-only signal "
                  "that still holds fails it.", ""] + [f"- {f.id} ({f.seen}): `{f.check}`" for f in checks]
    text = "\n".join(lines) + "\n"
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
        print(f"wrote {a.out}")
    else:
        sys.stdout.write(text)


def cmd_recheck(a, root):
    _, case = load(root, a.case)
    checks = [f for f in case.active_facts() if f.check]
    if not checks:
        raise Refused("no fact in this case has a --check")
    failed = []
    for f in checks:
        if a.dry_run:
            print(f"{f.id}: {f.check}")
            continue
        try:
            r = subprocess.run(["bash", "-c", f.check], capture_output=True, text=True, timeout=a.timeout)
            holds, note = r.returncode == 0, f"exit {r.returncode}"
        except subprocess.TimeoutExpired:
            holds, note = None, f"timed out after {a.timeout}s"
        word = "error" if holds is None else ("holds" if holds else "gone")
        print(f"{f.id} {f.seen:<8} {word:<5} {note}  {f.check}")
        if holds is None:
            failed.append(f"{f.id} could not be checked")
        elif a.expect == "gone" and f.seen == "variable" and holds:
            failed.append(f"{f.id} (a bug-only signal) still holds")
        elif a.expect == "present" and f.signal and not holds:
            failed.append(f"{f.id} no longer reproduces")
    if failed:
        raise Refused("; ".join(failed))
    if not a.dry_run:
        print("recheck passed" + (": the bug's signals are gone" if a.expect == "gone" else ": the bug reproduces"))


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="rootcause.py", description=__doc__.split("\n\n")[0])
    p.add_argument("--dir", default=".rootcause", help="where case files live (default .rootcause)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("new", help="open a case")
    s.add_argument("case"); s.add_argument("--symptom", required=True); s.add_argument("--control", required=True)
    s.set_defaults(fn=cmd_new)

    s = sub.add_parser("fact", help="record a fact")
    s.add_argument("case"); s.add_argument("text")
    s.add_argument("--source", choices=SOURCES, required=True)
    s.add_argument("--cite", required=True, help="where you observed it: query, file:line, trace id, URL")
    s.add_argument("--seen", choices=SEEN, required=True,
                   help="variable/control: seen on only that side (a signal); both: noise kept as a constraint")
    s.add_argument("--layer", type=int, default=0, help="0 where the symptom shows; +1 per layer down")
    s.add_argument("--check", help="shell command that exits 0 while this fact holds")
    s.set_defaults(fn=cmd_fact)

    s = sub.add_parser("retract", help="withdraw a fact that was gathered wrong")
    s.add_argument("case"); s.add_argument("fact"); s.add_argument("--why", required=True)
    s.set_defaults(fn=cmd_retract)

    s = sub.add_parser("hypo", help="add a hypothesis")
    s.add_argument("case"); s.add_argument("text")
    s.add_argument("--tactic", choices=("new", "split", "merge", "combine"), default="new")
    s.add_argument("--from", dest="parents", help="parent hypotheses, comma-separated")
    s.set_defaults(fn=cmd_hypo)

    s = sub.add_parser("mark", help="fill one matrix cell")
    s.add_argument("case"); s.add_argument("hypo"); s.add_argument("fact"); s.add_argument("verdict", choices=CELLS)
    s.add_argument("--why", required=True, help="the evidence for this verdict")
    s.set_defaults(fn=cmd_mark)

    s = sub.add_parser("tactic", help="log a tactic tried")
    s.add_argument("case"); s.add_argument("tactic", choices=TACTICS[:4]); s.add_argument("--note", required=True)
    s.set_defaults(fn=cmd_tactic)

    s = sub.add_parser("gap", help="record a layer the agent could not reach")
    s.add_argument("case"); s.add_argument("text"); s.add_argument("--layer", type=int, default=0)
    s.set_defaults(fn=cmd_gap)

    s = sub.add_parser("review", help="record an adversarial review at a gate")
    s.add_argument("case"); s.add_argument("gate", choices=GATES)
    s.add_argument("--verdict", choices=("pass", "fail"), required=True)
    s.add_argument("--by", required=True, help="the reviewer's model or agent id")
    s.add_argument("--note", default="")
    s.set_defaults(fn=cmd_review)

    s = sub.add_parser("matrix", help="print the facts-by-hypotheses matrix")
    s.add_argument("case"); s.set_defaults(fn=cmd_matrix)

    s = sub.add_parser("next", help="say the step and the one thing to do next")
    s.add_argument("case"); s.add_argument("--json", action="store_true"); s.set_defaults(fn=cmd_next)

    s = sub.add_parser("report", help="write the root-cause report (Markdown)")
    s.add_argument("case"); s.add_argument("--out"); s.add_argument("--draft", action="store_true")
    s.set_defaults(fn=cmd_report)

    s = sub.add_parser("recheck", help="run every fact's --check (a regression or deploy gate)")
    s.add_argument("case"); s.add_argument("--expect", choices=("gone", "present"), default="gone")
    s.add_argument("--timeout", type=int, default=120); s.add_argument("--dry-run", action="store_true")
    s.set_defaults(fn=cmd_recheck)
    return p


def main(argv: list[str] | None = None) -> int:
    a = parser().parse_args(argv)
    try:
        a.fn(a, Path(a.dir))
    except Refused as e:
        print(f"refused: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
