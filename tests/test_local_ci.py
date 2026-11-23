"""End-to-end tests for local_ci.py against a local bare repo and a stub `gh` that keeps GitHub's state in a JSON file."""
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "plugins/bstack/skills/local-ci/scripts/local_ci.py"
REPO = "owner/app"

# GET answers from the state file; POST/PATCH with --input - change it. Unknown calls fail loudly.
STUB_GH = r'''#!/usr/bin/env python3
import datetime, fcntl, json, os, re, sys
args = sys.argv[1:]
path = os.environ["STUB_STATE"]
lock = open(path + ".lock", "w")
fcntl.flock(lock, fcntl.LOCK_EX)
st = json.load(open(path))
assert args[0] == "api", args
url, _, query = args[1].partition("?")
q = dict(kv.split("=", 1) for kv in query.split("&") if "=" in kv)
method = args[args.index("-X") + 1] if "-X" in args else "GET"
body = json.load(sys.stdin) if "--input" in args else None
st.setdefault("calls", []).append([method, url, body])
out = None
R = "repos/owner/app"
if method == "GET" and url == R:
    out = {"default_branch": "main"}
elif method == "GET" and url.startswith(R + "/commits/") and url.endswith("/statuses"):
    sha = url.split("/")[-2]
    out = list(reversed(st["statuses"].get(sha, [])))
elif method == "GET" and url.startswith(R + "/commits/"):
    out = {"sha": st["branches"][url.split("/")[-1]]}
elif method == "GET" and url == R + "/pulls":
    out = [[p for p in st["pulls"]]]
elif method == "GET" and re.fullmatch(R + r"/pulls/\d+", url):
    out = next(p for p in st["pulls"] if p["number"] == int(url.split("/")[-1]))
elif method == "GET" and url == R + "/actions/runs":
    out = {"workflow_runs": st.get("runs", {}).get(q["head_sha"], [])}
elif method == "GET" and re.fullmatch(R + r"/actions/runs/\d+/jobs", url):
    out = {"jobs": st["jobs"][url.split("/")[-2]]}
elif method == "POST" and url.startswith(R + "/statuses/"):
    body["updated_at"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    st["statuses"].setdefault(url.split("/")[-1], []).append(body)
elif method == "GET" and re.fullmatch(R + r"/issues/\d+/comments", url):
    out = [[c for c in st["comments"] if c["pr"] == int(url.split("/")[-2])]]
elif method == "POST" and re.fullmatch(R + r"/issues/\d+/comments", url):
    st["comments"].append({"id": len(st["comments"]) + 1, "pr": int(url.split("/")[-2]), "body": body["body"]})
elif method == "PATCH" and url.startswith(R + "/issues/comments/"):
    c = next(c for c in st["comments"] if c["id"] == int(url.split("/")[-1]))
    c["body"] = body["body"]
else:
    sys.exit(f"stub gh: unexpected call {args}")
with open(path + ".tmp", "w") as f:
    json.dump(st, f)
os.replace(path + ".tmp", path)
if out is not None:
    print(json.dumps(out))
'''


def sh(*args, cwd=None):
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


class StubStateTest(unittest.TestCase):
    def test_concurrent_stub_calls_lose_no_update_and_a_reader_never_sees_a_torn_file(self):
        tmp = Path(tempfile.mkdtemp())
        gh = tmp / "gh"
        gh.write_text(STUB_GH)
        gh.chmod(0o755)
        state = tmp / "state.json"
        state.write_text(json.dumps({"statuses": {}}))
        env = dict(os.environ, STUB_STATE=str(state))
        workers, calls = 8, 15
        script = f"for i in $(seq {calls}); do {gh} api repos/owner/app >/dev/null || exit 1; done"
        procs = [subprocess.Popen(["sh", "-c", script], env=env) for _ in range(workers)]
        torn = 0
        while any(p.poll() is None for p in procs):
            try:
                json.loads(state.read_text())
            except ValueError:
                torn += 1
        self.assertEqual([p.returncode for p in procs], [0] * workers)
        self.assertEqual(torn, 0, "a reader saw a half-written state file")
        self.assertEqual(len(json.loads(state.read_text())["calls"]), workers * calls, "a stub call's update was lost")


