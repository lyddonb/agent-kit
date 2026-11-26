"""Tests for bstack's waiting-on-me list (plugins/bstack/skills/waiting-on-me/scripts/waiting.py)."""
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
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "plugins/bstack/skills/waiting-on-me/scripts/waiting.py"
FIXTURES = ROOT / "tests/fixtures/waiting"

spec = importlib.util.spec_from_file_location("waiting", SCRIPT)
waiting = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = waiting
spec.loader.exec_module(waiting)

FAKE_GH = """#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
slug = args[args.index("--repo") + 1]
pulls = json.load(open(os.environ["WAITING_FAKE_PULLS"]))
answer = pulls.get(slug, [])
if isinstance(answer, dict):
    sys.stderr.write(answer["error"] + "\\n")
    sys.exit(1)
print(json.dumps(answer))
"""

PULLS = {
    "example/alpha": [
        {"number": 7, "title": "Add the demo", "url": "https://github.com/example/alpha/pull/7", "isDraft": False,
         "reviewDecision": "", "statusCheckRollup": [{"conclusion": "SUCCESS", "status": "COMPLETED"},
                                                     {"state": "SUCCESS"}]},
        {"number": 8, "title": "Sketch", "url": "https://github.com/example/alpha/pull/8", "isDraft": True,
         "reviewDecision": "", "statusCheckRollup": []},
        {"number": 3, "title": "Fix the docs", "url": "https://github.com/example/alpha/pull/3", "isDraft": False,
         "reviewDecision": "CHANGES_REQUESTED", "statusCheckRollup": [{"conclusion": "FAILURE", "status": "COMPLETED"}]},
    ],
    "example/beta": [
        {"number": 2, "title": "Bump", "url": "https://github.com/example/beta/pull/2", "isDraft": False,
         "reviewDecision": "", "statusCheckRollup": [{"state": "PENDING"}]},
    ],
    "example/gamma": {"error": "HTTP 403: Resource not accessible"},
    "example/remote-only": [
        {"number": 11, "title": "Remote change", "url": "https://github.com/example/remote-only/pull/11",
         "isDraft": False, "reviewDecision": "", "statusCheckRollup": []},
    ],
}


def git(path, *args):
    subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True, text=True)


TEMPLATE = {}


def setUpModule():
    TEMPLATE["tmp"] = tempfile.TemporaryDirectory()
    ws = Path(TEMPLATE["tmp"].name) / "ws"
    shutil.copytree(FIXTURES, ws)
    for name in ("alpha", "beta", "gamma", "delta"):
        repo = ws / name
        git(repo, "init", "-q", "-b", "main")
        git(repo, "-c", "user.email=t@example.com", "-c", "user.name=t", "add", "-A")
        git(repo, "-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-q", "-m", "fixture")
        git(repo, "remote", "add", "origin", f"git@github.com:/example/{name}")
        git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    (ws / ".hidden").mkdir()
    git(ws / ".hidden", "init", "-q")
    (ws / "notes").mkdir()
    TEMPLATE["ws"] = ws


def tearDownModule():
    TEMPLATE.pop("tmp").cleanup()


