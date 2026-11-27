"""Tests for bstack's parallel-next in-flight check (plugins/bstack/skills/parallel-next/scripts/inflight.py)."""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "plugins/bstack/skills/parallel-next/scripts/inflight.py"

spec = importlib.util.spec_from_file_location("inflight", SCRIPT)
inflight = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = inflight
spec.loader.exec_module(inflight)

FAKE_GH = """#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
slug = args[args.index("--repo") + 1]
print(json.dumps(json.load(open(os.environ["INFLIGHT_FAKE_PULLS"])).get(slug, [])))
"""

NOW = datetime(2026, 11, 26, 12, 0, tzinfo=timezone.utc)


def git(path, *args):
    return subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True, text=True).stdout


def write(path, text="x\n"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


class Workspace:
    """A folder of repos, each with a bare origin so origin/main exists."""

    def __init__(self, root: Path):
        self.root = root

    def repo(self, name, commits=1, every=(), slug=None):
        path = self.root / name
        bare = self.root / ".origins" / f"{name}.git"
        bare.parent.mkdir(parents=True, exist_ok=True)
        git(self.root, "init", "-q", "--bare", "-b", "main", str(bare))
        git(self.root, "init", "-q", "-b", "main", str(path))
        git(path, "config", "user.email", "t@example.com")
        git(path, "config", "user.name", "t")
        write(path / "src/app.py")
        write(path / "docs/guide.md")
        for n in range(commits):
            for f in every:
                write(path / f, f"{n}\n")
            write(path / f"notes/{n}.md")
            git(path, "add", "-A")
            git(path, "commit", "-q", "-m", f"c{n}")
        git(path, "remote", "add", "origin", slug and f"https://github.com/{slug}.git" or str(bare))
        if slug:
            git(path, "remote", "set-url", "--push", "origin", str(bare))
            git(path, "config", "remote.origin.pushurl", str(bare))
        git(path, "push", "-q", str(bare), "main")
        git(path, "fetch", "-q", str(bare), "+refs/heads/*:refs/remotes/origin/*")
        git(path, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
        return path

    def worktree(self, repo, branch, home=".worktrees", files=(), dirty=()):
        tree = repo / home / branch.replace("/", "-")
        git(repo, "worktree", "add", "-q", "-b", branch, str(tree), "origin/main")
        git(tree, "config", "user.email", "t@example.com")
        git(tree, "config", "user.name", "t")
        for f in files:
            write(tree / f, "changed\n")
        if files:
            git(tree, "add", "-A")
            git(tree, "commit", "-q", "-m", "work")
        for f in dirty:
            write(tree / f, "dirty\n")
        return tree


class InflightTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.ws = Workspace(self.tmp)
        mock_env = dict(os.environ)
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(mock_env)))
        os.environ["INFLIGHT_GH"] = "no-such-gh-binary-for-tests"

    def collect(self, candidates=None, sessions=None):
        return inflight.collect([str(self.tmp)], candidates, sessions, now=NOW)

    def claims(self, report, repo):
        return [c for c in report.claims if c.repo == repo]

    def verdicts(self, report):
        return {v.id: v for v in report.verdicts}

    def test_worktree_claims_committed_and_uncommitted_files(self):
        repo = self.ws.repo("alpha")
        self.ws.worktree(repo, "feat/r12-export", files=["src/app.py"], dirty=["src/new.py"])
        [claim] = self.claims(self.collect(), "alpha")
        self.assertEqual(claim.kind, "worktree", "a linked worktree is a claim")
        self.assertEqual(claim.paths, ["src/app.py", "src/new.py"], "committed and untracked files both count")
        self.assertEqual(claim.ids, ["R12"], "the roadmap id comes from the branch name")

    def test_worktree_with_no_changes_has_unknown_footprint(self):
        repo = self.ws.repo("alpha")
        self.ws.worktree(repo, "worktree-r7-try", home=".claude/worktrees")
        report = self.collect([{"id": "R8", "repo": "alpha", "paths": ["docs/guide.md"]}])
        [claim] = self.claims(report, "alpha")
        self.assertIsNone(claim.paths, "no changes means an unknown footprint, never an empty one")
        self.assertEqual(claim.ids, ["R7"], "claude -w names the branch worktree-NAME; the id is still read")
        self.assertIsNotNone(claim.idle_hours, "an unknown footprint says how long it has been idle")
        self.assertEqual(self.verdicts(report)["R8"].state, "unknown")

    def test_idle_counts_from_when_head_moved_not_from_the_commit(self):
        repo = self.ws.repo("alpha")
        old = {**os.environ, "GIT_COMMITTER_DATE": "2020-01-01T00:00:00Z", "GIT_AUTHOR_DATE": "2020-01-01T00:00:00Z"}
        subprocess.run(["git", "-C", str(repo), "commit", "-q", "--allow-empty", "-m", "old"], check=True, env=old)
        git(repo, "worktree", "add", "-q", "-b", "fresh", str(repo / ".worktrees/fresh"), "HEAD")
        [claim] = self.claims(self.collect(), "alpha")
        self.assertLess(claim.idle_hours, 2, "a worktree made just now is not idle, however old its commit")

    def test_dotted_ids_are_kept_whole(self):
        repo = self.ws.repo("alpha")
        self.ws.worktree(repo, "claude/p2.3-export", files=["notes/x.md"])
        report = self.collect([{"id": "P2.3", "repo": "alpha", "paths": ["src/app.py"]},
                               {"id": "P2", "repo": "alpha", "paths": ["docs/guide.md"]}])
        self.assertEqual(inflight.ids_in_title("alpha P2.3: export"), ["P2.3"])
        v = self.verdicts(report)
        self.assertEqual(v["P2.3"].state, "taken")
        self.assertEqual(v["P2"].state, "clear", "P2.3 in flight does not take all of P2")

    def test_main_checkout_claims_only_when_dirty(self):
        repo = self.ws.repo("alpha")
        write(repo / ".worktrees/someone/file.txt")
        self.assertEqual(self.claims(self.collect(), "alpha"), [],
                         "a clean main checkout with an untracked worktree folder claims nothing")
        write(repo / "docs/guide.md", "edited\n")
        [claim] = self.claims(self.collect(), "alpha")
        self.assertEqual((claim.kind, claim.paths), ("checkout", ["docs/guide.md"]))

    def test_overlap_on_a_working_file_is_a_conflict(self):
        repo = self.ws.repo("alpha")
        self.ws.worktree(repo, "feat/r1-a", files=["src/app.py"])
        report = self.collect([
            {"id": "R2", "repo": "alpha", "paths": ["src/*.py"]},
            {"id": "R3", "repo": "alpha", "paths": ["docs/"]},
        ])
        v = self.verdicts(report)
        self.assertEqual(v["R2"].state, "conflict", "a glob that matches a claimed file conflicts")
        self.assertIn("src/app.py", v["R2"].reasons[0])
        self.assertEqual(v["R3"].state, "clear", "a disjoint folder is clear")

    def test_overlap_only_on_hot_files_is_a_rebase(self):
        repo = self.ws.repo("alpha", commits=12, every=["CHANGELOG.md"])
        self.ws.worktree(repo, "feat/r1-a", files=["CHANGELOG.md", "src/app.py"])
        report = self.collect([
            {"id": "R2", "repo": "alpha", "paths": ["CHANGELOG.md", "docs/guide.md"]},
            {"id": "R3", "repo": "alpha", "paths": ["CHANGELOG.md", "src/app.py"]},
        ])
        self.assertIn("CHANGELOG.md", report.repos[0].hot)
        v = self.verdicts(report)
        self.assertEqual(v["R2"].state, "rebase", "sharing only a hot file means a rebase")
        self.assertEqual(v["R3"].state, "conflict", "a hot file does not excuse a shared working file")

    def test_short_history_has_no_hot_files(self):
        repo = self.ws.repo("alpha", commits=5, every=["CHANGELOG.md"])
        self.ws.worktree(repo, "feat/r1-a", files=["CHANGELOG.md"])
        report = self.collect([{"id": "R2", "repo": "alpha", "paths": ["CHANGELOG.md"]}])
        self.assertEqual(report.repos[0].hot, set(), "five commits are too few to call any file hot")
        self.assertEqual(self.verdicts(report)["R2"].state, "conflict")

    def test_candidates_conflict_with_better_kept_candidates_only(self):
        self.ws.repo("alpha")
        self.ws.worktree(self.tmp / "alpha", "feat/r1-a", files=["src/app.py"])
        report = self.collect([
            {"id": "R2", "repo": "alpha", "paths": ["src/app.py", "docs/new.md"]},
            {"id": "R3", "repo": "alpha", "paths": ["docs/new.md"]},
            {"id": "R4", "repo": "alpha", "paths": ["docs/guide.md"]},
            {"id": "R5", "repo": "alpha", "paths": ["docs/guide.md"]},
        ])
        v = self.verdicts(report)
        self.assertEqual(v["R2"].state, "conflict")
        self.assertEqual(v["R3"].state, "clear", "a dropped candidate does not block the ones below it")
        self.assertEqual(v["R4"].state, "clear")
        self.assertEqual(v["R5"].state, "conflict", "two kept candidates may not share a file")
        self.assertIn("candidate R4", v["R5"].reasons[0])

    def test_taken_by_id_even_without_overlap(self):
        repo = self.ws.repo("alpha")
        self.ws.worktree(repo, "docs/m3-unit1-notes", files=["notes/x.md"])
        report = self.collect([{"id": "M3", "repo": "alpha", "paths": ["src/app.py"]}])
        self.assertEqual(self.verdicts(report)["M3"].state, "taken")

    def test_ids_are_scoped_to_their_repo(self):
        self.ws.repo("alpha")
        beta = self.ws.repo("beta")
        self.ws.worktree(beta, "feat/r9-b", files=["src/app.py"])
        report = self.collect([{"id": "R9", "repo": "alpha", "paths": ["src/app.py"]}])
        self.assertEqual(self.verdicts(report)["R9"].state, "clear", "R9 in beta says nothing about alpha")

    def test_pull_requests_join_their_worktree_and_include_drafts(self):
        repo = self.ws.repo("alpha", slug="example/alpha")
        self.ws.worktree(repo, "feat/r1-a", files=["src/app.py"])
        pulls = [
            {"number": 4, "title": "Export rows (R1)", "url": "https://github.com/example/alpha/pull/4",
             "headRefName": "feat/r1-a", "isDraft": False, "files": [{"path": "docs/guide.md"}]},
            {"number": 5, "title": "Sketch R6", "url": "https://github.com/example/alpha/pull/5",
             "headRefName": "sketch", "isDraft": True, "files": [{"path": "notes/0.md"}]},
        ]
        fake = self.tmp / "gh"
        fake.write_text(FAKE_GH)
        fake.chmod(0o755)
        (self.tmp / "pulls.json").write_text(json.dumps({"example/alpha": pulls}))
        os.environ["INFLIGHT_GH"] = str(fake)
        os.environ["INFLIGHT_FAKE_PULLS"] = str(self.tmp / "pulls.json")
        report = self.collect([{"id": "R6", "repo": "alpha", "paths": ["src/other.py"]},
                               {"id": "R7", "repo": "alpha", "paths": ["notes/0.md"]}])
        worktree, draft = self.claims(report, "alpha")
        self.assertEqual(worktree.paths, ["docs/guide.md", "src/app.py"], "a PR's files join its worktree claim")
        self.assertEqual(draft.kind, "pull")
        self.assertIn("(draft)", draft.links[0], "drafts are work in flight")
        v = self.verdicts(report)
        self.assertEqual(v["R6"].state, "taken", "an id in a PR title claims it")
        self.assertEqual(v["R7"].state, "conflict")

    def test_sessions_claim_ids_while_live(self):
        self.ws.repo("alpha")
        self.ws.repo("beta")
        recent = (NOW - timedelta(hours=2)).isoformat()
        old = (NOW - timedelta(hours=100)).isoformat()
        sessions = [
            {"title": "R1 in alpha", "cwd": str(self.tmp / "alpha"), "running": False, "last_active": recent},
            {"title": "R2 done", "cwd": str(self.tmp / "alpha"), "running": False, "last_active": recent,
             "pr_state": "MERGED"},
            {"title": "R3 long ago", "cwd": str(self.tmp / "alpha"), "running": False, "last_active": old},
            {"title": "R4 running", "cwd": str(self.tmp / "alpha"), "running": True, "last_active": old},
            {"title": "R5 elsewhere", "cwd": "/nowhere", "running": True},
        ]
        report = self.collect([{"id": f"R{n}", "repo": "alpha", "paths": [f"docs/{n}.md"]} for n in range(1, 6)]
                              + [{"id": "R1", "repo": "beta", "paths": ["docs/x.md"]}], sessions)
        states = [(v.repo, v.id, v.state) for v in report.verdicts]
        self.assertEqual(states, [
            ("alpha", "R1", "taken"), ("alpha", "R2", "clear"), ("alpha", "R3", "clear"),
            ("alpha", "R4", "taken"), ("alpha", "R5", "clear"), ("beta", "R1", "clear"),
        ], "running or recent unmerged sessions claim; a session in alpha claims nothing in beta")
        self.assertNotIn("footprint", " ".join(r for v in report.verdicts for r in v.reasons),
                         "a session claims ids only, never an unknown footprint")

    def test_session_in_a_folder_of_repos_claims_ids_everywhere(self):
        git(self.tmp, "init", "-q", "-b", "main")
        git(self.tmp, "-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "w")
        self.ws.repo("alpha")
        sessions = [{"title": "Work on M3", "cwd": str(self.tmp), "running": True}]
        report = self.collect([{"id": "M3", "repo": "alpha", "paths": ["docs/x.md"]}], sessions)
        self.assertEqual(self.verdicts(report)["M3"].state, "taken")

    def test_workspace_worktree_claims_its_ids_in_every_repo(self):
        workspace = self.ws.repo(".", commits=1)
        self.ws.repo("alpha")
        self.ws.worktree(workspace, "claude/r9-x", home=".claude/worktrees")
        report = self.collect([{"id": "R9", "repo": "alpha", "paths": ["docs/guide.md"]},
                               {"id": "R10", "repo": "alpha", "paths": ["docs/guide.md"]}])
        v = self.verdicts(report)
        self.assertEqual(v["R9"].state, "taken", "a session's workspace worktree branch takes its id in child repos")
        self.assertEqual(v["R10"].state, "clear", "a workspace worktree's unknown footprint is not booked to children")

    def test_broken_worktree_link_is_stale(self):
        self.ws.repo("alpha")
        orphan = self.tmp / ".worktrees/alpha-old"
        write(orphan / ".git", "gitdir: /no/such/place/.git/worktrees/alpha-old\n")
        report = self.collect()
        self.assertEqual(len(report.stale), 1)
        self.assertIn("alpha-old", report.stale[0])

    def test_cli_exit_codes(self):
        self.ws.repo("alpha")
        cands = self.tmp / "c.json"
        cands.write_text(json.dumps([{"id": "R1", "repo": "nope", "paths": ["x"]}]))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = inflight.main([str(self.tmp), "--candidates", str(cands), "--json"])
        self.assertEqual(code, 1, "a candidate in a repo that was not read is a problem")
        self.assertEqual(json.loads(out.getvalue())["problems"][0]["repo"], "nope")
        cands.write_text("{}")
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(inflight.main([str(self.tmp), "--candidates", str(cands)]), 2,
                             "a candidates file that is not a list is a usage error")


if __name__ == "__main__":
    unittest.main()
