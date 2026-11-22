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
import datetime, json, os, re, sys
args = sys.argv[1:]
path = os.environ["STUB_STATE"]
st = json.load(open(path))
assert args[0] == "api", args
url = args[1].split("?")[0]
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
json.dump(st, open(path, "w"))
if out is not None:
    print(json.dumps(out))
'''


def sh(*args, cwd=None):
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


class LocalCITest(unittest.TestCase):
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

    def test_run_force_reruns_a_finished_sha(self):
        sha = self.add_pr(9, "echo ok")
        self.run_ci("tick")
        p = self.run_ci("run", "--pr", "9")
        self.assertIn("already has", p.stdout)
        self.run_ci("run", "--pr", "9", "--force")
        self.assertEqual(len(self.final(sha)), 2)

    def test_checkout_working_tree_is_untouched(self):
        (self.checkout / "scratch.txt").write_text("mine")
        self.add_pr(10, "echo ok")
        self.run_ci("tick")
        self.assertEqual(sh("git", "-C", str(self.checkout), "status", "--porcelain"), "?? scratch.txt")
        self.assertEqual(sh("git", "-C", str(self.checkout), "worktree", "list").count("\n"), 0,
                         "the throwaway worktree is removed")


if __name__ == "__main__":
    unittest.main()
