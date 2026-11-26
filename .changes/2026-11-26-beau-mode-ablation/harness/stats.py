import json, sys
from pathlib import Path
R = Path(__file__).resolve().parent / "runs"
for f in sorted(R.glob("*.jsonl")):
    reads, res = [], {}
    for line in f.read_text().splitlines():
        try: ev = json.loads(line)
        except ValueError: continue
        if ev.get("type") == "assistant":
            for c in ev["message"]["content"]:
                if c.get("type") == "tool_use":
                    p = json.dumps(c["input"])
                    if "/kit/skills/" in p or "SKILL.md" in p:
                        for part in p.split('"'):
                            if "/kit/skills/" in part or "SKILL.md" in part: reads.append(part.split("/kit/skills/")[-1][:60])
        if ev.get("type") == "result": res = ev
    u = res.get("usage", {})
    print(f.stem, res.get("subtype"), "cost=%.2f" % (res.get("total_cost_usd") or 0), "turns=", res.get("num_turns"),
          "s=%d" % ((res.get("duration_ms") or 0)/1000), "diff=%d" % len((R / (f.stem + ".diff")).read_text()) if (R / (f.stem + ".diff")).exists() else "", sorted(set(reads)))
