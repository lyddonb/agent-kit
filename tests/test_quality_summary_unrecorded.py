"""Tests for `quality.py summary` on repos with no test records, repo visibility and `--public-only`
(plugins/bstack/skills/qualitydirector/scripts/quality.py).

Every repo, test id, step name, sha and link here is made up. Books are written by hand (`Builder` of test_quality_visibility)
and nothing reads the network, the clock or sleeps. The tests under UnchangedOutputTest hold literal or derived expectations that
the script before this feature met too (run them with QUALITY_SCRIPT pointing at that script to see it).
"""
import copy
import json
import shutil
import unittest

import test_quality_fetch as tf
import test_quality_visibility as tv

quality = tf.quality
ROOT = tf.ROOT
W46, W47 = "2026-W46", "2026-W47"
OPEN, TOOL, SECRET, SVC = ("open-lib", "acme/open-lib"), ("open-tool", "acme/open-tool"), ("secret-app", "acme/secret-app"), ("secret-svc", "acme/secret-svc")
SHA = "0be11b0a1c2d3e4f5061728394a5b6c7d8e9f001"
SEALED_STEP = "Seal the vault ledger"
SEALED_TEST = "tests.test_vault.VaultTest.test_rotates_keys"
MONDAY, SUNDAY = "2026-11-16T00:00:00Z", "2026-11-15T23:59:50Z"  # W47 starts on the Monday


def jobs_only(b: tv.Builder, repo: str, slug: str, n: int, created: str, steps=("Checkout", "Build"), total="30000") -> tv.Builder:
    """A CI run of `repo` with job and step rows and no runs.csv row: a repo whose CI has no test recorder."""
    evidence = tv.link(slug, n)
    b.job_id += 1
    b.jobs.append([created, repo, SHA, "push", tv.WORKFLOW, "build", b.job_id, "success", "2000", total, "", evidence])
    b.steps.extend([created, repo, b.job_id, i, step, "success", 1000 * i, evidence] for i, step in enumerate(steps, 1))
    return b


def books_of(*, with_repos=True) -> tv.Builder:
    """W46: open-lib (public, recorded), open-tool (public, unrecorded), secret-app (private, recorded),
    secret-svc (no repos.csv row, so private, unrecorded)."""
    b = tv.Builder(OPEN, TOOL, SECRET, SVC)
    b.run("open-lib", "acme/open-lib", 1, SHA, jobs=[("build", ["Checkout", "Run tests"])])
    b.run("secret-app", "acme/secret-app", 2, SHA, failing=[SEALED_TEST], jobs=[("build", ["Checkout", "Run tests"])])
    jobs_only(b, "open-tool", "acme/open-tool", 3, "2026-11-10T10:00:00Z")
    jobs_only(b, "secret-svc", "acme/secret-svc", 4, "2026-11-10T11:00:00Z", steps=("Checkout", SEALED_STEP), total="90000")
    b.has_repos = with_repos
    if with_repos:
        b.visibility(tv.STAMP, "open-lib", "acme/open-lib", "public").visibility(tv.STAMP, "open-tool", "acme/open-tool", "public")
        b.visibility(tv.STAMP, "secret-app", "acme/secret-app", "private")
    return b


class Case(tv.TempCase):
    def write(self, b: tv.Builder, **kw) -> None:
        for rel in (quality.JOBS, quality.STEPS, quality.REPOS):  # a rewrite must not keep a file the new books lack
            (self.books / rel).unlink(missing_ok=True)
        b.write(self.books, **{"repos": getattr(b, "has_repos", True), **kw})

    def summary(self, *extra) -> tuple[int, str]:
        return tf.cli("summary", self.books, *extra)

    def result(self, *extra) -> dict:
        code, out = self.summary("--json", *extra)
        self.assertEqual(code, 0, out)
        return json.loads(out)


