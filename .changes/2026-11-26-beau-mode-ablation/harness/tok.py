import json, subprocess, sys
from pathlib import Path
M = Path(__file__).resolve().parent
d = M / "tok"; d.mkdir(exist_ok=True)
for arm in ["none", "full", "slim"]:
    extra = [] if arm == "none" else ["--append-system-prompt-file", str(M / f"arm-{arm}.md")]
    p = subprocess.run(["claude", "-p", "Reply with the single word ok.", "--model", "sonnet", "--setting-sources", "",
                        "--strict-mcp-config", "--disable-slash-commands", "--tools", "", *extra, "--output-format", "json"],
                       cwd=d, capture_output=True, text=True)
    j = json.loads(p.stdout); u = j["usage"]
    tot = u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0) + u.get("cache_read_input_tokens", 0)
    print(arm, tot, j.get("total_cost_usd"))