class Harness(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.origin = self.tmp / "origin.git"
        self.checkout = self.tmp / "checkout"
        self.dev = self.tmp / "dev"
        sh("git", "init", "-q", "--bare", "-b", "main", str(self.origin))
        sh("git", "clone", "-q", str(self.origin), str(self.dev))
        for k, v in (("user.email", "t@example.invalid"), ("user.name", "t")):
            sh("git", "-C", str(self.dev), "config", k, v)
        self.main_sha = self.commit("echo main ok", "main")
        sh("git", "clone", "-q", str(self.origin), str(self.checkout))
        gh = self.tmp / "gh"
        gh.write_text(STUB_GH)
        gh.chmod(0o755)
        self.state = self.tmp / "state.json"
        self.write_state({"branches": {"main": self.main_sha}, "pulls": [], "statuses": {},
                          "comments": []})
        self.env = dict(os.environ, LOCAL_CI_GH=str(gh), STUB_STATE=str(self.state),
                        LOCAL_CI_STATE=str(self.tmp / "ci-state"), LOCAL_CI_HOST="testhost")

    def commit(self, ci_body, branch, ref=None):
        """Commit a scripts/ci whose body is ci_body on `branch` and push it (to `ref` if given)."""
        d = str(self.dev)
        if branch != "main":
            sh("git", "-C", d, "checkout", "-q", "-B", branch, "origin/main" if self.has_main() else "HEAD")
        ci = self.dev / "scripts" / "ci"
        ci.parent.mkdir(exist_ok=True)
        if ci_body is None:
            ci.unlink(missing_ok=True)
            (self.dev / "README").write_text(branch)
        else:
            ci.write_text("#!/bin/sh\n" + textwrap.dedent(ci_body) + "\n")
            ci.chmod(0o755)
        sh("git", "-C", d, "add", "-A")
        sh("git", "-C", d, "commit", "-q", "-m", branch)
        sha = sh("git", "-C", d, "rev-parse", "HEAD")
        sh("git", "-C", d, "push", "-q", "-f", "origin", f"HEAD:{ref or 'refs/heads/' + branch}")
        sh("git", "-C", d, "fetch", "-q", "origin")
        return sha

    def has_main(self):
        return subprocess.run(["git", "-C", str(self.dev), "rev-parse", "-q", "--verify", "origin/main"],
                              capture_output=True).returncode == 0

    def add_pr(self, number, ci_body):
        sha = self.commit(ci_body, f"pr{number}", ref=f"refs/pull/{number}/head")
        st = self.read_state()
        st["pulls"].append({"number": number, "head": {"sha": sha, "repo": {"full_name": REPO}},
                            "base": {"ref": "main"}})
        self.write_state(st)
        return sha

    def read_state(self):
        return json.loads(self.state.read_text())

    def write_state(self, st):
        self.state.write_text(json.dumps(st))

    def run_ci(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *args, "--repo", f"{REPO}={self.checkout}"],
                              env=self.env, capture_output=True, text=True)

    def final(self, sha):
        return [s for s in self.read_state()["statuses"].get(sha, []) if s["state"] != "pending"]