class UnchangedOutputTest(Case):
    def test_books_with_neither_the_job_books_nor_repos_csv_print_what_they_always_printed(self):
        shutil.copytree(tf.ROOT / "tests/fixtures/quality/books", self.books / "books")
        self.assertEqual(self.summary("--json"), (0, (ROOT / "tests/fixtures/quality-summary.json").read_text()))
        out = self.summary("--json")[1]
        for key in ("recorded", "visibility", "public_only", "lifecycle"):
            self.assertNotIn(key, out)
        self.assertNotIn("private", self.summary()[1])

    def test_job_books_where_every_repo_with_jobs_has_runs_only_add_the_recorded_key(self):
        b = books_of(with_repos=False)
        b.jobs = [j for j in b.jobs if j[1] in ("open-lib", "secret-app")]
        b.steps = [s for s in b.steps if s[1] in ("open-lib", "secret-app")]
        self.write(b)
        adopted = self.result()
        self.assertEqual({r["recorded"] for r in adopted["repos"].values()}, {True})
        plain = tv.Builder(OPEN, TOOL, SECRET, SVC)
        plain.runs, plain.failures, plain.weekly, plain.has_repos = b.runs, b.failures, b.weekly, False
        self.write(plain, jobs=False)
        before = self.result()
        for r in adopted["repos"].values():
            self.assertIsNotNone(r.pop("lifecycle"))
            del r["recorded"]
        self.assertEqual(adopted, before)

    def test_the_text_of_such_books_only_gains_lifecycle_lines(self):
        b = books_of(with_repos=False)
        b.jobs, b.steps = b.jobs[:2], b.steps[:4]
        self.write(b)
        with_jobs = self.summary()[1].splitlines()
        self.write(b, jobs=False)
        plain = self.summary()[1].splitlines()
        self.assertEqual([l for l in with_jobs if not l.startswith(("  lifecycle:", "  outside the suite:", "  slowest step:"))], plain)
        self.assertNotIn("private", "\n".join(with_jobs))


