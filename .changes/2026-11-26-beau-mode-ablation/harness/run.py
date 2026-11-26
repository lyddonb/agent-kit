import json, os, random, subprocess, sys, shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

META = Path(__file__).resolve().parent
SP = META.parent
WORK = SP / "work"
KIT = WORK / "kit"
SRC = {"agent-kit": "<agent-runtime>/agent-kit",
       "agent-ledger": "<agent-runtime>/agent-ledger"}
ARMS = ["full1", "full2", "slim"]
SEED = 4343
RUNS = META / "runs"
CAP = os.environ.get("CAP_USD", "2.00")
SETTINGS = json.dumps({"sandbox": {"enabled": True, "autoAllowBashIfSandboxed": True,
                                   "allowUnsandboxedCommands": False,
                                   "filesystem": {"allowWrite": ["/private/var/folders"]}},
                       "permissions": {"allow": ["Edit(//private/var/folders/**)"]}})


def tasks():
    return json.loads((META / "tasks.json").read_text())


def mapping():
    path = META / "mapping.json"
    if path.exists():
        return json.loads(path.read_text())
    rng = random.Random(SEED)
    out = {}
    for t in tasks():
        letters = ["p", "q", "r"]
        rng.shuffle(letters)
        out[t["id"]] = dict(zip(ARMS, letters))
    path.write_text(json.dumps(out, indent=1))
    return out


def git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def setup(t, letter):
    d = WORK / f"{t['id']}-{letter}"
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    base = subprocess.run(["git", "rev-parse", t["merge"] + "^1"], cwd=SRC[t["repo"]],
                          check=True, capture_output=True, text=True).stdout.strip()
    git("init", "-q", "-b", "main", ".", cwd=d)
    git("fetch", "-q", "--no-tags", "--depth", "400", "file://" + SRC[t["repo"]], base, cwd=d)
    git("reset", "-q", "--hard", "FETCH_HEAD", cwd=d)
    (d / ".git" / "FETCH_HEAD").unlink(missing_ok=True)
    shallow = d / ".git" / "shallow"
    return d, base


def run(t, arm, letter):
    d, base = setup(t, letter)
    name = f"{t['id']}-{arm}"
    out = RUNS / f"{name}.jsonl"
    cmd = ["claude", "-p", t["prompt"], "--model", "sonnet",
           "--append-system-prompt-file", str(META / f"arm-{arm.rstrip('12')}.md"),
           "--setting-sources", "", "--strict-mcp-config", "--disable-slash-commands",
           "--permission-mode", "acceptEdits", "--settings", SETTINGS,
           "--add-dir", str(KIT),
           "--disallowedTools", "WebFetch", "WebSearch", "Bash(gh:*)", "Bash(git push:*)",
           "--max-budget-usd", CAP, "--output-format", "stream-json", "--verbose"]
    with open(out, "w") as fh:
        p = subprocess.run(cmd, cwd=d, stdout=fh, stderr=subprocess.PIPE, text=True, timeout=3600)
    diff = subprocess.run(["git", "diff", base], cwd=d, capture_output=True, text=True).stdout
    subprocess.run(["git", "add", "-A"], cwd=d)
    diff = subprocess.run(["git", "diff", "--cached", base], cwd=d, capture_output=True, text=True).stdout
    (RUNS / f"{name}.diff").write_text(diff)
    (RUNS / f"{name}.meta.json").write_text(json.dumps({"rc": p.returncode, "stderr": p.stderr[-2000:],
                                                        "dir": str(d), "base": base}))
    return name, p.returncode


def main():
    RUNS.mkdir(exist_ok=True)
    want = sys.argv[1].split(",") if len(sys.argv) > 1 else [t["id"] for t in tasks()]
    m = mapping()
    jobs = [(t, a, m[t["id"]][a]) for t in tasks() if t["id"] in want for a in ARMS]
    jobs = [j for j in jobs if not (RUNS / f"{j[0]['id']}-{j[1]}.diff").exists()]
    with ThreadPoolExecutor(max_workers=4) as ex:
        for name, rc in ex.map(lambda j: run(*j), jobs):
            print(name, rc, flush=True)


if __name__ == "__main__":
    main()
