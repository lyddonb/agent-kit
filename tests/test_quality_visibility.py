"""Tests for the visibility books (`books/repos.csv`) and `quality.py leak-check`
(plugins/bstack/skills/qualitydirector/scripts/quality.py).

Every repo, test id, sha and link here is made up. Books are written by hand (`Builder`); `fetch` is driven through the fake
`gh` of test_quality_fetch with its clock set, and nothing reads the network, the clock or sleeps. The tests under
UnadoptedBooksTest hold literal expectations that the script before `repos.csv` met too (run them with QUALITY_SCRIPT pointing at
that script to see it).
"""
import contextlib
import csv
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import time
import unittest
import unittest.mock
from pathlib import Path

import test_quality_fetch as tf
import test_quality_ingest as ti

quality = tf.quality
SECRET, OPEN = ("secret-app", "acme/secret-app"), ("open-lib", "acme/open-lib")
SHA_SECRET = "5ec2e7a91b3c4d5e6f708192a3b4c5d6e7f80912"
SHA_OPEN = "0be11b0a1c2d3e4f5061728394a5b6c7d8e9f001"
STAMP = "2026-11-20T10:00:00Z"
TODAY = "2026-11-15"
WORKFLOW = "ci"


def write_csv(path: Path, header: tuple, rows: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    path.write_text(out.getvalue())


def link(slug: str, n: int) -> str:
    return f"https://github.com/{slug}/actions/runs/{n}/attempts/1"


class Builder:
    """Books that pass `check`: a watch list, runs with their failures, weekly rows, jobs and steps, and repos.csv."""

    def __init__(self, *watch: tuple[str, str]):
        self.watched = list(watch)
        self.runs, self.failures, self.weekly, self.jobs, self.steps, self.repos = [], [], {}, [], [], []
        self.job_id = 0

    def run(self, repo: str, slug: str, n: int, sha: str, failing=(), jobs=()) -> "Builder":
        """A run of `repo` (jobs: (job name, [step names]) pairs)."""
        evidence, started = link(slug, n), "2026-11-10T10:00:00Z"
        self.runs.append([started, repo, sha, "push", WORKFLOW, "3.12", len(failing) + 1, len(failing), 0, 1000, int(bool(failing)), evidence])
        for test_id in failing:
            self.failures.append([started, repo, sha, "3.12", test_id, "fail", evidence])
            self.weekly[("2026-W46", repo, test_id)] = ["2026-W46", repo, test_id, 1, 1, 10, 10]
        for name, steps in jobs:
            self.job_id += 1
            self.jobs.append([started, repo, sha, "push", WORKFLOW, name, self.job_id, "success", "", "", "", evidence])
            self.steps.extend(["", repo, self.job_id, i, step, "success", "", evidence] for i, step in enumerate(steps, 1))
        return self

    def visibility(self, seen: str, repo: str, slug: str, value: str) -> "Builder":
        self.repos.append([seen, repo, slug, value])
        return self

    def write(self, folder: Path, repos: bool = True, jobs: bool = True) -> Path:
        S = quality
        write_csv(folder / S.WATCHED, S.WATCHED_SCHEMA, [[r, s, WORKFLOW] for r, s in self.watched])
        write_csv(folder / S.RUNS, S.RUNS_SCHEMA, self.runs)
        write_csv(folder / S.FAILURES, S.FAILURES_SCHEMA, self.failures)
        write_csv(folder / S.WEEKLY, S.WEEKLY_SCHEMA, [self.weekly[k] for k in sorted(self.weekly)])
        if jobs:
            write_csv(folder / S.JOBS, S.JOBS_SCHEMA, self.jobs)
            write_csv(folder / S.STEPS, S.STEPS_SCHEMA, self.steps)
        if repos:
            write_csv(folder / S.REPOS, S.REPOS_SCHEMA, sorted(self.repos, key=lambda r: (r[0], r[1])))
        return folder


class TempCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.books = self.tmp / "books-repo"

    def repos_text(self) -> str:
        return (self.books / quality.REPOS).read_text()


# ---------------------------------------------------------------------------
# check
# ---------------------------------------------------------------------------

class CheckReposTest(TempCase):
    def books_with(self, *rows) -> None:
        b = Builder(SECRET, OPEN)
        for row in rows:
            b.visibility(*row)
        b.write(self.books)

    def problems(self, *extra) -> list[str]:
        code, out = tf.cli("check", self.books, *extra)
        self.assertEqual(code, 1, out)
        return out.splitlines()

    def test_good_rows_pass_and_are_counted(self):
        self.books_with((STAMP, "secret-app", "acme/secret-app", "private"), (STAMP, "open-lib", "acme/open-lib", "public"))
        self.assertEqual(tf.cli("check", self.books), (0, "ok, 4 rows, 0 problems\n"))

    def test_every_value_visibility_may_take_is_allowed_and_nothing_else(self):
        self.books_with(*((f"2026-11-2{i}T10:00:00Z", "secret-app", "acme/secret-app", v) for i, v in enumerate(quality.VISIBILITIES)))
        self.assertEqual(tf.cli("check", self.books)[0], 0)
        self.books_with((STAMP, "secret-app", "acme/secret-app", "Public"))
        self.assertIn("books/repos.csv:2: visibility must be one of public, private, internal, unknown, got 'Public'", self.problems())

    def test_the_header_the_types_and_the_text_rules_are_held(self):
        self.books_with((STAMP, "Secret App", "acme", "private"), ("2026-11-20 10:00:00", "secret-app", "acme/secret-app", "private"),
                        ("2026-11-21T10:00:00Z", "secret-app", "acme/secret-app", "private"))
        out = "\n".join(self.problems())
        self.assertIn("books/repos.csv:3: repo must match", out)
        self.assertIn("books/repos.csv:3: github must look like OWNER/NAME", out)
        self.assertIn("books/repos.csv:2: seen must look like 2026-11-15T09:30:00Z", out)
        (self.books / quality.REPOS).write_text("seen,repo,github\n")
        self.assertIn("books/repos.csv:1: header does not match the schema: expected seen,repo,github,visibility", "\n".join(self.problems()))

    def test_rows_must_be_sorted_by_seen_then_repo_and_unique(self):
        b = Builder(SECRET, OPEN)
        b.write(self.books)
        write_csv(self.books / quality.REPOS, quality.REPOS_SCHEMA, [
            ["2026-11-20T10:00:00Z", "secret-app", "acme/secret-app", "private"], ["2026-11-20T10:00:00Z", "open-lib", "acme/open-lib", "public"],
            ["2026-11-20T10:00:00Z", "open-lib", "acme/open-lib", "private"], ["2026-11-19T10:00:00Z", "open-lib", "acme/open-lib", "public"]])
        out = self.problems()
        self.assertIn("books/repos.csv:3: not sorted by seen, repo", out)
        self.assertIn("books/repos.csv:4: duplicate of line 3 (same seen and repo)", out)
        self.assertIn("books/repos.csv:5: not sorted by seen, repo", out)

    def test_the_file_is_append_only_against_a_base(self):
        self.books_with((STAMP, "secret-app", "acme/secret-app", "private"))
        git = lambda *a: subprocess.run(["git", "-C", str(self.books), "-c", "user.name=t", "-c", "user.email=t@example.com",
                                         "-c", "commit.gpgsign=false", *a], capture_output=True, check=True)
        git("init", "-q")
        git("add", "-A")
        git("commit", "-q", "-m", "books")
        self.assertEqual(tf.cli("check", self.books, "--base", "HEAD")[0], 0)
        with open(self.books / quality.REPOS, "a") as f:
            f.write("2026-11-21T10:00:00Z,secret-app,acme/secret-app,public\n")
        self.assertEqual(tf.cli("check", self.books, "--base", "HEAD")[0], 0)  # a row at the end is fine
        (self.books / quality.REPOS).write_text(self.repos_text().replace(",private\n", ",public\n", 1))
        self.assertIn("books/repos.csv:2: changed since HEAD", self.problems("--base", "HEAD"))
        (self.books / quality.REPOS).unlink()
        self.assertIn("books/repos.csv:1: removed since HEAD", self.problems("--base", "HEAD"))


# ---------------------------------------------------------------------------
# fetch
# ---------------------------------------------------------------------------

def run_obj(run_id: int, slug: str, **over) -> dict:
    run = {"id": run_id, "name": WORKFLOW, "status": "completed", "conclusion": "success", "event": "pull_request", "head_sha": f"{run_id:040x}",
           "head_branch": "feat/x", "run_attempt": 1, "run_started_at": "2026-11-14T10:00:00Z", "updated_at": "2026-11-14T10:10:00Z",
           "head_repository": {"full_name": slug}}
    run.update(over)
    return run


class FetchBase(TempCase):
    def setUp(self):
        super().setUp()
        self.out = self.tmp / "out"
        self.data = self.tmp / "data"
        (self.data / "api").mkdir(parents=True)
        self.gh = self.tmp / "bin" / "gh"
        self.gh.parent.mkdir()
        self.gh.write_text(tf.FAKE_GH)
        self.gh.chmod(self.gh.stat().st_mode | stat.S_IXUSR)
        for patcher in (unittest.mock.patch.dict(os.environ, {"QUALITY_GH": str(self.gh), "FAKE_GH_DATA": str(self.data)}),
                        unittest.mock.patch.object(quality, "utc_stamp", return_value=STAMP, create=True)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def put(self, endpoint: str, value) -> None:
        (self.data / "api" / (endpoint.replace("/", "__") + ".json")).write_text(value if isinstance(value, str) else json.dumps(value))

    def listing(self, slug: str, *runs: dict) -> None:
        self.put(f"repos/{slug}/actions/runs", json.dumps({"total_count": len(runs), "workflow_runs": list(runs)}))

    def endpoints(self) -> list[str]:
        log = self.data / "calls.log"
        calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
        return [next(a for a in call[1:] if not a.startswith("-")).split("?")[0] for call in calls]

    def fetch(self, *extra) -> tuple[int, str]:
        return tf.cli("fetch", self.books, self.out, "--today", TODAY, *extra)

    def repo_json(self, repo: str) -> dict:
        return json.loads((self.out / repo / "repo.json").read_text())


class FetchVisibilityTest(FetchBase):
    def test_each_answer_is_stored_by_the_rule_and_a_repo_without_runs_still_gets_its_file(self):
        names = {"pub-api": {"visibility": "public", "private": False, "default_branch": "main"},
                 "int-api": {"visibility": "internal", "private": True},
                 "old-api": {"private": True},
                 "bare-api": {"default_branch": "main"}}
        Builder(*((n, f"acme/{n}") for n in names)).write(self.books, jobs=False)
        for name, answer in names.items():
            self.listing(f"acme/{name}")
            self.put(f"repos/acme/{name}", answer)
        code, out = self.fetch()
        self.assertEqual(code, 0, out)
        self.assertEqual({n: self.repo_json(n) for n in names},
                         {n: {"v": 1, "repo": n, "github": f"acme/{n}", "visibility": v, "seen": STAMP}
                          for n, v in {"pub-api": "public", "int-api": "internal", "old-api": "private", "bare-api": "unknown"}.items()})
        self.assertIn("pub-api (acme/pub-api, ci): runs created since 2026-11-08\n  visibility: public\n", out)
        self.assertIn("  visibility: internal\n", out)
        self.assertEqual(sorted(self.endpoints()), sorted([f"repos/acme/{n}/actions/runs" for n in names] + [f"repos/acme/{n}" for n in names]))
        self.assertEqual((self.out / "pub-api" / "repo.json").read_text(), json.dumps(self.repo_json("pub-api"), sort_keys=True, indent=2) + "\n")

    def test_the_rule_for_every_answer_shape(self):
        for answer, expected in [({"visibility": "public"}, "public"), ({"visibility": "public", "private": False}, "public"),
                                 ({"visibility": "public", "private": True}, "private"), ({"visibility": "internal", "private": True}, "internal"),
                                 ({"visibility": "private"}, "private"), ({"private": True}, "private"), ({"private": False}, "public"),
                                 ({}, "unknown"), ({"visibility": "banana", "private": False}, "unknown"), ({"visibility": ["public"]}, "unknown"),
                                 ({"visibility": None, "private": "no"}, "unknown"), ("public", "unknown"), (None, "unknown")]:
            self.assertEqual(quality.visibility_of(answer), expected, answer)

    def test_a_run_is_fetched_with_one_call_for_the_repo_and_the_file_is_written(self):
        Builder(OPEN).write(self.books, jobs=False)
        self.listing("acme/open-lib", run_obj(101, "acme/open-lib"))
        self.put("repos/acme/open-lib", {"visibility": "public", "default_branch": "main"})
        self.put("repos/acme/open-lib/actions/runs/101/artifacts", {"artifacts": []})
        code, out = self.fetch()
        self.assertEqual(code, 0, out)
        self.assertEqual(self.endpoints().count("repos/acme/open-lib"), 1)
        self.assertEqual(self.repo_json("open-lib")["visibility"], "public")
        self.assertTrue((self.out / "open-lib" / "101" / "manifest.json").exists() or "1 without test-results artifacts" in out)

    def test_a_failed_call_books_unknown_and_counts_one_failure(self):
        Builder(OPEN).write(self.books, jobs=False)
        self.listing("acme/open-lib", run_obj(101, "acme/open-lib"))
        (self.data / "api" / "repos__acme__open-lib.error").write_text("gh: Not Found (HTTP 404)\n")
        code, out = self.fetch()
        self.assertEqual(code, 1, out)
        self.assertEqual(self.repo_json("open-lib")["visibility"], "unknown")
        self.assertEqual(out.count("FAILED"), 1)
        self.assertIn("  FAILED default branch: ", out)
        self.assertTrue(out.endswith("; 1 failed\n"), out)
        self.assertEqual(self.endpoints().count("repos/acme/open-lib"), 1)

    def test_a_failed_call_for_a_repo_without_runs_is_a_failure_too(self):
        Builder(OPEN).write(self.books, jobs=False)
        self.listing("acme/open-lib")
        code, out = self.fetch()
        self.assertEqual(code, 1, out)
        self.assertEqual(self.repo_json("open-lib")["visibility"], "unknown")
        self.assertIn("  FAILED visibility: ", out)

    def test_a_failed_listing_still_asks_for_visibility_and_counts_only_the_listing(self):
        Builder(OPEN).write(self.books, jobs=False)
        self.put("repos/acme/open-lib", {"visibility": "private"})
        code, out = self.fetch()
        self.assertEqual(code, 1, out)
        self.assertEqual(self.repo_json("open-lib")["visibility"], "private")
        self.assertEqual(out.count("FAILED"), 1)
        self.assertIn("FAILED listing", out)

    def test_repo_limits_the_calls_and_the_files(self):
        Builder(SECRET, OPEN).write(self.books, jobs=False)
        self.listing("acme/open-lib")
        self.put("repos/acme/open-lib", {"visibility": "public"})
        self.assertEqual(self.fetch("--repo", "open-lib")[0], 0)
        self.assertEqual(sorted(p.name for p in self.out.iterdir()), ["open-lib"])
        self.assertEqual(sorted(self.endpoints()), ["repos/acme/open-lib", "repos/acme/open-lib/actions/runs"])


# ---------------------------------------------------------------------------
# books without repos.csv: every command as before
# ---------------------------------------------------------------------------

class UnadoptedBooksTest(TempCase):
    def test_check_says_what_it_said_before(self):
        Builder(SECRET).run("secret-app", "acme/secret-app", 1, SHA_SECRET, failing=["tests.test_vault.VaultTest.test_rotates_keys"]).write(self.books, repos=False, jobs=False)
        self.assertEqual(tf.cli("check", self.books), (0, "ok, 4 rows, 0 problems\n"))
        (self.books / "stray-repo.json").write_text("{}")
        self.assertEqual(tf.cli("check", self.books), (0, "ok, 4 rows, 0 problems\n"))

    def test_check_with_a_base_does_not_look_for_the_file(self):
        Builder(SECRET).write(self.books, repos=False)
        git = lambda *a: subprocess.run(["git", "-C", str(self.books), "-c", "user.name=t", "-c", "user.email=t@example.com",
                                         "-c", "commit.gpgsign=false", *a], capture_output=True, check=True)
        git("init", "-q")
        git("add", "-A")
        git("commit", "-q", "-m", "books")
        self.assertEqual(tf.cli("check", self.books, "--base", "HEAD"), (0, "ok, 1 rows, 0 problems\n"))

    def test_summary_does_not_read_the_file_at_all(self):
        b = Builder(SECRET).run("secret-app", "acme/secret-app", 1, SHA_SECRET, failing=["tests.test_vault.VaultTest.test_rotates_keys"])
        b.write(self.books, repos=False)
        plain = [tf.cli("summary", self.books), tf.cli("summary", self.books, "--json")]
        b.visibility(STAMP, "secret-app", "acme/secret-app", "private").write(self.books)
        self.assertEqual([tf.cli("summary", self.books), tf.cli("summary", self.books, "--json")], plain)
        self.assertEqual(plain[0][0], 0)
        self.assertNotIn("visibility", plain[1][1])
        self.assertNotIn("repos.csv", plain[0][1] + plain[1][1])

    def test_ingest_ignores_repo_json_files_and_prints_and_writes_what_it_did(self):
        books, art = ti.header_only_books(self.tmp / "ib"), self.tmp / "art"
        art.mkdir()
        ti.put_good_run(art, 1)
        ti.put(art, "demo/repo.json", json.dumps({"v": 1, "repo": "demo", "github": "example/demo", "visibility": "private", "seen": STAMP}))
        ti.put(art, "other/repo.json", "not json at all")
        code, out = ti.cli("ingest", books, art)
        self.assertEqual((code, out), (0, f"booked: demo/1/artifacts/test-results-py3.12/test-results.jsonl: demo 3.12 2 tests, exit_code 0, {ti.ev(1)}\n"
                                          "booked 1 runs, 0 failures, 2 weekly rows touched; skipped 0 already booked, 0 duplicates; rejected 0 of 1 files\n"))
        self.assertFalse((books / "books/repos.csv").exists())
        self.assertEqual(sorted(p.name for p in (books / "books").iterdir()), ["failures.csv", "runs.csv", "tests-weekly.csv", "watched.csv"])
        code, out = ti.cli("ingest", books, art, "--json")
        self.assertEqual(code, 0, out)
        self.assertEqual(sorted(json.loads(out)), ["dry_run", "files", "totals", "wrote"])
        self.assertNotIn("visibility", json.loads(out)["totals"])
        for only in ("jobs",):
            self.assertEqual(ti.cli("ingest", books, art, "--only", only)[0], 2)

    def test_ingest_only_visibility_needs_the_file(self):
        books, art = ti.header_only_books(self.tmp / "ib"), self.tmp / "art"
        art.mkdir()
        code, out = ti.cli("ingest", books, art, "--only", "visibility")
        self.assertEqual(code, 2, out)
        self.assertIn("--only visibility needs books/repos.csv", out)

    def test_fetch_makes_no_call_for_a_repo_without_runs_writes_no_file_and_prints_no_line(self):
        case = FetchBase()
        case.setUp()
        try:
            Builder(OPEN, SECRET).write(case.books, repos=False, jobs=False)
            case.listing("acme/open-lib", run_obj(101, "acme/open-lib"))
            case.put("repos/acme/open-lib", {"visibility": "public", "default_branch": "main"})
            case.put("repos/acme/open-lib/actions/runs/101/artifacts", {"artifacts": []})
            case.listing("acme/secret-app")
            code, out = case.fetch()
            self.assertEqual((code, out), (0, "open-lib (acme/open-lib, ci): runs created since 2026-11-08\n"
                                              "secret-app (acme/secret-app, ci): runs created since 2026-11-08\n"
                                              "fetched 0 runs (0 artifacts); listed 1; skipped 0 forks, 0 pushes to a non-default branch, "
                                              "0 already booked, 1 without test-results artifacts; 0 failed\n"))
            self.assertEqual(case.endpoints(), ["repos/acme/open-lib/actions/runs", "repos/acme/open-lib", "repos/acme/open-lib/actions/runs/101/artifacts",
                                                "repos/acme/secret-app/actions/runs"])
            self.assertEqual(list(case.out.rglob("repo.json")), [])
        finally:
            case.doCleanups()


# ---------------------------------------------------------------------------
# ingest
# ---------------------------------------------------------------------------

def repo_file(repo: str, visibility: str, seen: str = STAMP, slug: str | None = None, **over) -> dict:
    body = {"v": 1, "repo": repo, "github": slug or f"acme/{repo}", "visibility": visibility, "seen": seen}
    body.update(over)
    return body


class IngestVisibilityTest(TempCase):
    def setUp(self):
        super().setUp()
        self.art = self.tmp / "art"
        self.art.mkdir()
        self.builder = Builder(SECRET, OPEN)
        self.builder.write(self.books)

    def put(self, repo: str, body, name: str = "repo.json") -> None:
        ti.put(self.art, f"{repo}/{name}", body if isinstance(body, (str, bytes)) else json.dumps(body))

    def ingest(self, *extra) -> tuple[int, str]:
        return ti.cli("ingest", self.books, self.art, *extra)

    def rows(self) -> list[list[str]]:
        return ti.csv_rows(self.books / quality.REPOS)[1:]

    def test_a_first_answer_is_booked_and_a_second_ingest_adds_nothing(self):
        self.put("secret-app", repo_file("secret-app", "private"))
        self.put("open-lib", repo_file("open-lib", "public"))
        code, out = self.ingest()
        self.assertEqual(code, 0, out)
        self.assertIn("booked visibility open-lib: public\nbooked visibility secret-app: private\n", out)
        self.assertEqual(self.rows(), [[STAMP, "open-lib", "acme/open-lib", "public"], [STAMP, "secret-app", "acme/secret-app", "private"]])
        self.assertEqual(tf.cli("check", self.books)[0], 0)
        before = self.repos_text()
        code, out = self.ingest()
        self.assertEqual(code, 0, out)
        self.assertIn("visibility open-lib: unchanged (public)\nvisibility secret-app: unchanged (private)\n", out)
        self.assertNotIn("booked visibility", out)
        self.assertEqual(self.repos_text(), before)

    def test_a_change_is_booked_and_said_in_a_line_for_the_brief(self):
        self.put("secret-app", repo_file("secret-app", "public"))
        self.ingest()
        self.put("secret-app", repo_file("secret-app", "private", seen="2026-11-21T10:00:00Z"))
        code, out = self.ingest()
        self.assertEqual(code, 0, out)
        self.assertIn("booked visibility secret-app: private\nvisibility secret-app changed: public -> private\n", out)
        self.assertEqual([r[3] for r in self.rows()], ["public", "private"])
        self.put("secret-app", repo_file("secret-app", "unknown", seen="2026-11-22T10:00:00Z"))
        self.assertIn("visibility secret-app changed: private -> unknown\n", self.ingest()[1])

    def test_dry_run_says_would_book_and_writes_nothing(self):
        self.put("secret-app", repo_file("secret-app", "private"))
        before = self.repos_text()
        code, out = self.ingest("--dry-run")
        self.assertEqual(code, 0, out)
        self.assertIn("would book visibility secret-app: private\n", out)
        self.assertEqual(self.repos_text(), before)

    def test_json_lists_each_file_and_the_totals_count_them(self):
        self.put("secret-app", repo_file("secret-app", "private"))
        self.put("open-lib", repo_file("open-lib", "public", v=2))
        code, out = self.ingest("--json")
        data = json.loads(out)
        self.assertEqual(code, 1, out)
        self.assertEqual(data["visibility"], [{"path": "open-lib/repo.json", "reason": "repo.json v must be 1, got 2", "status": "rejected"},
                                              {"path": "secret-app/repo.json", "status": "booked", "visibility": "private"}])
        self.assertEqual({k: v for k, v in data["totals"].items() if k.startswith("visibility")},
                         {"visibility_booked": 1, "visibility_unchanged": 0, "visibility_rejected": 1})
        self.assertEqual(out, json.dumps(data, sort_keys=True, indent=2) + "\n")

    def test_only_visibility_reads_no_artifact_and_books_no_job(self):
        ti.put_good_run(self.art, 1)
        self.put("secret-app", repo_file("secret-app", "private"))
        ti.put(self.art, "stray.jsonl", "x\n")
        ti.put(self.art, "demo/9/jobs.json", "not json")
        before = {rel: (self.books / rel).read_bytes() for rel in (quality.RUNS, quality.FAILURES, quality.WEEKLY, quality.JOBS, quality.STEPS)}
        code, out = self.ingest("--only", "visibility")
        self.assertEqual((code, out), (0, "booked visibility secret-app: private\n"))
        self.assertEqual({rel: (self.books / rel).read_bytes() for rel in before}, before)
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(self.ingest("--only", "visibility")[1], "visibility secret-app: unchanged (private)\n")

    def test_only_visibility_with_no_file_says_so(self):
        self.assertEqual(self.ingest("--only", "visibility"), (0, "no repo.json files\n"))

    def test_only_jobs_leaves_the_visibility_book_alone_and_says_nothing_of_it(self):
        self.put("secret-app", repo_file("secret-app", "private"))
        before = self.repos_text()
        code, out = self.ingest("--only", "jobs")
        self.assertEqual(code, 0, out)
        self.assertNotIn("visibility", out)
        self.assertEqual(self.repos_text(), before)

    def test_the_other_books_ingest_with_repos_csv_too(self):
        ti.put_good_run(self.art, 1)
        self.put("secret-app", repo_file("secret-app", "private"))
        ti.put(self.art, "demo/1/manifest.json", json.dumps(ti.manifest(1)))
        self.builder.watched.append(("demo", "example/demo"))
        self.builder.write(self.books)
        code, out = self.ingest()
        self.assertEqual(code, 0, out)
        self.assertIn("booked 1 runs", out)
        self.assertIn("booked visibility secret-app: private\n", out)
        self.assertEqual(tf.cli("check", self.books)[0], 0)

    def test_a_file_is_read_strictly_and_a_bad_one_is_rejected_by_name_with_exit_1(self):
        good = repo_file("secret-app", "private")
        bad = {"not json": "{", "not an object": "[]", "a missing key": {k: v for k, v in good.items() if k != "seen"},
               "an unknown key": dict(good, extra=1), "a v that is not 1": dict(good, v=2), "a v that is a bool": dict(good, v=True),
               "a visibility that is not text": dict(good, visibility=1), "a visibility it does not know": dict(good, visibility="Public"),
               "another repo's name": dict(good, repo="open-lib"), "another github": dict(good, github="acme/else"),
               "a bad stamp": dict(good, seen="yesterday"), "a NUL": dict(good, github="acme/secret-app\x00"),
               "a duplicate key": '{"v":1,"v":1,"repo":"secret-app","github":"acme/secret-app","visibility":"private","seen":"%s"}' % STAMP}
        before = self.repos_text()
        for what, body in bad.items():
            with self.subTest(what):
                self.put("secret-app", body)
                code, out = self.ingest()
                self.assertEqual(code, 1, out)
                self.assertIn("rejected: secret-app/repo.json: ", out)
                self.assertIn("some files were rejected or not read", out)
                self.assertEqual(self.repos_text(), before)
        self.put("secret-app", dict(good, github="ACME/Secret-App"))  # GitHub names are not case sensitive
        self.assertEqual(self.ingest()[0], 0)
        self.assertEqual(self.rows()[0][2], "acme/secret-app")  # booked under the watch list's spelling

    def test_a_repo_off_the_watch_list_a_link_and_a_big_file_are_rejected(self):
        self.put("gone-app", repo_file("gone-app", "private"))
        ti.put(self.art, "evil\x1b[31m/repo.json", json.dumps(repo_file("evil\x1b[31m", "private")))
        self.put("open-lib", " " * ((64 << 10) + 1))
        (self.art / "secret-app").mkdir()
        os.symlink(self.tmp / "elsewhere.json", self.art / "secret-app" / "repo.json")
        (self.tmp / "elsewhere.json").write_text(json.dumps(repo_file("secret-app", "private")))
        os.symlink(self.art / "gone-app", self.art / "linked-folder")
        code, out = self.ingest()
        self.assertEqual(code, 1, out)
        self.assertIn("rejected: gone-app/repo.json: repo gone-app is not on the watch list\n", out)
        self.assertIn("rejected: 'evil\\x1b[31m/repo.json': repo evil\\x1b[31m is not on the watch list\n", out)
        self.assertIn("rejected: open-lib/repo.json: file is larger than 64 KB\n", out)
        self.assertIn("rejected: secret-app/repo.json: is a symbolic link\n", out)
        self.assertNotIn("linked-folder", out)
        self.assertNotIn("\x1b", out)
        self.assertEqual(self.rows(), [])

    def test_an_answer_older_than_the_repos_latest_row_is_old_news_and_one_that_cannot_be_appended_in_order_is_refused(self):
        self.builder.visibility("2026-11-21T10:00:00Z", "secret-app", "acme/secret-app", "public").write(self.books)
        self.put("secret-app", repo_file("secret-app", "private", seen="2026-11-20T10:00:00Z"))
        code, out = self.ingest("--only", "visibility")
        self.assertEqual((code, out), (0, "visibility secret-app: unchanged (public)\n"))
        self.put("open-lib", repo_file("open-lib", "private", seen="2026-11-20T10:00:00Z"))
        code, out = self.ingest()
        self.assertEqual(code, 1, out)
        self.assertIn("rejected: open-lib/repo.json: seen 2026-11-20T10:00:00Z is not after the latest row of books/repos.csv (2026-11-21T10:00:00Z); fetch again\n", out)
        self.assertEqual(len(self.rows()), 1)


# ---------------------------------------------------------------------------
# leak-check
# ---------------------------------------------------------------------------

STEP_ONLY_HERE = "Run the secret migration"
JOB_ONLY_HERE = "deploy-to-staging-cluster"
SHARED_JOB = "build-release-artifacts"
SHARED_STEP = "Apply the staging manifests"
SECRET_TEST = "tests.test_vault.VaultTest.test_rotates_keys"
SECRET_LINK = link("acme/secret-app", 101)


def leak_books(extra=None) -> Builder:
    b = Builder(SECRET, OPEN)
    b.run("secret-app", "acme/secret-app", 101, SHA_SECRET, failing=[SECRET_TEST, "a.test_x"],
          jobs=[(JOB_ONLY_HERE, [SHARED_STEP, STEP_ONLY_HERE]), (SHARED_JOB, ["checkout"]), ("lint", ["checkout"])])
    b.run("open-lib", "acme/open-lib", 7, SHA_OPEN, failing=["tests.test_core.CoreTest.test_parse"], jobs=[(SHARED_JOB, [SHARED_STEP])])
    b.visibility("2026-11-18T10:00:00Z", "secret-app", "acme/secret-app", "private").visibility("2026-11-18T10:00:00Z", "open-lib", "acme/open-lib", "public")
    return b


class LeakCase(TempCase):
    def setUp(self):
        super().setUp()
        leak_books().write(self.books)
        self.files = self.tmp / "files"
        self.files.mkdir()

    def file(self, text, name: str = "pr.md") -> str:
        path = self.files / name
        path.write_bytes(text if isinstance(text, bytes) else text.encode())
        return str(path)

    def leak(self, text, *extra, name: str = "pr.md") -> tuple[int, str]:
        return tf.cli("leak-check", self.books, self.file(text, name), *extra)

    def kinds(self, text) -> list[tuple[str, str]]:
        """(kind, matched text) of every match in the text."""
        code, out = self.leak(text)
        self.assertIn(code, (0, 1), out)
        found = [line.split(": ", 2) for line in out.splitlines()[:-1]]
        return [(kind, hit) for _, kind, hit in found]

    final = "leak-check: {} matches in {} files; checked against 1 private repos (2 links, 1 commits, 1 tests, 1 job names, 1 step names)"


class LeakKindsTest(LeakCase):
    def test_each_kind_is_found_with_its_line_and_the_final_line_counts_what_was_checked(self):
        text = (f"Failed run {SECRET_LINK} today\nsee acme/secret-app now\nabbreviated {SHA_SECRET[:8]} here\n{SECRET_TEST} broke\n"
                f"{JOB_ONLY_HERE} is slow\n{STEP_ONLY_HERE} took long\nnothing here\n")
        code, out = self.leak(text)
        p = str(self.files / "pr.md")
        self.assertEqual(out, f"{p}:1: link: {SECRET_LINK}\n{p}:2: link: acme/secret-app\n{p}:3: commit: {SHA_SECRET[:8]}\n{p}:4: test: {SECRET_TEST}\n"
                              f"{p}:5: job: {JOB_ONLY_HERE}\n{p}:6: step: {STEP_ONLY_HERE}\n" + self.final.format(6, 1) + "\n")
        self.assertEqual(code, 1)

    def test_a_clean_file_passes_and_the_final_line_is_still_printed(self):
        self.assertEqual(self.leak("nothing of note: acme/open-lib and tests.test_core.CoreTest.test_parse and lint\n"),
                         (0, self.final.format(0, 1) + "\n"))

    def test_links_the_run_a_repo_url_an_unbooked_run_and_the_bare_slug_with_its_bounds(self):
        found = self.kinds("a https://github.com/acme/secret-app/pull/3\nb https://github.com/acme/secret-app/actions/runs/999/attempts/1\n"
                           "c git@github.com:acme/secret-app.git\nd ACME/Secret-App\ne in acme/secret-app.\nf acme/secret-app/src/x.py\n")
        self.assertEqual(found, [("link", "github.com/acme/secret-app"), ("link", "github.com/acme/secret-app"), ("link", "github.com:acme/secret-app"),
                                 ("link", "ACME/Secret-App"), ("link", "acme/secret-app"), ("link", "acme/secret-app")])
        for text in ("acme/secret-app-extra", "xacme/secret-app", "see/acme/secret-app", "acme/secret-app.txt", "acme/secret-apple", "acme/open-lib",
                     "https://github.com/acme/secret-app-extra/pull/1", "secret-app", "github.com/acme/open-lib"):
            self.assertEqual(self.kinds(text), [], text)

    def test_a_link_inside_a_longer_link_is_reported_once_and_the_longer_one_wins(self):
        b = leak_books()
        b.run("secret-app", "acme/secret-app", 12, "1" * 40)
        b.run("secret-app", "acme/secret-app", 1, "2" * 40)
        b.write(self.books)
        self.assertEqual(self.kinds(f"{link('acme/secret-app', 12)}\n"), [("link", link("acme/secret-app", 12))])

    def test_commits_are_whole_hex_tokens_of_eight_or_more_that_prefix_a_private_sha(self):
        for text, expect in [(SHA_SECRET[:7], []), (SHA_SECRET[:8], [("commit", SHA_SECRET[:8])]), (SHA_SECRET, [("commit", SHA_SECRET)]),
                             (f"({SHA_SECRET[:12]}).", [("commit", SHA_SECRET[:12])]), (SHA_SECRET[:8].upper(), [("commit", SHA_SECRET[:8].upper())]),
                             (f"x{SHA_SECRET[:10]}", []), (f"{SHA_SECRET[:10]}z", []), (SHA_SECRET + "a", []), (SHA_SECRET[:8] + "0" * 9 + "ff", []),
                             (SHA_OPEN, []), ("deadbeef" * 5, []), ("0" * 64, [])]:
            self.assertEqual(self.kinds(text), expect, text)

    def test_test_ids_match_exactly_from_twelve_characters_up(self):
        self.assertEqual(self.kinds(f"x{SECRET_TEST}y"), [("test", SECRET_TEST)])
        self.assertEqual(self.kinds("a.test_x"), [])  # booked, but too short to say anything
        self.assertEqual(self.kinds(SECRET_TEST[:-1]), [])
        self.assertEqual(self.kinds("tests.test_core.CoreTest.test_parse"), [])  # a public repo's

    def test_job_and_step_names_match_when_long_and_no_public_repo_has_them(self):
        self.assertEqual(self.kinds(f"{JOB_ONLY_HERE} {STEP_ONLY_HERE}"), [("job", JOB_ONLY_HERE), ("step", STEP_ONLY_HERE)])
        self.assertEqual(self.kinds(f"{SHARED_JOB} {SHARED_STEP} lint checkout"), [])
        self.assertEqual(self.kinds(JOB_ONLY_HERE.upper()), [])  # exact, case sensitive
        self.assertEqual(self.kinds(JOB_ONLY_HERE[:-1]), [])

    def test_a_job_name_a_public_repo_has_only_as_a_step_does_not_count_and_the_placeholder_never_does(self):
        b = leak_books()
        b.run("secret-app", "acme/secret-app", 2, "3" * 40, jobs=[("(unprintable name)", ["(unprintable name)"]), ("Release the build-things", ["x"])])
        b.run("open-lib", "acme/open-lib", 8, "4" * 40, jobs=[("lint", ["Release the build-things"])])
        b.write(self.books)
        self.assertEqual(self.kinds("(unprintable name) Release the build-things"), [])

    def test_bare_repo_names_and_numbers_are_not_looked_for(self):
        self.assertEqual(self.kinds("secret-app is 1000 ms slower, run 101, 3.12, 2026-11-10T10:00:00Z"), [])

    def test_a_match_on_a_later_line_is_reported_at_its_line_and_one_that_spans_lines_at_its_first(self):
        b = leak_books()
        b.run("secret-app", "acme/secret-app", 3, "6" * 40, failing=["tests.test_multi\nline_id_here"])
        b.write(self.books)
        code, out = self.leak("a\r\nb\n\nc tests.test_multi\nline_id_here d acme/secret-app\n")
        p = str(self.files / "pr.md")
        self.assertIn(f"{p}:4: test: tests.test_multi\\nline_id_here\n", out)
        self.assertIn(f"{p}:5: link: acme/secret-app\n", out)

    def test_the_same_match_twice_on_a_line_is_one_line(self):
        code, out = self.leak("acme/secret-app acme/secret-app\nacme/secret-app\n")
        self.assertEqual(out.count(": link: acme/secret-app\n"), 2)
        self.assertIn("2 matches in 1 files", out)


class LeakRuleTest(TempCase):
    def test_a_repo_is_public_only_when_every_row_says_public_and_the_set_is_every_repo_any_book_mentions(self):
        b = Builder(("pub-a", "acme/pub-a"))
        shas = {}
        for i, (repo, history) in enumerate({"pub-a": ["public"], "prv-b": ["private"], "int-c": ["internal"], "unk-d": ["unknown"],
                                            "flip-e": ["public", "private", "public"], "norow-f": [], "left-g": ["public"], "weird-h": ["public", "unknown"]}.items()):
            shas[repo] = f"{i + 1:x}" * 40
            b.run(repo, f"acme/{repo}", i + 1, shas[repo])
            for day, value in enumerate(history):
                b.visibility(f"2026-11-1{day}T10:00:00Z", repo, f"acme/{repo}", value)
        b.write(self.books)  # only pub-a is on the watch list: the rest are rows of repos no longer watched
        with unittest.mock.patch.object(sys, "stdin", io.TextIOWrapper(io.BytesIO(" ".join(shas.values()).encode()))):
            code, out = tf.cli("leak-check", self.books, "-")
        self.assertEqual(code, 1, out)
        hit = {line.split(": commit: ")[1] for line in out.splitlines() if ": commit: " in line}
        self.assertEqual(hit, {shas[r] for r in ("prv-b", "int-c", "unk-d", "flip-e", "norow-f", "weird-h")})
        self.assertIn("checked against 6 private repos (12 links, 6 commits, 0 tests, 0 job names, 0 step names)", out)

    def test_a_repo_whose_tests_are_not_recorded_has_no_test_id_to_find(self):
        Builder(SECRET).run("secret-app", "acme/secret-app", 1, SHA_SECRET).visibility(STAMP, "secret-app", "acme/secret-app", "private").write(self.books)
        path = self.tmp / "f.txt"
        path.write_text("tests.test_vault.VaultTest.test_rotates_keys\n")
        self.assertEqual(tf.cli("leak-check", self.books, path), (0, "leak-check: 0 matches in 1 files; checked against 1 private repos (2 links, 1 commits, 0 tests, 0 job names, 0 step names)\n"))

    def test_with_no_private_repo_the_final_line_is_printed_and_the_exit_is_0(self):
        Builder(OPEN).run("open-lib", "acme/open-lib", 7, SHA_OPEN).visibility(STAMP, "open-lib", "acme/open-lib", "public").write(self.books)
        path = self.tmp / "f.txt"
        path.write_text(f"{SHA_OPEN} acme/open-lib\n")
        self.assertEqual(tf.cli("leak-check", self.books, path),
                         (0, "leak-check: 0 matches in 1 files; checked against 0 private repos (0 links, 0 commits, 0 tests, 0 job names, 0 step names)\n"))


class LeakCommandTest(LeakCase):
    def test_without_repos_csv_nothing_can_be_called_public_so_it_is_a_usage_error(self):
        (self.books / quality.REPOS).unlink()
        code, out = self.leak("all clear")
        self.assertEqual(code, 2, out)
        self.assertIn("leak-check needs books/repos.csv: visibility is not booked, so no repo can be called public", out)
        self.assertNotIn("matches in", out)

    def test_books_that_fail_check_are_refused(self):
        (self.books / quality.REPOS).write_text("seen,repo,github,visibility\nyesterday,secret-app,acme/secret-app,private\n")
        code, out = self.leak("x")
        self.assertEqual(code, 2, out)
        self.assertIn("books/repos.csv:2: seen must look like", out)
        self.assertIn("1 problems; no leak-check against unchecked books", out)

    def test_usage_errors(self):
        self.assertEqual(tf.cli("leak-check", self.tmp / "none", "x")[0], 2)
        self.assertEqual(tf.cli("leak-check", self.books)[0], 2)  # no file
        with unittest.mock.patch.object(quality, "LEAK_MAX_FILES", 2):
            code, out = tf.cli("leak-check", self.books, "a", "b", "c")
        self.assertEqual(code, 2, out)

    def test_it_writes_nothing(self):
        before = {str(p): p.read_bytes() for p in self.books.rglob("*") if p.is_file()}
        self.leak(f"{SECRET_LINK}\n")
        self.assertEqual({str(p): p.read_bytes() for p in self.books.rglob("*") if p.is_file()}, before)

    def test_stdin_is_named_by_a_dash(self):
        with unittest.mock.patch.object(sys, "stdin", io.TextIOWrapper(io.BytesIO(b"x\nsee acme/secret-app\n"))):
            code, out = tf.cli("leak-check", self.books, "-")
        self.assertEqual(code, 1)
        self.assertEqual(out.splitlines()[0], "-:2: link: acme/secret-app")

    def test_several_files_are_listed_by_path_and_each_match_once(self):
        a, b = self.file("acme/secret-app\n", "b.md"), self.file(f"ok\n{SHA_SECRET[:9]}\n", "a.md")
        code, out = tf.cli("leak-check", self.books, a, b, a)
        self.assertEqual(out.splitlines()[:2], [f"{b}:2: commit: {SHA_SECRET[:9]}", f"{a}:1: link: acme/secret-app"])
        self.assertIn("2 matches in 2 files", out)

    def test_json_is_one_sorted_object_without_the_private_names(self):
        code, out = self.leak(f"{SECRET_LINK}\n{SHA_SECRET[:8]}\n", "--json")
        data = json.loads(out)
        p = str(self.files / "pr.md")
        self.assertEqual(code, 1)
        self.assertEqual(data, {"v": 1, "matches": [{"kind": "link", "line": 1, "path": p, "text": SECRET_LINK},
                                                    {"kind": "commit", "line": 2, "path": p, "text": SHA_SECRET[:8]}],
                               "files": 1, "private_repos": 1, "strings": {"links": 2, "commits": 1, "tests": 1, "jobs": 1, "steps": 1}})
        self.assertEqual(out, json.dumps(data, sort_keys=True, indent=2) + "\n")
        self.assertEqual(self.leak(f"{SECRET_LINK}\n{SHA_SECRET[:8]}\n", "--json")[1], out)
        clean = json.loads(self.leak("fine", "--json")[1])
        self.assertEqual((clean["matches"], clean["files"]), ([], 1))
        self.assertEqual(self.leak("fine", "--json")[0], 0)
        self.assertNotIn(SHA_SECRET, out.replace(SHA_SECRET[:8], ""))

    def test_an_unreadable_file_is_named_and_makes_the_exit_1(self):
        target = self.file("acme/secret-app")
        link_path = self.files / "link.md"
        os.symlink(target, link_path)
        big = self.file(b"a" * ((1 << 20) + 1), "big.md")
        missing = str(self.files / "missing.md")
        fifo = self.files / "pipe.md"
        os.mkfifo(fifo)
        code, out = tf.cli("leak-check", self.books, link_path, big, missing, self.files, fifo)
        self.assertEqual(code, 1, out)
        self.assertIn(f"{link_path}: unreadable: is a symbolic link, which this command does not follow\n", out)
        self.assertIn(f"{big}: unreadable: is larger than 1048576 bytes\n", out)
        self.assertIn(f"{missing}: unreadable: could not be read: No such file or directory\n", out)
        self.assertIn(f"{self.files}: unreadable: is not a regular file\n", out)
        self.assertIn(f"{fifo}: unreadable: is not a regular file\n", out)
        self.assertTrue(out.endswith("leak-check: 0 matches in 5 files; checked against 1 private repos (2 links, 1 commits, 1 tests, 1 job names, 1 step names)\n"), out)
        shown, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(shown), contextlib.redirect_stderr(errors):
            code = quality.main(["leak-check", str(self.books), str(big), "--json"])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(shown.getvalue())["matches"], [])
        self.assertEqual(errors.getvalue(), f"{big}: unreadable: is larger than 1048576 bytes\n")

    def test_a_file_of_exactly_one_megabyte_is_read(self):
        code, out = self.leak(b"a" * ((1 << 20) - 20) + b" acme/secret-app")
        self.assertEqual(code, 1, out)
        self.assertIn(": link: acme/secret-app\n", out)

    def test_text_from_the_books_and_from_the_command_line_is_escaped_and_capped(self):
        long_id = "ab\n" * 333 + "z"
        b = leak_books()
        b.run("secret-app", "acme/secret-app", 3, "7" * 40, failing=["tests.tab\there_and\nnewline", long_id])
        b.write(self.books)
        hostile = self.file(f"x tests.tab\there_and\nnewline\n{long_id}\n", "evil\x1b[31m.md")
        code, out = tf.cli("leak-check", self.books, hostile)
        self.assertEqual(code, 1, out)
        self.assertNotIn("\x1b", out)
        self.assertNotIn("\t", out)
        self.assertEqual(len(out.splitlines()), 3 + 0, out)
        lines = out.splitlines()
        self.assertTrue(lines[0].startswith(str(self.files) + "/evil\\x1b[31m.md:1: test: tests.tab\\there_and\\nnewline"), lines[0])
        long_line = [ln for ln in lines if "ab\\nab\\n" in ln][0]
        self.assertEqual(len(long_line.split(": test: ", 1)[1]), quality.MAX_CELL)
        self.assertTrue(long_line.endswith("..."))
        data = json.loads(tf.cli("leak-check", self.books, hostile, "--json")[1])
        self.assertEqual(data["matches"][0]["path"], str(self.files) + "/evil\\x1b[31m.md")


class LeakSpeedTest(TempCase):
    def test_a_big_file_against_twenty_thousand_ids_that_share_a_prefix_is_not_quadratic(self):
        ids = [f"tests.test_module_{i}.TestCase.test_method_{i}" for i in range(20_000)]
        b = Builder(SECRET)
        b.visibility(STAMP, "secret-app", "acme/secret-app", "private")
        for test_id in ids:
            b.weekly[("2026-W46", "secret-app", test_id)] = ["2026-W46", "secret-app", test_id, 1, 1, 10, 10]
        b.write(self.books)
        body = "".join(f"line {i} of the report: tests.test_module_{i * 7 % 20000}.TestCase.test_method_{i * 7 % 20000} failed in tests.test_module_x\n"
                       for i in range(9000))
        path = self.tmp / "big.txt"
        path.write_text(body[:1 << 20])
        self.assertGreater(path.stat().st_size, 900_000)
        started = time.monotonic()
        code, out = tf.cli("leak-check", self.books, path)
        took = time.monotonic() - started
        self.assertEqual(code, 1)
        self.assertIn(f"{len(set(i * 7 % 20000 for i in range(9000)))} matches in 1 files; checked against 1 private repos (1 links, 0 commits, 20000 tests", out)
        self.assertLess(took, 5.0)


if __name__ == "__main__":
    unittest.main()