class UnrecordedRepoTest(Case):
    def test_a_repo_with_job_rows_and_no_test_records_is_listed_with_exactly_its_lifecycle(self):
        self.write(books_of(with_repos=False))
        repos = self.result()["repos"]
        self.assertEqual(list(repos), ["open-lib", "open-tool", "secret-app", "secret-svc"])
        self.assertEqual(repos["open-tool"], {"recorded": False, "lifecycle": {
            "billed_ms": 30000, "failed_steps": [], "job_ms": {"median": 30000, "p95": 30000}, "jobs": 1, "jobs_skipped": 0,
            "jobs_untimed": 0, "queue_ms": {"max": 2000, "median": 2000, "p95": 2000}, "resolution_ms": 1000,
            "run_ms": {"median": 32000, "p95": 32000}, "runs": 1,
            "slowest_steps": [{"median": 2000, "p95": 2000, "step": "Build", "steps": 1},
                              {"median": 1000, "p95": 1000, "step": "Checkout", "steps": 1}],
            "with_suite": {"job_ms": 0, "outside_suite_ms": 0, "runs": 0, "runs_floored": 0, "suite_ms": 0}}})
        self.assertTrue(repos["open-lib"]["recorded"])
        self.assertIn("suite_ms", repos["open-lib"])

    def test_an_unrecorded_repo_has_no_test_side_key_and_adds_no_top_level_number(self):
        self.write(books_of())
        result = self.result()
        self.assertEqual(sorted(result["repos"]["open-tool"]), ["lifecycle", "recorded", "visibility"])
        self.assertTrue(all(t["repo"] in ("open-lib", "secret-app") for t in result["slowest_tests"]))

    def test_a_repo_whose_runs_are_in_another_week_is_not_listed(self):
        self.write(books_of(with_repos=False))
        self.assertNotIn("open-tool", self.result("--week", W47)["repos"])
        b = books_of(with_repos=False)
        jobs_only(b, "open-tool", "acme/open-tool", 5, MONDAY)
        self.write(b)
        self.assertEqual(self.result("--week", W47)["repos"]["open-tool"]["lifecycle"]["runs"], 1)
        self.assertEqual(self.result("--week", W46)["repos"]["open-tool"]["lifecycle"]["runs"], 1)

    def test_a_run_that_straddles_a_week_boundary_is_listed_in_its_earliest_jobs_week_only(self):
        b = books_of(with_repos=False)
        jobs_only(b, "open-tool", "acme/open-tool", 6, SUNDAY)
        b.jobs.append([MONDAY, "open-tool", SHA, "push", tv.WORKFLOW, "late", 99, "success", "0", "5000", "", tv.link("acme/open-tool", 6)])
        b.jobs = [j for j in b.jobs if not (j[1] == "open-tool" and j[-1] == tv.link("acme/open-tool", 3))]
        b.steps = [s for s in b.steps if not (s[1] == "open-tool" and s[-1] == tv.link("acme/open-tool", 3))]
        self.write(b)
        self.assertEqual(self.result("--week", W46)["repos"]["open-tool"]["lifecycle"]["jobs"], 2)
        self.assertNotIn("open-tool", self.result("--week", W47)["repos"])

    def test_unrecorded_means_no_test_record_started_this_week_even_for_a_run_recorded_in_the_next(self):
        """The run's first job was created on Sunday and its test record started on Monday: in the Sunday week the repo is
        unrecorded, and in the Monday week it is recorded with no lifecycle."""
        b = tv.Builder(OPEN)
        b.run("open-lib", "acme/open-lib", 1, SHA, jobs=[("build", ["Checkout", "Run tests"])])
        b.runs[-1][0] = MONDAY
        for job in b.jobs:
            job[0] = SUNDAY
        for step in b.steps:
            step[0] = SUNDAY
        self.write(b)
        sunday_week = self.result("--week", W46)["repos"]["open-lib"]
        self.assertIs(sunday_week["recorded"], False)
        self.assertEqual(sunday_week["lifecycle"]["runs"], 1)
        monday_week = self.result("--week", W47)["repos"]["open-lib"]
        self.assertIs(monday_week["recorded"], True)
        self.assertIsNone(monday_week["lifecycle"])

    def test_a_repo_with_run_rows_this_week_and_job_rows_only_in_another_is_recorded_with_a_null_lifecycle(self):
        b = tv.Builder(OPEN, TOOL)
        b.run("open-lib", "acme/open-lib", 1, SHA)
        jobs_only(b, "open-lib", "acme/open-lib", 7, "2026-11-02T10:00:00Z")
        self.write(b)
        entry = self.result()["repos"]["open-lib"]
        self.assertEqual((entry["recorded"], entry["lifecycle"]), (True, None))

    def test_the_text_says_so_and_prints_the_lifecycle_lines(self):
        self.write(books_of())
        code, text = self.summary()
        self.assertEqual(code, 0, text)
        lines = text.splitlines()
        i = lines.index("open-tool: no test record started this week")
        self.assertTrue(lines[i + 1].startswith("  lifecycle: 1 runs, 1 jobs"), lines[i + 1])
        self.assertEqual(lines[i + 3], '  slowest step: "Build" median 2000 ms over 1 steps')
        j = lines.index("secret-svc (private): no test record started this week")
        self.assertEqual(lines[j + 3], f'  slowest step: "{SEALED_STEP}" median 2000 ms over 1 steps')
        self.assertTrue(any(l.startswith("secret-app (private): 1 runs") for l in lines))
        self.assertTrue(any(l.startswith("open-lib: 1 runs") for l in lines))

    def test_the_json_is_the_same_bytes_every_time_with_integers_only(self):
        self.write(books_of())
        for extra in ((), ("--public-only",)):
            first, second = self.summary("--json", *extra)[1], self.summary("--json", *extra)[1]
            self.assertEqual(first, second)
            self.assertEqual(first, json.dumps(json.loads(first), indent=2, sort_keys=True) + "\n")

            def walk(value):
                if isinstance(value, dict):
                    for v in value.values():
                        walk(v)
                elif isinstance(value, list):
                    for v in value:
                        walk(v)
                else:
                    self.assertIn(type(value), (int, str, bool, type(None)), value)
            walk(json.loads(first))


class VisibilityTest(Case):
    def test_every_listed_repo_has_a_visibility_and_no_row_means_private(self):
        self.write(books_of())
        got = {name: r["visibility"] for name, r in self.result()["repos"].items()}
        self.assertEqual(got, {"open-lib": "public", "open-tool": "public", "secret-app": "private", "secret-svc": "private"})

    def test_without_repos_csv_the_key_is_absent_everywhere(self):
        self.write(books_of(with_repos=False))
        code, out = self.summary("--json")
        self.assertNotIn("visibility", out)
        self.assertNotIn("(private)", self.summary()[1])

    def test_the_rule_is_private_repos_of_the_books_not_a_second_one(self):
        self.write(books_of())
        private = quality.private_repos(quality.load(str(self.books)))
        self.assertEqual(private, {"secret-app", "secret-svc"})
        self.assertEqual({n for n, r in self.result()["repos"].items() if r["visibility"] == "private"}, private)