class LocalCITest(Harness):
    def test_passing_pr_gets_success_and_no_comment(self):
        sha = self.add_pr(1, 'test "$LOCAL_CI_BASE" = origin/main && git rev-parse origin/main >/dev/null && echo fine')
        p = self.run_ci("tick")
        self.assertEqual(p.returncode, 0, p.stderr)
        statuses = self.read_state()["statuses"][sha]
        self.assertEqual([s["state"] for s in statuses], ["pending", "success"], statuses)
        self.assertEqual(statuses[-1]["context"], "local-ci")
        self.assertIn("passed in", statuses[-1]["description"])
        self.assertEqual(self.read_state()["comments"], [], "a passing PR with no earlier failure gets no comment")
        self.assertEqual([s["state"] for s in self.final(self.main_sha)], ["success"], "the default branch head runs too")

    def test_failing_pr_gets_failure_and_one_comment_then_edited_on_pass(self):
        sha = self.add_pr(2, "echo step one\necho the real error >&2\nexit 3")
        self.run_ci("tick")
        self.assertEqual(self.final(sha)[-1]["state"], "failure")
        self.assertIn("the real error", self.final(sha)[-1]["description"])
        comments = self.read_state()["comments"]
        self.assertEqual(len(comments), 1)
        self.assertIn("the real error", comments[0]["body"])
        self.assertIn("<!-- local-ci -->", comments[0]["body"])

        fixed = self.add_pr(2, "echo fixed")
        st = self.read_state()
        st["pulls"] = [p for p in st["pulls"] if p["head"]["sha"] == fixed]
        self.write_state(st)
        self.run_ci("tick")
        self.assertEqual(self.final(fixed)[-1]["state"], "success")
        comments = self.read_state()["comments"]
        self.assertEqual(len(comments), 1, "the existing comment is edited, not a new one added")
        self.assertIn("passed", comments[0]["body"])

    def test_tick_output_names_each_job(self):
        self.add_pr(12, "echo ok")
        p = self.run_ci("tick")
        self.assertIn(f"{REPO}:main@{self.main_sha[:7]}: success", p.stdout)
        self.assertIn(f"{REPO}#12@", p.stdout)

    def test_finished_sha_is_not_rerun(self):
        sha = self.add_pr(3, "echo ok")
        self.run_ci("tick")
        self.run_ci("tick")
        self.assertEqual(len(self.read_state()["statuses"][sha]), 2, "the second tick posts nothing")

    def test_old_finished_status_is_not_rerun(self):
        sha = self.add_pr(11, "echo ok")
        st = self.read_state()
        st["statuses"][sha] = [{"state": "failure", "context": "local-ci", "updated_at": "2000-01-01T00:00:00Z"}]
        self.write_state(st)
        self.run_ci("tick")
        self.assertEqual(len(self.read_state()["statuses"][sha]), 1, "only a pending can go stale")

    def test_stale_pending_is_rerun_and_fresh_pending_is_not(self):
        sha = self.add_pr(4, "echo ok")
        st = self.read_state()
        st["statuses"][sha] = [{"state": "pending", "context": "local-ci", "updated_at": "2000-01-01T00:00:00Z"}]
        st["statuses"][self.main_sha] = [{"state": "pending", "context": "local-ci", "updated_at": "2099-01-01T00:00:00Z"}]
        self.write_state(st)
        self.run_ci("tick")
        self.assertEqual(self.final(sha)[-1]["state"], "success", "a pending left by a dead run is rerun")
        self.assertEqual(self.final(self.main_sha), [], "a pending from a run still in progress is left alone")

    def test_missing_scripts_ci_is_error(self):
        sha = self.add_pr(5, None)
        self.run_ci("tick")
        self.assertEqual(self.final(sha)[-1]["state"], "error")
        self.assertIn("scripts/ci", self.final(sha)[-1]["description"])

    def test_timeout_is_failure(self):
        sha = self.add_pr(6, "sleep 30")
        p = self.run_ci("run", "--pr", "6", "--timeout", "1")
        self.assertEqual(p.returncode, 1)
        self.assertEqual(self.final(sha)[-1]["state"], "failure")
        self.assertIn("timed out", self.final(sha)[-1]["description"])

    def test_moved_head_posts_nothing_for_the_old_sha(self):
        old = self.add_pr(7, "echo ok")
        self.commit("echo newer", "pr7", ref="refs/pull/7/head")
        self.run_ci("tick")
        self.assertNotIn(old, self.read_state()["statuses"], "a sha that is no longer the head gets no status")

    def test_fork_pr_never_runs(self):
        sha = self.add_pr(8, "echo ok")
        st = self.read_state()
        st["pulls"][0]["head"]["repo"] = {"full_name": "someone/app"}
        self.write_state(st)
        self.run_ci("tick")
        self.assertNotIn(sha, self.read_state()["statuses"])

    def test_run_exit_code_follows_an_existing_verdict(self):
        sha = self.add_pr(13, "exit 1")
        self.run_ci("tick")
        p = self.run_ci("run", "--pr", "13")
        self.assertEqual(p.returncode, 1, "an existing failure is not reported as success")
        self.assertIn("failure (existing", p.stdout)
        self.assertEqual(len(self.final(sha)), 1, "nothing reruns without --force")

    def test_run_reruns_a_fresh_pending_once_it_holds_the_lock(self):
        sha = self.add_pr(14, "echo ok")
        st = self.read_state()
        st["statuses"][sha] = [{"state": "pending", "context": "local-ci", "updated_at": "2099-01-01T00:00:00Z"}]
        self.write_state(st)
        p = self.run_ci("run", "--pr", "14")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(self.final(sha)[-1]["state"], "success")

    def test_run_waits_for_a_tick_holding_the_lock(self):
        sha = self.add_pr(15, "sleep 2; exit 1")
        tick = subprocess.Popen([sys.executable, str(SCRIPT), "tick", "--repo", f"{REPO}={self.checkout}"],
                                env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        lock = self.tmp / "ci-state" / "lock"
        for _ in range(100):
            if self.read_state().get("statuses", {}).get(sha):
                break
            subprocess.run(["sleep", "0.1"])
        p = self.run_ci("run", "--pr", "15")
        tick.wait()
        self.assertTrue(lock.exists())
        self.assertEqual(p.returncode, 1, "run waited and reported the tick's failure, not 0 for 'skipping'")
        self.assertNotIn("skipping", p.stdout)

    def test_run_force_reruns_a_finished_sha(self):
        sha = self.add_pr(9, "echo ok")
        self.run_ci("tick")
        p = self.run_ci("run", "--pr", "9")
        self.assertIn("success (existing", p.stdout)
        self.run_ci("run", "--pr", "9", "--force")
        self.assertEqual(len(self.final(sha)), 2)

    def test_checkout_working_tree_is_untouched(self):
        (self.checkout / "scratch.txt").write_text("mine")
        self.add_pr(10, "echo ok")
        self.run_ci("tick")
        self.assertEqual(sh("git", "-C", str(self.checkout), "status", "--porcelain"), "?? scratch.txt")
        self.assertEqual(sh("git", "-C", str(self.checkout), "worktree", "list").count("\n"), 0,
                         "the throwaway worktree is removed")


REFUSED = {"status": "completed", "conclusion": "failure", "steps": [], "runner_name": None}
RAN_RED = {"status": "completed", "conclusion": "failure", "steps": [{"name": "x"}], "runner_name": "r1"}


class FallbackTest(Harness):
    """`fallback` runs scripts/fallback/<job> from the base branch for jobs GitHub never started."""

    def setUp(self):
        super().setUp()
        self.seen = self.tmp / "seen.txt"
        # The base branch's checker: records what it was given and passes.
        self.fallback_on_main("ledger-verify", f'echo "target=$(git -C "$LOCAL_CI_TARGET" rev-parse HEAD) '
                              f'event=$LOCAL_CI_EVENT dry=$LOCAL_CI_DRY_RUN" > {self.seen}')

    def fallback_on_main(self, job, body, explicit=False):
        d = str(self.dev)
        sh("git", "-C", d, "checkout", "-q", "-B", "main", "origin/main")
        f = self.dev / "scripts" / "fallback" / job
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("#!/bin/sh\n" + ("# local-ci: explicit\n" if explicit else "") + body + "\n")
        f.chmod(0o755)
        sh("git", "-C", d, "add", "-A")
        sh("git", "-C", d, "commit", "-q", "-m", f"fallback {job}")
        sh("git", "-C", d, "push", "-q", "origin", "HEAD:refs/heads/main")
        sh("git", "-C", d, "fetch", "-q", "origin")
        self.main_sha = sh("git", "-C", d, "rev-parse", "HEAD")
        st = self.read_state()
        st["branches"]["main"] = self.main_sha
        self.write_state(st)

    def pr_with_merge(self, number, pr_fallback_body=None):
        """A PR whose own copy of the ledger fallback fails, plus GitHub's merge commit for it."""
        d = str(self.dev)
        sh("git", "-C", d, "checkout", "-q", "-B", f"pr{number}", "origin/main")
        (self.dev / "change.txt").write_text(str(number))
        if pr_fallback_body is not None:
            (self.dev / "scripts/fallback/ledger-verify").write_text("#!/bin/sh\n" + pr_fallback_body + "\n")
        sh("git", "-C", d, "add", "-A")
        sh("git", "-C", d, "commit", "-q", "-m", f"pr {number}")
        head = sh("git", "-C", d, "rev-parse", "HEAD")
        sh("git", "-C", d, "push", "-q", "-f", "origin", f"HEAD:refs/pull/{number}/head")
        sh("git", "-C", d, "checkout", "-q", "--detach", "origin/main")
        sh("git", "-C", d, "merge", "-q", "--no-ff", "--no-edit", head)
        merge = sh("git", "-C", d, "rev-parse", "HEAD")
        sh("git", "-C", d, "push", "-q", "-f", "origin", f"HEAD:refs/pull/{number}/merge")
        st = self.read_state()
        st["pulls"].append({"number": number, "head": {"sha": head, "repo": {"full_name": REPO}},
                            "base": {"ref": "main"}})
        self.write_state(st)
        return head, merge

    def hosted(self, sha, **jobs):
        st = self.read_state()
        st.setdefault("runs", {})[sha] = [{"id": 900 + i, "name": n, "event": "pull_request_target",
                                           "created_at": f"2026-01-01T00:00:0{i}Z"} for i, n in enumerate(jobs)]
        st.setdefault("jobs", {}).update({str(900 + i): [dict(j, name=n)] for i, (n, j) in enumerate(jobs.items())})
        self.write_state(st)

    def fb(self, *args):
        return self.run_ci("fallback", *args)

    def test_refused_job_runs_the_base_branch_checker_on_the_merge_commit(self):
        head, merge = self.pr_with_merge(20, pr_fallback_body="exit 1")
        self.hosted(head, **{"ledger-verify": REFUSED})
        p = self.fb("--pr", "20")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn(f"target={merge} event=pull_request dry=0", self.seen.read_text(),
                      "the checker sees the merge commit, and the PR's failing copy of the script never ran")
        st = [s for s in self.read_state()["statuses"][head] if s["context"] == "ledger-verify (local fallback)"]
        self.assertEqual([s["state"] for s in st], ["pending", "success"])
        self.assertIn("GitHub didn't start it", st[-1]["description"])

    def test_job_that_ran_on_github_is_never_replaced(self):
        head, _ = self.pr_with_merge(21)
        self.hosted(head, **{"ledger-verify": RAN_RED})
        p = self.fb("--pr", "21")
        self.assertIn("ran on GitHub (failure); no fallback", p.stdout)
        self.assertNotIn(head, self.read_state()["statuses"])
        self.assertFalse(self.seen.exists())

    def test_explicit_fallback_runs_only_when_named(self):
        self.fallback_on_main("deploy", f"echo deployed > {self.tmp / 'deployed'}", explicit=True)
        self.hosted(self.main_sha, deploy=REFUSED)
        p = self.fb("--branch", "main")
        self.assertIn("runs only when named", p.stdout)
        self.assertFalse((self.tmp / "deployed").exists())
        p = self.fb("--branch", "main", "--job", "deploy")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertTrue((self.tmp / "deployed").exists())

    def test_no_fallback_script_fails_without_a_status(self):
        head, _ = self.pr_with_merge(22)
        self.hosted(head, **{"other-job": REFUSED})
        p = self.fb("--pr", "22")
        self.assertEqual(p.returncode, 1)
        self.assertIn("no scripts/fallback/other-job", p.stdout)
        self.assertNotIn(head, self.read_state()["statuses"])

    def test_stale_merge_commit_is_refused(self):
        head, _ = self.pr_with_merge(23)
        newer = self.commit("echo x", "pr23", ref="refs/pull/23/head")
        st = self.read_state()
        st["pulls"][-1]["head"]["sha"] = newer
        self.write_state(st)
        self.hosted(newer, **{"ledger-verify": REFUSED})
        p = self.fb("--pr", "23")
        self.assertEqual(p.returncode, 1)
        self.assertIn("merge commit still holds", p.stderr)
        self.assertFalse(self.seen.exists())

    def test_dry_run_posts_nothing(self):
        head, _ = self.pr_with_merge(24)
        self.hosted(head, **{"ledger-verify": REFUSED})
        p = self.fb("--pr", "24", "--dry-run")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("dry=1", self.seen.read_text())
        self.assertNotIn(head, self.read_state()["statuses"])

    def test_failing_checker_posts_failure(self):
        self.fallback_on_main("ledger-verify", "echo chain broken >&2; exit 2")
        head, _ = self.pr_with_merge(25)
        self.hosted(head, **{"ledger-verify": REFUSED})
        p = self.fb("--pr", "25")
        self.assertEqual(p.returncode, 1)
        st = self.read_state()["statuses"][head]
        self.assertEqual(st[-1]["state"], "failure")
        self.assertIn("chain broken", st[-1]["description"])


HEADER = '{"v":1,"repo":"app","tests":1}'
WRITES_RECORD = f"""test -f "$QUALITY_PY" || exit 9
printf '%s\\n{{"id":"t.a","ms":3,"outcome":"pass"}}\\n' '{HEADER}' > "$LOCAL_CI_RECORD"
echo tested"""


class RecordsTest(Harness):
    """A scripts/ci that writes $LOCAL_CI_RECORD has it published to refs/local-ci/records of origin."""

    def ref(self):
        p = subprocess.run(["git", "-C", str(self.origin), "rev-parse", "-q", "--verify", "refs/local-ci/records"],
                           capture_output=True, text=True)
        return p.stdout.strip() or None

    def files(self):
        out = sh("git", "-C", str(self.origin), "ls-tree", "-r", "--name-only", "refs/local-ci/records")
        return out.splitlines()

    def show(self, path):
        return sh("git", "-C", str(self.origin), "show", f"refs/local-ci/records:{path}")

    def pr(self, number, body):
        sha = self.add_pr(number, body)
        st = self.read_state()
        st["pulls"][-1]["head"]["ref"] = f"feat/{number}"
        self.write_state(st)
        return sha

    def test_a_record_is_published_with_a_manifest_local_ci_wrote(self):
        sha = self.pr(30, WRITES_RECORD)
        p = self.run_ci("tick")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn(f"{REPO}: published 1 test record to refs/local-ci/records", p.stdout)
        self.assertEqual([s["state"] for s in self.final(sha)], ["success"])
        files = self.files()
        self.assertEqual(len(files), 2, files)
        prefix = files[0].rsplit("/", 1)[0]
        self.assertRegex(prefix, rf"^runs/{sha}/\d{{4}}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        manifest = json.loads(self.show(f"{prefix}/manifest.json"))
        started = prefix.rsplit("/", 1)[1]
        self.assertEqual({k: v for k, v in manifest.items() if k != "completed"},
                         {"v": 1, "github": REPO, "sha": sha, "event": "pull_request", "pr": 30, "head_branch": "feat/30",
                          "base": "main", "started": started, "exit_code": 0, "host": "testhost"})
        self.assertGreaterEqual(manifest["completed"], started)
        self.assertEqual(self.show(f"{prefix}/test-results.jsonl").splitlines()[0], HEADER)
        log = sh("git", "-C", str(self.origin), "log", "--format=%an %s", "refs/local-ci/records")
        self.assertEqual(log, "local-ci local-ci: 1 test record from testhost")

    def test_each_run_adds_a_commit_on_top_and_a_failed_run_keeps_its_record(self):
        self.pr(31, WRITES_RECORD)
        self.run_ci("tick")
        first = self.ref()
        red = self.pr(32, WRITES_RECORD + "\nexit 4")
        self.run_ci("tick")
        self.assertEqual(sh("git", "-C", str(self.origin), "rev-parse", "refs/local-ci/records^"), first)
        self.assertEqual(len(self.files()), 4)
        prefix = next(f for f in self.files() if f.startswith(f"runs/{red}/")).rsplit("/", 1)[0]
        self.assertEqual(json.loads(self.show(f"{prefix}/manifest.json"))["exit_code"], 4)
        self.assertEqual(self.final(red)[-1]["state"], "failure")

    def test_the_default_branch_head_is_a_push(self):
        main = self.commit(WRITES_RECORD, "main")
        st = self.read_state()
        st["branches"]["main"] = main
        self.write_state(st)
        self.run_ci("run", "--branch", "main")
        manifest = json.loads(self.show(next(f for f in self.files() if f.endswith("manifest.json"))))
        self.assertEqual((manifest["event"], manifest["pr"], manifest["head_branch"]), ("push", None, "main"))

    def test_a_repo_that_records_nothing_gets_no_ref_and_no_output(self):
        self.pr(33, "echo plain")
        p = self.run_ci("tick")
        self.assertIsNone(self.ref())
        self.assertNotIn("record", p.stdout + p.stderr)

    def test_a_link_or_a_file_that_is_not_a_record_is_not_published(self):
        secret = self.tmp / "secret"
        secret.write_text('{"v":1,"key":"do not publish"}\n')
        self.pr(34, f'ln -s "{secret}" "$LOCAL_CI_RECORD"')
        self.pr(35, 'echo "not a record" > "$LOCAL_CI_RECORD"')
        self.pr(36, 'mkdir "$LOCAL_CI_RECORD"')
        self.pr(39, 'mkfifo "$LOCAL_CI_RECORD"')
        p = self.run_ci("tick")
        self.assertIsNone(self.ref())
        self.assertIn("cannot open the record", p.stderr)
        self.assertIn("first line is not JSON", p.stderr)
        self.assertIn("not a regular file", p.stderr)

    def test_a_failed_push_is_retried_next_tick_and_never_changes_the_status(self):
        sha = self.pr(37, WRITES_RECORD)
        sh("git", "-C", str(self.checkout), "remote", "set-url", "--push", "origin", str(self.tmp / "nowhere.git"))
        p = self.run_ci("tick")
        self.assertEqual(self.final(sha)[-1]["state"], "success")
        self.assertIn("test records not published, retried next tick", p.stderr)
        self.assertIsNone(self.ref())
        sh("git", "-C", str(self.checkout), "remote", "set-url", "--push", "origin", str(self.origin))
        p = self.run_ci("tick")
        self.assertIn("published 1 test record", p.stdout)
        self.assertEqual(len(self.files()), 2)

    def records(self):
        return self.tmp / "ci-state" / "records" / REPO.replace("/", "__")

    def plant(self, sha, started, manifest=None, record=None, link_to=None, fifo=False):
        d = self.records() / sha / started
        d.mkdir(parents=True)
        body = manifest if manifest is not None else {"v": 1, "github": REPO, "sha": sha, "started": started}
        (d / "manifest.json").write_text(json.dumps(body))
        target = d / "test-results.jsonl"
        if link_to:
            target.symlink_to(link_to)
        elif fifo:
            os.mkfifo(target)
        else:
            target.write_text(record or HEADER + "\n")
        return d

    def test_a_published_run_is_deleted_and_a_run_already_on_the_ref_is_not_pushed_twice(self):
        self.pr(38, WRITES_RECORD)
        self.run_ci("tick")
        tip = self.ref()
        self.assertEqual(list(self.records().rglob("*")), [], "published runs are deleted")
        prefix = self.files()[0].rsplit("/", 1)[0]
        _, sha, started = prefix.split("/")
        d = self.records() / sha / started
        d.mkdir(parents=True)
        for name in ("manifest.json", "test-results.jsonl"):
            (d / name).write_text(self.show(f"{prefix}/{name}") + "\n")
        p = self.run_ci("tick")
        self.assertEqual(self.ref(), tip, "a run the ref holds already is not pushed again")
        self.assertNotIn("published", p.stdout)
        self.assertFalse(d.exists())

    def test_a_planted_folder_is_never_published_and_never_blocks_a_good_run(self):
        secret = self.tmp / "secret"
        secret.write_text('{"v":1,"key":"do not publish"}\n')
        good = self.pr(40, WRITES_RECORD)
        self.plant("e" * 40, "2026-11-23T01:00:00Z", link_to=secret)
        self.plant("d" * 40, "2026-11-23T01:00:00Z", fifo=True)
        self.plant("c" * 40, "2026-11-23T01:00:00Z", manifest={"v": 1, "github": REPO, "sha": "f" * 40, "started": "x"})
        self.plant("not-a-sha", "2026-11-23T01:00:00Z")
        (self.records() / ("b" * 40) / "2026-11-23T01:00:00Z").mkdir(parents=True)
        p = subprocess.run([sys.executable, str(SCRIPT), "tick", "--repo", f"{REPO}={self.checkout}"],
                           env=self.env, capture_output=True, text=True, timeout=120)
        self.assertEqual(self.final(good)[-1]["state"], "success")
        files = self.files()
        self.assertEqual(sorted({f.split("/")[1] for f in files}), [good], files)
        self.assertNotIn("do not publish", sh("git", "-C", str(self.origin), "log", "-p", "refs/local-ci/records"))
        for why in ("cannot open the record", "not a regular file", "does not match its folder", "not a run folder", "no record"):
            self.assertIn(why, p.stderr)

    def test_a_broken_records_folder_never_changes_the_status(self):
        (self.tmp / "ci-state").mkdir(exist_ok=True)
        (self.tmp / "ci-state" / "scratch").write_text("a file where a folder goes")
        sha = self.pr(41, WRITES_RECORD.replace('test -f "$QUALITY_PY" || exit 9', 'test -z "${LOCAL_CI_RECORD:-}" || exit 9'))
        p = self.run_ci("tick")
        self.assertEqual(self.final(sha)[-1]["state"], "success", p.stderr)
        self.assertIn("no record this run", p.stderr)

    def test_the_push_skips_the_checkouts_hooks(self):
        hook = self.checkout / ".git" / "hooks" / "pre-push"
        hook.write_text(f"#!/bin/sh\ntouch {self.tmp / 'hook-ran'}\nexit 1\n")
        hook.chmod(0o755)
        self.pr(42, WRITES_RECORD)
        p = self.run_ci("tick")
        self.assertIn("published 1 test record", p.stdout, p.stderr)
        self.assertFalse((self.tmp / "hook-ran").exists())

    def test_nothing_scripts_ci_leaves_running_outlives_the_run(self):
        flag = self.tmp / "late"
        sha = self.pr(43, f'(sleep 3; touch "{flag}") &\necho done')
        self.run_ci("tick")
        self.assertEqual(self.final(sha)[-1]["state"], "success")
        import time
        time.sleep(5)
        self.assertFalse(flag.exists(), "the background process was killed with its group")


if __name__ == "__main__":
    unittest.main()
