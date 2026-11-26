import json, shutil, subprocess, sys
from pathlib import Path
META = Path(__file__).resolve().parent
WORK = META.parent / "work"; GT = META.parent / "gt"
SRC = {"agent-kit": "<agent-runtime>/agent-kit", "agent-ledger": "<agent-runtime>/agent-ledger"}
CASES = {
 "t3": ("tests/test_debrief.py", "tests.test_debrief", ["DebriefTests"], ["test_a_pattern_folder_link_or_submodule_is_not_a_record", "test_a_file_whose_name_is_a_glob_character_is_a_record", "test_a_record_that_links_outside_the_repo_is_not_read", "test_a_record_that_links_to_an_endless_device_does_not_hang", "test_a_record_git_holds_as_a_link_or_executable_is_rejected", "test_a_changes_folder_that_links_outside_the_repo_is_not_read"]),
 "t7": ("tests/test_session.py", "tests.test_session", [], ["test_many_redactions_under_a_password_or_key_name_still_archive"]),
 "t8": ("tests/test_scan.py", "tests.test_scan", [], ["test_a_stacked_pull_request_is_checked_against_the_main_commit_it_forked_from", "test_a_stack_that_rewrites_a_merged_main_line_still_fails", "test_a_first_parent_with_no_history_in_common_with_main_is_refused"]),
}
tasks = {t["id"]: t for t in json.loads((META / "tasks.json").read_text())}
mapping = json.loads((META / "mapping.json").read_text())
out = {}
for tid, (path, mod, _, names) in CASES.items():
    t = tasks[tid]
    merged = subprocess.run(["git", "show", f"{t['merge']}:{path}"], cwd=SRC[t["repo"]], capture_output=True, text=True, check=True).stdout
    for arm in ["base", "full1", "full2", "slim"]:
        letter = mapping[tid]["full1" if arm == "base" else arm]
        dst = GT / f"{tid}-{arm}"
        if dst.exists(): shutil.rmtree(dst)
        shutil.copytree(WORK / f"{tid}-{letter}", dst, symlinks=True)
        if arm == "base":
            subprocess.run(["git", "reset", "-q", "--hard", "HEAD"], cwd=dst); subprocess.run(["git", "clean", "-qfdx"], cwd=dst)
        (dst / path).write_text(merged)
        src = subprocess.run(["grep", "-n", "def " + names[0], path], cwd=dst, capture_output=True, text=True).stdout
        cls = subprocess.run(["python3", "-c", f"import ast,sys;t=ast.parse(open('{path}').read());print(' '.join(c.name+'.'+f.name for c in t.body if isinstance(c,ast.ClassDef) for f in c.body if isinstance(f,ast.FunctionDef) and f.name in {names!r}))"], cwd=dst, capture_output=True, text=True).stdout.split()
        ids = [f"{mod}.{c}" for c in cls]
        ks = [x for n in names for x in ("-k", n)]
        cmd = ["python3", "-m", "unittest", *ids] if t["repo"] == "agent-kit" else ["python3", "-m", "unittest", "discover", "-s", "tests", "-p", Path(path).name, *ks]
        p = subprocess.run(cmd, cwd=dst, capture_output=True, text=True, timeout=600)
        last = [l for l in p.stderr.splitlines() if l.startswith(("Ran ", "OK", "FAILED"))]
        out[f"{tid}-{arm}"] = {"rc": p.returncode, "summary": " ".join(last), "tests": len(ids)}
        print(tid, arm, p.returncode, " ".join(last), flush=True)
(META / "truth.json").write_text(json.dumps(out, indent=1))