class PublicOnlyTest(Case):
    def test_it_needs_repos_csv(self):
        self.write(books_of(with_repos=False))
        code, out = self.summary("--public-only")
        self.assertEqual(code, 2)
        self.assertIn("visibility is not booked", out)
        self.assertEqual(self.summary("--public-only", "--json")[0], 2)

    def test_private_repos_are_left_out_of_repos_and_of_slowest_tests(self):
        b = books_of()
        b.weekly[("2026-W46", "open-lib", "tests.test_open.OpenTest.test_it")] = ["2026-W46", "open-lib", "tests.test_open.OpenTest.test_it", 1, 1, 10, 10]
        self.write(b)
        full = self.result()
        self.assertEqual({t["repo"] for t in full["slowest_tests"]}, {"open-lib", "secret-app"})
        result = self.result("--public-only")
        self.assertEqual(list(result["repos"]), ["open-lib", "open-tool"])
        self.assertEqual({t["repo"] for t in result["slowest_tests"]}, {"open-lib"})
        self.assertIs(result["public_only"], True)
        for name in ("open-lib", "open-tool"):
            self.assertEqual(result["repos"][name], full["repos"][name])

    def test_generated_from_counts_only_public_rows_and_skills_is_omitted(self):
        b = books_of()
        self.write(b)
        skills = self.books / quality.SKILLS
        skills.write_text(",".join(quality.SKILLS_SCHEMA) + "\n")
        full, public = self.result(), self.result("--public-only")
        self.assertEqual(full["generated_from"], {"failures": 1, "runs": 2, "weekly_rows": 1})
        self.assertEqual(public["generated_from"], {"failures": 0, "runs": 1, "weekly_rows": 0})
        self.assertIn("skills", full)
        self.assertNotIn("skills", public)
        self.assertNotIn("skills:", self.summary("--public-only")[1])

    def test_no_private_string_appears_in_json_or_text(self):
        self.write(books_of())
        for extra in (("--json",), ()):
            code, out = self.summary("--public-only", *extra)
            self.assertEqual(code, 0, out)
            for private in ("secret", SEALED_STEP, SEALED_TEST, "vault", "Vault", "acme/secret", "(private)"):
                self.assertNotIn(private, out)
        full = self.summary("--json")[1] + self.summary()[1]
        for private in ("secret-app", "secret-svc", SEALED_STEP, SEALED_TEST):
            self.assertIn(private, full)

    def test_the_week_default_does_not_move_when_private_repos_are_dropped(self):
        b = tv.Builder(OPEN, SECRET)
        b.run("open-lib", "acme/open-lib", 1, SHA)
        b.run("secret-app", "acme/secret-app", 2, SHA)
        b.runs[1][0] = MONDAY
        b.visibility(tv.STAMP, "open-lib", "acme/open-lib", "public").visibility(tv.STAMP, "secret-app", "acme/secret-app", "private")
        self.write(b)
        self.assertEqual(self.result()["week"], W47)
        public = self.result("--public-only")
        self.assertEqual((public["week"], public["repos"]), (W47, {}))

    def test_books_that_fail_check_print_no_problem_line_because_one_can_quote_a_private_repo(self):
        b = books_of()
        b.failures.append(["2026-11-10T12:00:00Z", "secret-app", SHA, "3.12", SEALED_TEST, "fail", tv.link("acme/secret-app", 55)])
        self.write(b)
        code, out = self.summary("--public-only", "--json")
        self.assertEqual(code, 1)
        self.assertEqual(out, "1 problems; no summary from unchecked books (run check to read them: --public-only prints none)\n")
        code, out = self.summary("--json")  # without the flag the line is printed, as before
        self.assertEqual(code, 1)
        self.assertIn("acme/secret-app/actions/runs/55", out)

    def test_the_text_starts_with_a_line_that_says_so(self):
        self.write(books_of())
        lines = self.summary("--public-only")[1].splitlines()
        self.assertEqual(lines[0], "public repos only")
        self.assertTrue(lines[1].startswith("quality summary for 2026-W46"))
        self.assertNotEqual(self.summary()[1].splitlines()[0], "public repos only")
        self.assertNotIn("public_only", self.summary("--json")[1])


if __name__ == "__main__":
    unittest.main()