class Fixture:
    """A fresh copy of the fixture workspace with a fake gh on WAITING_GH."""

    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.ws = self.root / "ws"
        shutil.copytree(TEMPLATE["ws"], self.ws, symlinks=True)
        gh = self.root / "gh"
        gh.write_text(FAKE_GH)
        gh.chmod(0o755)
        pulls = self.root / "pulls.json"
        pulls.write_text(json.dumps(PULLS))
        self.env = {"WAITING_GH": str(gh), "WAITING_FAKE_PULLS": str(pulls)}
        self.old_env = {k: os.environ.get(k) for k in self.env}
        os.environ.update(self.env)

    def close(self):
        for k, v in self.old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def run_cli(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = waiting.main([*args])
        return code, out.getvalue()

    def report(self, *extra):
        code, out = self.run_cli(str(self.ws), "--json", *extra)
        return code, json.loads(out)


def ids(data, kind, repo):
    return [i["id"] for i in data["items"] if i["kind"] == kind and i["repo"] == repo]


class Workspace(unittest.TestCase):
    """Each test gets its own copy, for tests that change files or the environment."""

    def setUp(self):
        self.fx = Fixture()
        self.ws, self.root = self.fx.ws, self.fx.root

    def tearDown(self):
        self.fx.close()

    def report(self, *extra):
        return self.fx.report(*extra)

    def run_cli(self, *args):
        return self.fx.run_cli(*args)


class Shared(unittest.TestCase):
    """One read of an unchanged copy, shared by tests that only read the result."""

    @classmethod
    def setUpClass(cls):
        if "shared" not in TEMPLATE:
            fx = Fixture()
            try:
                code, data = fx.report()
                _, markdown = fx.run_cli(str(fx.ws))
                TEMPLATE["shared"] = (code, data, markdown)
            finally:
                fx.close()
        cls.code, cls.data, cls.markdown = TEMPLATE["shared"]


class TaskShapes(Shared):
    def test_a_status_table_keeps_only_rows_not_done_or_skipped(self):
        data = self.data
        self.assertEqual(ids(data, "task", "alpha"), ["H4", "H6", "H7"],
                         "To do, Partially done and 'steps 1 and 2 done; 3 and 4 to do' are open; Done and Skipped are not")

    def test_a_blocker_comes_first_with_what_it_blocks(self):
        data = self.data
        blockers = [i for i in data["items"] if i["kind"] == "blocker"]
        self.assertEqual([(i["repo"], i["id"], i["blocks"]) for i in blockers],
                         [("alpha", "H5", "ROADMAP R10, R12"), ("gamma", "T33", "")])
        self.assertEqual(data["items"][0]["kind"], "blocker", "blockers lead the list")

    def test_a_done_checkbox_column_keeps_unticked_rows_with_their_unblocks(self):
        data = self.data
        beta = [(i["id"], i["blocks"], i["state"]) for i in data["items"] if i["kind"] == "task" and i["repo"] == "beta"]
        self.assertEqual(beta, [("H2", "K7.1", ""), ("H3", "K8.2", "Halfway: serif picked, size not")])

    def test_bullets_under_open_are_tasks_and_bullets_under_done_are_not(self):
        data = self.data
        self.assertEqual(ids(data, "task", "gamma"), ["T31"])
        t31 = next(i for i in data["items"] if i["repo"] == "gamma" and i["id"] == "T31")
        self.assertEqual(t31["title"], "Water the fern")
        self.assertEqual(t31["blocks"], "the repotting step")

    def test_a_file_in_no_known_shape_is_reported_not_read_as_empty(self):
        code, data = self.code, self.data
        self.assertEqual(code, 1, "a problem makes the exit code 1")
        self.assertIn(("delta", "no task table"), [(p["repo"], p["message"][:13]) for p in data["problems"]])


class Gates(Shared):
    def test_only_a_gate_after_the_last_answer_in_an_unsealed_run_is_open(self):
        data = self.data
        gates = [i for i in data["items"] if i["kind"] == "gate"]
        self.assertEqual([(g["id"], g["state"]) for g in gates], [("2026-01-02-open-run#4", "delete-data")],
                         "seq 2 was answered at seq 3, and the sealed run's gate is closed by its seal")
        path, line = gates[0]["link"].rsplit(":", 1)
        entry = json.loads((FIXTURES / path.split("/ws/", 1)[1]).read_text().splitlines()[int(line) - 1])
        self.assertEqual((entry["type"], entry["seq"]), ("gate", 4), "the link points at the gate entry")


class Questions(Shared):
    def test_open_questions_without_an_answer_line_are_listed(self):
        data = self.data
        qs = [(i["id"], i["title"]) for i in data["items"] if i["kind"] == "question"]
        self.assertEqual(qs, [("Q21", "Garden hose"), ("Q23", "Spare key")],
                         "Q22 has an Answer: line, Q20 is under Answered, and Answer inside Q23's text is not an answer")


class Pulls(Shared):
    def test_open_pull_requests_that_are_not_drafts_with_their_check_state(self):
        data = self.data
        pulls = [(i["repo"], i["id"], i["state"]) for i in data["items"] if i["kind"] == "pull"]
        self.assertEqual(pulls, [
            ("alpha", "#3", "checks failing, review changes requested"),
            ("alpha", "#7", "checks passing"),
            ("beta", "#2", "checks pending"),
        ])

    def test_a_gh_failure_for_one_repo_is_reported_and_the_rest_still_list(self):
        code, data = self.code, self.data
        self.assertEqual(code, 1)
        self.assertIn(("gamma", "HTTP 403: Resource not accessible"),
                      [(p["repo"], p["message"]) for p in data["problems"]])


class Links(Shared):
    def test_a_file_that_matches_the_remote_links_to_github_at_its_line(self):
        data = self.data
        h4 = next(i for i in data["items"] if i["repo"] == "alpha" and i["id"] == "H4")
        self.assertEqual(h4["link"], "https://github.com/example/alpha/blob/main/HUMAN_TASKS.md#L8")
        line = (FIXTURES / "alpha/HUMAN_TASKS.md").read_text().splitlines()[7]
        self.assertIn("H4", line, "line 8 is H4's row")


class Repos(Shared):
    def test_a_folder_of_repos_reads_each_child_and_skips_hidden_and_plain_folders(self):
        data = self.data
        self.assertEqual([r["name"] for r in data["repos"]], ["alpha", "beta", "delta", "gamma"])
        self.assertEqual(data["repos"][0]["github"], "example/alpha", "the git@github.com:/owner/name form parses")


class Markdown(Shared):
    def test_sections_come_in_order_with_counts_and_every_item_has_a_link(self):
        out = self.markdown
        headings = [line for line in out.splitlines() if line.startswith("## ")]
        self.assertEqual(headings, [
            "## Blockers (2)", "## Open ledger gates (1)", "## Pull requests waiting on review or merge (3)",
            "## Human tasks (6)", "## Open questions (2)", "## Could not read (2)",
        ])
        items = [line for line in out.splitlines() if line.startswith("- ") and "Could not" not in line]
        listed = [line for line in items if line.endswith(">")]
        self.assertEqual(len(listed), 14, "every listed item ends with its link")
        self.assertIn("- alpha H5: Try it on real work (blocks ROADMAP R10, R12) "
                      "<https://github.com/example/alpha/blob/main/HUMAN_TASKS.md#L9>", out)


class GatesChanges(Workspace):
    def test_a_torn_line_is_reported_and_the_other_entries_still_count(self):
        ledger = self.ws / "alpha/.audit/runs/2026-01-02-open-run/ledger.jsonl"
        with ledger.open("a") as f:
            f.write('{"type": "gate-answer", "se')
        _, data = self.report()
        self.assertEqual([i["id"] for i in data["items"] if i["kind"] == "gate"], ["2026-01-02-open-run#4"])
        self.assertTrue(any(p["source"] == f"{ledger.resolve()}:6" for p in data["problems"]), data["problems"])

    def test_a_run_that_lives_only_in_a_worktree_is_read(self):
        alpha = self.ws / "alpha"
        tree = self.root / "alpha-wt"
        git(alpha, "worktree", "add", "-q", "-b", "lane", str(tree))
        run = tree / ".audit/runs/2026-01-09-branch-run"
        run.mkdir(parents=True)
        run.joinpath("ledger.jsonl").write_text(json.dumps(
            {"seq": 1, "type": "gate", "summary": "migration: about to migrate", "data": {"gate": "migration"}}) + "\n")
        _, data = self.report()
        self.assertIn("2026-01-09-branch-run#1", [i["id"] for i in data["items"] if i["kind"] == "gate"])


class PullsChanges(Workspace):
    def test_a_github_name_adds_its_pull_requests_only(self):
        _, data = self.report("--github", "example/remote-only", "--github", "example/alpha")
        self.assertIn(("remote-only", "#11"), [(i["repo"], i["id"]) for i in data["items"] if i["kind"] == "pull"])
        self.assertEqual([r["name"] for r in data["repos"]].count("alpha"), 1, "a name already read is not added twice")

    def test_no_gh_is_reported_and_the_files_are_still_read(self):
        os.environ["WAITING_GH"] = str(self.root / "missing-gh")
        code, data = self.report()
        self.assertEqual(code, 1)
        self.assertIn("cannot find the gh CLI", " ".join(p["message"] for p in data["problems"]))
        self.assertTrue(ids(data, "task", "alpha"))


class LinksChanges(Workspace):
    def test_a_locally_changed_file_links_to_its_path_and_line(self):
        path = self.ws / "beta/questions.md"
        path.write_text(path.read_text().replace("Garden hose", "Garden rake"))
        _, data = self.report()
        q21 = next(i for i in data["items"] if i["id"] == "Q21")
        self.assertEqual(q21["link"], f"{path.resolve()}:7")


class ReposChanges(Workspace):
    def test_one_repo_path_reads_just_that_repo(self):
        code, out = self.run_cli(str(self.ws / "beta"), "--json")
        self.assertEqual([r["name"] for r in json.loads(out)["repos"]], ["beta"])
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
