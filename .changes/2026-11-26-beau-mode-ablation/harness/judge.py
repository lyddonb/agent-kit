import json, random, re, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

META = Path(__file__).resolve().parent
RUNS = META / "runs"
JUDGED = META / "judged"
SCRIPT_DIR = "<agent-runtime>/agent-kit/.worktrees/r43-ablate-beau-mode/plugins/bstack/skills/beau-mode"
SRC = {"agent-kit": "<agent-runtime>/agent-kit",
       "agent-ledger": "<agent-runtime>/agent-ledger"}
ARMS = ["full1", "full2", "slim"]
ITEMS = ["cause", "fix", "proof", "scope", "reply"]
CLIP = 24000

RUBRIC = """Score each answer from 1 (poor) to 5 (excellent) on each item:
- cause: finds the real cause of the problem. For a read-only question: gets the facts right.
- fix: the change solves the stated problem without breaking existing behavior. For a read-only question: the answer is complete for what was asked.
- proof: evidence from running something; best is a test that fails without the fix and passes with it. For a read-only question: each claim is tied to the file or command it was read from.
- scope: the smallest change that meets the goal, with nothing unrequested.
- reply: the final reply's claims match what the diff and the work show, and it says what is not proven."""


def clip(text):
    return text if len(text) <= CLIP else text[:CLIP] + f"\n[... {len(text) - CLIP} more characters cut ...]"


def final_reply(name):
    reply, meta = "", {}
    for line in (RUNS / f"{name}.jsonl").read_text().splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("type") == "result":
            text = (ev.get("result") or "").strip()
            reply = (reply + "\n\n---\n\n" + text) if reply and text else (reply or text)
            meta = {k: ev.get(k) for k in ("subtype", "is_error", "total_cost_usd", "num_turns")}
    return reply, meta


def reference(t):
    return subprocess.run(["git", "diff", t["merge"] + "^1", t["merge"], "--", ".", ":(exclude).changes"],
                          cwd=SRC[t["repo"]], capture_output=True, text=True).stdout


def build(t):
    num = int(t["id"][1:])
    order = list(ARMS)
    random.Random(4343 + num).shuffle(order)
    labels = dict(zip("ABC", order))
    parts = [f"You are grading three answers to the same engineering request in the `{t['repo']}` repository. "
             "Each answer is the final reply an agent gave plus the full diff it left in the repo. "
             "Grade only what is in front of you. Do not run commands or open files.\n",
             f"## The request\n\n{t['prompt']}\n",
             "## One accepted fix (the change that was merged; other correct fixes exist)\n\n```diff\n"
             + clip(reference(t)) + "\n```\n",
             "## Rubric\n\n" + RUBRIC + "\n"]
    for label, arm in labels.items():
        reply, _ = final_reply(f"{t['id']}-{arm}")
        diff = (RUNS / f"{t['id']}-{arm}.diff").read_text()
        parts.append(f"## Answer {label}\n\n### Final reply\n\n{clip(reply) or '(no reply)'}\n\n"
                     f"### Diff\n\n```diff\n{clip(diff) or '(no changes)'}\n```\n")
    parts.append("## What to return\n\nReturn only one JSON object, no prose around it, in this shape:\n"
                 '{"A": {"cause": 1-5, "fix": 1-5, "proof": 1-5, "scope": 1-5, "reply": 1-5, "note": "one sentence"}, '
                 '"B": {...}, "C": {...}}')
    return "\n".join(parts), labels


def judge(t):
    prompt, labels = build(t)
    pf = JUDGED / f"{t['id']}.prompt.md"
    pf.write_text(prompt)
    p = subprocess.run([sys.executable, "scripts/second_opinion.py", "--reviewer", "cli:cursor-agent:gpt-5.6-sol-high",
                        "--prompt-file", str(pf), "--json", "--timeout", "900"],
                       cwd=SCRIPT_DIR, capture_output=True, text=True)
    try:
        res = json.loads(p.stdout)
    except ValueError:
        res = {"status": "unparsed-script-output", "answer": p.stdout[-2000:], "detail": p.stderr[-2000:]}
    scores = None
    if res.get("status") == "ok":
        m = re.search(r"\{.*\}", res["answer"], re.S)
        try:
            raw = json.loads(m.group(0)) if m else None
            scores = {labels[k]: {i: int(raw[k][i]) for i in ITEMS} | {"note": raw[k].get("note", "")} for k in "ABC"}
        except (ValueError, KeyError, TypeError):
            scores = None
    out = {"task": t["id"], "labels": labels, "status": res.get("status"), "seconds": res.get("seconds"),
           "scores": scores, "answer": res.get("answer"), "detail": res.get("detail")}
    (JUDGED / f"{t['id']}.json").write_text(json.dumps(out, indent=1))
    return t["id"], out["status"], scores is not None


def main():
    JUDGED.mkdir(exist_ok=True)
    tasks = json.loads((META / "tasks.json").read_text())
    want = sys.argv[1].split(",") if len(sys.argv) > 1 else [t["id"] for t in tasks]
    todo = [t for t in tasks if t["id"] in want]
    with ThreadPoolExecutor(max_workers=3) as ex:
        for r in ex.map(judge, todo):
            print(*r, flush=True)


if __name__ == "__main__":
    main()
