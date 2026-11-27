import json, pathlib, re, sys
spec = pathlib.Path("docs/phases/P1-add.md").read_text()
if not re.search(r"- \[[xX]\] \*\*C1\.\*\*", spec):
    sys.exit(0)
led = pathlib.Path(".audit/runs/2026-11-26-p1-add/ledger.jsonl")
entries = [json.loads(l) for l in led.read_text().splitlines() if l.strip()] if led.exists() else []
ok = any(e.get("type") == "verification" and (e.get("data") or {}).get("receipt", {}).get("criterion") in ("C1", "P1-C1")
         and e["data"].get("verdict") == "VERIFIED" for e in entries)
sys.exit(0 if ok else 1)
