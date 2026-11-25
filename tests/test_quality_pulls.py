"""Tests for the pulls book (`books/pulls.csv`): how long each merged pull request was open and where the time went
(plugins/bstack/skills/qualitydirector/scripts/quality.py).

Every repo, sha and link here is made up. `fetch` is driven through the fake `gh` of test_quality_fetch with --today set.
PullCycleTest holds the arithmetic on plain numbers; UnadoptedPullsTest holds what books without the file must still do:
the same calls, files and output as before the book existed.
"""
import json
import re
import unittest
import unittest.mock

import test_quality_fetch as tf
import test_quality_ingest as ti
import test_quality_local_ci as tl
import test_quality_visibility as tv

quality = tf.quality
OPEN, SECRET = tv.OPEN, tv.SECRET
SHA_A, SHA_B, SHA_C = "a" * 40, "b" * 40, "c" * 40
SLUG = "acme/open-lib"
DAY = "2026-11-12"


def at(clock: str, day: str = DAY) -> str:
    return f"{day}T{clock}:00Z"


def sec(clock: str, day: str = DAY) -> int:
    return quality.epoch_of(at(clock, day))


def minutes(n: int) -> int:
    return n * 60


def pull_link(slug: str, n: int) -> str:
    return f"https://github.com/{slug}/pull/{n}"


class PullCycleTest(unittest.TestCase):
    def cycle(self, opened: str, merged: str, intervals: list[tuple[str, str]], head: list[tuple[str, str]] | None = None,
              ready_events: tuple[str, ...] = ()) -> dict:
        span = lambda pairs: [(sec(a), sec(b)) for a, b in pairs]
        return quality.pull_cycle(sec(opened), sec(merged), [sec(e) for e in ready_events], span(intervals),
                                  span(intervals if head is None else head))

    def test_overlapping_intervals_count_once_and_the_wait_starts_when_the_head_finished(self):
        got = self.cycle("10:00", "12:00", [("10:05", "10:20"), ("10:15", "10:40")])
        self.assertEqual((got["ci"], got["wait"], got["head_done"]), (minutes(35), minutes(80), sec("10:40")))
        self.assertEqual(minutes(120) - got["ci"] - got["wait"], minutes(5), "the rest is rework")

    def test_a_check_that_ends_after_the_merge_is_clipped_for_ci_and_ends_the_wait_at_the_merge(self):
        got = self.cycle("10:00", "12:00", [("11:50", "12:30")])
        self.assertEqual((got["ci"], got["wait"], got["head_done"]), (minutes(10), 0, sec("12:30")))

    def test_a_check_that_never_completed_runs_to_the_merge(self):
        runs = [{"started_at": at("11:00"), "completed_at": None}, {"started_at": None, "completed_at": None}]
        self.assertEqual(quality.check_intervals(runs, sec("12:00")), [(sec("11:00"), sec("12:00"))])

    def test_a_check_or_status_that_starts_after_the_merge_is_not_an_interval_so_the_wait_stands(self):
        runs = [{"started_at": at("10:05"), "completed_at": at("10:20")},
                {"started_at": at("12:10"), "completed_at": at("12:15")}]
        statuses = [{"context": "ci", "state": "pending", "created_at": at("12:20"), "id": 1},
                    {"context": "ci", "state": "success", "created_at": at("12:30"), "id": 2}]
        intervals = quality.check_intervals(runs, sec("12:00")) + quality.status_intervals(statuses, sec("12:00"))
        self.assertEqual(intervals, [(sec("10:05"), sec("10:20"))], "a re-run after the merge must not move head_done past it")
        got = quality.pull_cycle(sec("10:00"), sec("12:00"), [], intervals, intervals)
        self.assertEqual((got["ci"], got["wait"], got["head_done"]), (minutes(15), minutes(100), sec("10:20")))

    def test_a_trailing_pending_status_runs_to_the_merge(self):
        statuses = [{"context": "ci", "state": "pending", "created_at": at("11:00"), "id": 1}]
        intervals = quality.status_intervals(statuses, sec("12:00"))
        self.assertEqual(intervals, [(sec("11:00"), sec("12:00"))])
        got = quality.pull_cycle(sec("10:00"), sec("12:00"), [], intervals, intervals)
        self.assertEqual((got["ci"], got["wait"], got["head_done"]), (minutes(60), 0, sec("12:00")))

    def test_no_checks_means_everything_after_ready_is_wait(self):
        got = quality.pull_cycle(sec("10:00"), sec("12:00"), [], [], [])
        self.assertEqual((got["ci"], got["wait"], got["head_done"]), (0, minutes(120), 0))

    def test_a_draft_that_turned_ready_counts_from_ready_and_its_earlier_checks_are_rework(self):
        got = self.cycle("10:00", "12:00", [("10:30", "10:50")], ready_events=("11:00",))
        self.assertEqual((got["ready"], got["ci"], got["wait"]), (sec("11:00"), 0, minutes(60)))

    def test_the_latest_ready_event_before_the_merge_wins_and_one_after_it_is_ignored(self):
        got = self.cycle("10:00", "12:00", [], ready_events=("10:30", "11:00", "13:00"))
        self.assertEqual(got["ready"], sec("11:00"))
        got = self.cycle("10:00", "12:00", [], ready_events=("09:00",))
        self.assertEqual(got["ready"], sec("10:00"), "never before it was opened")

    def test_a_run_on_a_superseded_commit_still_running_after_the_head_finished_is_ci_not_wait(self):
        got = self.cycle("10:00", "12:00", [("10:00", "11:10"), ("10:30", "10:40")], head=[("10:30", "10:40")])
        self.assertEqual((got["ci"], got["wait"], got["head_done"]), (minutes(70), minutes(50), sec("10:40")))

    def test_a_pull_request_merged_before_it_was_opened_is_refused(self):
        with self.assertRaisesRegex(quality.Rejected, "merged before it was opened"):
            quality.pull_cycle(sec("12:00"), sec("10:00"), [], [], [])

    def test_the_three_parts_never_add_up_to_more_than_the_open_time(self):
        cases = [[("10:00", "12:00")], [("09:00", "13:00")], [("11:59", "12:01")], [("10:00", "10:00")], []]
        for intervals in cases:
            got = self.cycle("10:00", "12:00", intervals)
            self.assertLessEqual(got["ci"] + got["wait"], minutes(120), intervals)

    def test_status_contexts_are_read_in_time_order_each_on_its_own(self):
        statuses = [{"context": "a", "state": "success", "created_at": at("10:30"), "id": 9},
                    {"context": "a", "state": "pending", "created_at": at("10:10"), "id": 8},
                    {"context": "a", "state": "pending", "created_at": at("10:20"), "id": 10},
                    {"context": "b", "state": "success", "created_at": at("10:05"), "id": 11},
                    {"context": "b", "state": "pending", "created_at": at("10:40"), "id": 12},
                    {"context": "b", "state": "failure", "created_at": at("10:45"), "id": 13}]
        self.assertEqual(sorted(quality.status_intervals(statuses, sec("12:00"))),
                         [(sec("10:10"), sec("10:30")), (sec("10:40"), sec("10:45"))],
                         "a repeated pending keeps the first start; a result with no pending before it is no interval")

    def test_an_answer_that_is_not_a_time_is_refused(self):
        with self.assertRaisesRegex(quality.Rejected, "started_at is not a usable time"):
            quality.check_intervals([{"started_at": "yesterday"}], 0)
        with self.assertRaisesRegex(quality.Rejected, "no usable context or state"):
            quality.status_intervals([{"state": "pending"}], 0)


def pull_obj(number: int, created: str, merged: str | None, sha: str = SHA_B, updated: str | None = None) -> dict:
    return {"number": number, "created_at": created, "merged_at": merged, "updated_at": updated or merged or created,
            "head": {"sha": sha}}


def check_run(started: str | None, completed: str | None, name: str = "build") -> dict:
    return {"name": name, "started_at": started, "completed_at": completed}


def q(query: str) -> str:
    return "__q__" + re.sub(r"[^A-Za-z0-9._-]", "_", query)


LIST_QUERY = "state=closed&sort=updated&direction=desc&per_page=100&page="


class FetchPullsBase(tv.FetchBase):
    def setUp(self):
        super().setUp()
        tv.Builder(OPEN).write(self.books, repos=False, jobs=False)
        tv.write_csv(self.books / quality.PULLS, quality.PULLS_SCHEMA, [])
        self.listing(SLUG)

    def pulls_page(self, page: int, pulls: list[dict]) -> None:
        self.put(f"repos/{SLUG}/pulls{q(LIST_QUERY + str(page))}", pulls)

    def serve_pull(self, number: int, commits: list[str], checks: dict[str, list[dict]], statuses: dict[str, list[dict]] | None = None,
                   timeline: list[dict] | None = None) -> None:
        self.put(f"repos/{SLUG}/pulls/{number}/commits{q('per_page=100')}", [{"sha": sha} for sha in commits])
        for sha in commits:
            self.put(f"repos/{SLUG}/commits/{sha}/check-runs{q('filter=all&per_page=100')}",
                     {"total_count": len(checks.get(sha, [])), "check_runs": checks.get(sha, [])})
            self.put(f"repos/{SLUG}/commits/{sha}/statuses{q('per_page=100')}", (statuses or {}).get(sha, []))
        self.put(f"repos/{SLUG}/issues/{number}/timeline{q('per_page=100')}", timeline or [])

    def pull_file(self, number: int, repo: str = "open-lib") -> dict:
        return json.loads((self.out / repo / "pulls" / f"{number}.json").read_text())


class FetchPullsTest(FetchPullsBase):
    def serve_seven(self) -> None:
        self.serve_pull(7, [SHA_A, SHA_B],
                        {SHA_A: [check_run(at("10:05"), at("10:20"))],
                         SHA_B: [check_run(at("10:30"), at("10:50")), check_run(None, None, "queued")]},
                        {SHA_B: [{"context": "local-ci", "state": "success", "created_at": at("11:10"), "id": 2},
                                 {"context": "local-ci", "state": "pending", "created_at": at("10:35"), "id": 1}]},
                        [{"event": "commented"}, {"event": "ready_for_review", "created_at": at("10:01")},
                         {"event": "head_ref_force_pushed", "created_at": at("10:25")},
                         {"event": "head_ref_force_pushed", "created_at": at("10:45")}])

    def test_a_merged_pull_request_is_read_from_its_commits_checks_statuses_and_timeline(self):
        self.pulls_page(1, [pull_obj(8, at("09:00", "2026-11-11"), None),
                            pull_obj(7, at("10:00"), at("12:00")),
                            pull_obj(5, at("09:00", "2026-11-01"), at("09:30", "2026-11-01"), updated=at("09:30", "2026-11-01"))])
        self.serve_seven()
        code, out = self.fetch()
        self.assertEqual(code, 0, out)
        self.assertEqual(self.pull_file(7), {
            "v": 1, "github": SLUG, "repo": "open-lib", "merged": at("12:00"), "number": 7, "opened": at("10:00"), "ready": at("10:01"),
            "head_ci_done": at("11:10"), "ci_ms": minutes(55) * 1000, "wait_ms": minutes(50) * 1000, "shas": 2, "checks": 3,
            "force_pushes": 2, "evidence": pull_link(SLUG, 7)})
        self.assertEqual(sorted(p.name for p in (self.out / "open-lib" / "pulls").iterdir()), ["7.json"])
        self.assertIn(f"  pull 7: merged {at('12:00')}, ci 3300000 ms, wait 3000000 ms, 2 commits, 3 checks, 2 force pushes\n", out)
        self.assertTrue(out.endswith("; 1 merged pull requests read; 0 failed\n"), out)
        endpoints = self.endpoints()
        self.assertEqual(endpoints.count(f"repos/{SLUG}/pulls"), 1)
        self.assertNotIn(f"repos/{SLUG}/pulls/8/commits", endpoints)
        self.assertNotIn(f"repos/{SLUG}/pulls/5/commits", endpoints)

    def test_a_head_with_no_checks_has_an_empty_head_ci_done(self):
        self.pulls_page(1, [pull_obj(7, at("10:00"), at("12:00"))])
        self.serve_pull(7, [SHA_B], {})
        code, out = self.fetch()
        self.assertEqual(code, 0, out)
        got = self.pull_file(7)
        self.assertEqual((got["head_ci_done"], got["ci_ms"], got["wait_ms"], got["checks"]), ("", 0, minutes(120) * 1000, 0))

    def test_listing_pages_until_one_was_last_updated_before_since_and_no_further(self):
        recent = [pull_obj(100 + i, at("09:00", "2026-11-11"), None, updated=at("09:00", "2026-11-13")) for i in range(100)]
        old = [pull_obj(300 + i, at("09:00", "2026-10-01"), None, updated=at("09:00", "2026-11-01")) for i in range(99)]
        self.pulls_page(1, recent)
        self.pulls_page(2, [pull_obj(7, at("10:00"), at("12:00"), updated=at("12:00"))] + old)
        self.serve_pull(7, [SHA_B], {})
        code, out = self.fetch()
        self.assertEqual(code, 0, out)
        self.assertEqual(self.endpoints().count(f"repos/{SLUG}/pulls"), 2, "the third page is never asked for")
        self.assertEqual([p.name for p in (self.out / "open-lib" / "pulls").iterdir()], ["7.json"])

    def test_booked_pull_requests_are_not_read_again_and_since_comes_from_the_latest_merge(self):
        tv.write_csv(self.books / quality.PULLS, quality.PULLS_SCHEMA,
                     [[at("12:00"), "open-lib", 7, at("10:00"), at("10:00"), "", 0, minutes(120) * 1000, 1, 0, 0, pull_link(SLUG, 7)]])
        self.pulls_page(1, [pull_obj(9, at("09:00", "2026-11-10"), at("09:30", "2026-11-10")),
                            pull_obj(7, at("10:00"), at("12:00")),
                            pull_obj(6, at("09:00", "2026-11-08"), at("09:30", "2026-11-08"), updated=at("09:30", "2026-11-08"))])
        self.serve_pull(9, [SHA_B], {})
        code, out = self.fetch()
        self.assertEqual(code, 0, out)
        self.assertEqual([p.name for p in (self.out / "open-lib" / "pulls").iterdir()], ["9.json"])
        self.assertNotIn(f"repos/{SLUG}/pulls/7/commits", self.endpoints())
        self.assertEqual(quality._latest_merged(quality.load(str(self.books)), "open-lib"), "2026-11-09")

    def test_a_pull_request_that_cannot_be_read_fails_only_itself(self):
        self.pulls_page(1, [pull_obj(7, at("10:00"), at("12:00"), SHA_C), pull_obj(8, at("10:00"), at("12:30"))])
        self.serve_pull(8, [SHA_B], {})
        self.put(f"repos/{SLUG}/pulls/7/commits{q('per_page=100')}", [{"sha": SHA_C}])
        code, out = self.fetch()
        self.assertEqual(code, 1, out)
        self.assertIn("  FAILED pull 7: gh api repos/acme/open-lib/commits/", out)
        self.assertEqual([p.name for p in (self.out / "open-lib" / "pulls").iterdir()], ["8.json"])
        self.assertIn("; 1 merged pull requests read; 1 failed\n", out)

    def test_a_pull_request_the_api_gave_no_usable_time_for_fails_only_itself(self):
        self.pulls_page(1, [pull_obj(7, "yesterday", at("12:00")), pull_obj(8, at("10:00"), at("12:30"))])
        self.serve_pull(8, [SHA_B], {})
        code, out = self.fetch()
        self.assertEqual(code, 1, out)
        self.assertIn("  FAILED pull 7: created_at is not a usable time ('yesterday')\n", out)
        self.assertEqual([p.name for p in (self.out / "open-lib" / "pulls").iterdir()], ["8.json"])

    def test_a_failed_listing_fails_the_repo_and_nothing_else(self):
        code, out = self.fetch()
        self.assertEqual(code, 1, out)
        self.assertIn("  FAILED pulls: gh api repos/acme/open-lib/pulls failed", out)

    def test_too_many_pull_requests_are_read_oldest_merged_first_and_the_rest_left_for_later(self):
        self.pulls_page(1, [pull_obj(9, at("10:00"), at("12:30")), pull_obj(7, at("10:00"), at("12:00"))])
        self.serve_pull(7, [SHA_B], {})
        with unittest.mock.patch.object(quality, "MAX_PULLS_PER_FETCH", 1):
            code, out = self.fetch()
        self.assertEqual(code, 0, out)
        self.assertIn("  pulls: 2 to read; reading the oldest 1, the rest on a later fetch\n", out)
        self.assertEqual([p.name for p in (self.out / "open-lib" / "pulls").iterdir()], ["7.json"])

    def test_a_window_needing_more_pages_than_the_bound_is_refused(self):
        self.pulls_page(1, [pull_obj(100 + i, at("09:00", "2026-11-11"), None, updated=at("09:00", "2026-11-13")) for i in range(100)])
        self.pulls_page(2, [])
        with unittest.mock.patch.object(quality, "MAX_PULL_PAGES", 1):
            code, out = self.fetch()
        self.assertEqual(code, 1, out)
        self.assertIn("more than 1 pages of pull requests since 2026-11-08; pass a later --since", out)

    def test_every_page_of_the_commits_is_read(self):
        self.pulls_page(1, [pull_obj(7, at("10:00"), at("12:00"))])
        self.serve_pull(7, [SHA_B], {})
        self.put(f"repos/{SLUG}/pulls/7/commits{q('per_page=100')}", json.dumps([{"sha": SHA_A}]) + json.dumps([{"sha": SHA_B}]))
        self.put(f"repos/{SLUG}/commits/{SHA_A}/check-runs{q('filter=all&per_page=100')}", {"check_runs": []})
        self.put(f"repos/{SLUG}/commits/{SHA_A}/statuses{q('per_page=100')}", [])
        code, out = self.fetch()
        self.assertEqual(code, 0, out)
        self.assertEqual(self.pull_file(7)["shas"], 2)


class FetchLocalPullsTest(tl.LocalBase):
    def test_a_local_ci_repo_gets_its_pull_requests_from_the_same_api(self):
        tv.write_csv(self.books / quality.PULLS, quality.PULLS_SCHEMA, [])
        self.serve()
        day = "2026-11-14"
        self.put(f"repos/{tl.SLUG}/pulls{q(LIST_QUERY + '1')}", [pull_obj(7, at("10:00", day), at("12:00", day))])
        self.put(f"repos/{tl.SLUG}/pulls/7/commits{q('per_page=100')}", [{"sha": SHA_B}])
        self.put(f"repos/{tl.SLUG}/commits/{SHA_B}/check-runs{q('filter=all&per_page=100')}", {"check_runs": []})
        self.put(f"repos/{tl.SLUG}/commits/{SHA_B}/statuses{q('per_page=100')}",
                 [{"context": "local-ci", "state": "success", "created_at": at("10:20", day), "id": 2},
                  {"context": "local-ci", "state": "pending", "created_at": at("10:10", day), "id": 1}])
        self.put(f"repos/{tl.SLUG}/issues/7/timeline{q('per_page=100')}", [])
        code, out = self.fetch()
        self.assertEqual(code, 0, out)
        got = json.loads((self.out / tl.REPO / "pulls" / "7.json").read_text())
        self.assertEqual((got["ci_ms"], got["wait_ms"], got["evidence"]), (minutes(10) * 1000, minutes(100) * 1000, pull_link(tl.SLUG, 7)))


class UnadoptedPullsTest(tv.FetchBase):
    def test_fetch_without_the_book_makes_no_pull_call_and_prints_what_it_did_before(self):
        tv.Builder(OPEN).write(self.books, repos=False, jobs=False)
        self.listing(SLUG)
        code, out = self.fetch()
        self.assertEqual((code, out), (0, "open-lib (acme/open-lib, ci): runs created since 2026-11-08\n"
                                          "fetched 0 runs (0 artifacts); listed 0; skipped 0 forks, 0 pushes to a non-default branch, "
                                          "0 already booked, 0 without test-results artifacts; 0 failed\n"))
        self.assertEqual(self.endpoints(), ["repos/acme/open-lib/actions/runs"])

    def test_summary_check_and_ingest_without_the_book_have_no_pulls(self):
        tv.Builder(OPEN).run("open-lib", SLUG, 1, tv.SHA_OPEN).write(self.books)
        ti.put(self.out, "open-lib/pulls/7.json", "{")
        self.assertEqual(tf.cli("check", self.books)[0], 0)
        self.assertNotIn("pulls", tf.cli("summary", self.books, "--json")[1] + tf.cli("summary", self.books)[1])
        code, out = ti.cli("ingest", self.books, self.out, "--json")
        self.assertEqual(code, 0, out)
        self.assertNotIn("pulls", out)

    def test_a_pull_request_link_is_not_a_run_link_in_any_other_book(self):
        tv.Builder(OPEN).run("open-lib", SLUG, 1, tv.SHA_OPEN).write(self.books)
        text = (self.books / quality.RUNS).read_text().replace(tv.link(SLUG, 1), pull_link(SLUG, 1))
        (self.books / quality.RUNS).write_text(text)
        code, out = tf.cli("check", self.books)
        self.assertEqual(code, 1)
        self.assertIn("evidence must look like https://HOST/OWNER/REPO/actions/runs/N/attempts/N", out)


def pull_body(number: int = 7, repo: str = "open-lib", slug: str = SLUG, **over) -> dict:
    body = {"v": 1, "repo": repo, "github": slug, "merged": at("12:00"), "number": number, "opened": at("10:00"), "ready": at("10:01"),
            "head_ci_done": at("11:10"), "ci_ms": 3_300_000, "wait_ms": 3_000_000, "shas": 2, "checks": 3, "force_pushes": 2,
            "evidence": pull_link(slug, number)}
    body.update(over)
    return body


def pull_cells(body: dict) -> list:
    return [body[k] for k in quality.PULLS_SCHEMA]


class IngestPullsTest(tv.TempCase):
    def setUp(self):
        super().setUp()
        self.art = self.tmp / "art"
        self.art.mkdir()
        tv.Builder(OPEN, SECRET).write(self.books)
        tv.write_csv(self.books / quality.PULLS, quality.PULLS_SCHEMA, [])

    def put(self, body, repo: str = "open-lib", name: str = "7") -> None:
        ti.put(self.art, f"{repo}/pulls/{name}.json", body if isinstance(body, str) else json.dumps(body))

    def ingest(self, *extra) -> tuple[int, str]:
        return ti.cli("ingest", self.books, self.art, *extra)

    def rows(self) -> list[list[str]]:
        return ti.csv_rows(self.books / quality.PULLS)[1:]

    def test_a_pull_request_is_booked_once_and_check_passes(self):
        self.put(pull_body())
        code, out = self.ingest()
        self.assertEqual(code, 0, out)
        self.assertIn(f"booked pull open-lib 7: merged {at('12:00')}, ci 3300000 ms, wait 3000000 ms\n", out)
        self.assertIn("booked 1 merged pull requests; 0 already booked, rejected 0\n", out)
        self.assertEqual(self.rows(), [[at("12:00"), "open-lib", "7", at("10:00"), at("10:01"), at("11:10"), "3300000", "3000000",
                                        "2", "3", "2", pull_link(SLUG, 7)]])
        self.assertEqual(tf.cli("check", self.books)[0], 0)
        code, out = self.ingest("--json")
        self.assertEqual(code, 0, out)
        got = json.loads(out)
        self.assertEqual(got["pulls"], [{"path": "open-lib/pulls/7.json", "status": "unchanged", "number": 7, "merged": at("12:00")}])
        self.assertEqual((got["totals"]["pulls_booked"], got["totals"]["pulls_unchanged"], got["totals"]["pulls_rejected"]), (0, 1, 0))
        self.assertEqual(len(self.rows()), 1)

    def test_new_rows_are_appended_in_merge_order_to_what_is_booked(self):
        self.put(pull_body(8, merged=at("13:00"), evidence=pull_link(SLUG, 8)), name="8")
        self.put(pull_body(7), name="7")
        self.put(pull_body(9, repo="secret-app", slug="acme/secret-app"), repo="secret-app", name="9")
        code, out = self.ingest()
        self.assertEqual(code, 0, out)
        self.assertEqual([(r[1], r[2]) for r in self.rows()], [("open-lib", "7"), ("secret-app", "9"), ("open-lib", "8")])
        self.assertEqual(tf.cli("check", self.books)[0], 0)

    def test_a_pull_request_booked_with_another_row_is_rejected_never_changed(self):
        self.put(pull_body())
        self.ingest()
        self.put(pull_body(ci_ms=1))
        code, out = self.ingest()
        self.assertEqual(code, 1, out)
        self.assertIn("rejected: open-lib/pulls/7.json: open-lib pull request 7 is booked already with a different row; a row is never changed\n", out)
        self.assertEqual(len(self.rows()), 1)

    def test_a_bad_file_is_rejected_by_name_and_the_good_one_is_booked(self):
        bad = {"wrong repo": (pull_body(repo="secret-app"), "repo secret-app is not in folder open-lib"),
               "wrong number": (pull_body(number=8), "number 8 is not the file's name"),
               "other github": (pull_body(slug="acme/other"), "github acme/other is not acme/open-lib"),
               "other repo's link": (pull_body(evidence=pull_link("acme/other", 7)), "is not pull request 7 of acme/open-lib"),
               "other number's link": (pull_body(evidence=pull_link(SLUG, 8)), "is not pull request 7 of acme/open-lib"),
               "a run link": (pull_body(evidence=tv.link(SLUG, 7)), "is not pull request 7"),
               "backwards": (pull_body(opened=at("13:00"), ready=at("13:00")), "must not run backwards"),
               "too much ci": (pull_body(ci_ms=7_000_000), "is more than the time from ready to merged"),
               "bad stamp": (pull_body(head_ci_done="soon"), "head_ci_done must be empty or look like"),
               "a float": (pull_body(checks=1.5), "checks must be int"),
               "a bool": (pull_body(shas=True), "shas must be int"),
               "extra key": ({**pull_body(), "path": "x"}, "unknown key"),
               "missing key": ({k: v for k, v in pull_body().items() if k != "ready"}, "is missing ready"),
               "wrong version": (pull_body(v=2), "v must be 1"),
               "not json": ("{", "")}
        for name, (body, why) in bad.items():
            with self.subTest(name):
                self.put(body)
                code, out = self.ingest()
                self.assertEqual(code, 1, out)
                self.assertIn("rejected: open-lib/pulls/7.json: ", out)
                self.assertIn(why, out)
                self.assertEqual(self.rows(), [])
        self.put(pull_body())
        self.put(pull_body(9, repo="stray", slug="acme/stray"), repo="stray", name="9")
        code, out = self.ingest()
        self.assertEqual(code, 1, out)
        self.assertIn("repo stray is not on the watch list", out)
        self.assertEqual(len(self.rows()), 1)

    def test_a_file_whose_name_is_not_its_number_is_rejected(self):
        self.put(pull_body(), name="007")
        code, out = self.ingest()
        self.assertEqual(code, 1, out)
        self.assertIn("number 7 is not the file's name", out)

    def test_only_jobs_or_visibility_leaves_the_book_alone(self):
        self.put(pull_body())
        for only in ("jobs", "visibility"):
            code, out = self.ingest("--only", only)
            self.assertNotIn("pulls", out)
        self.assertEqual(self.rows(), [])

    def test_a_dry_run_books_nothing(self):
        self.put(pull_body())
        code, out = self.ingest("--dry-run")
        self.assertEqual(code, 0, out)
        self.assertIn("would book pull open-lib 7", out)
        self.assertEqual(self.rows(), [])


class CheckPullsTest(tv.TempCase):
    def problems(self, rows: list) -> str:
        tv.Builder(OPEN).write(self.books)
        tv.write_csv(self.books / quality.PULLS, quality.PULLS_SCHEMA, rows)
        code, out = tf.cli("check", self.books)
        self.assertEqual(code, 1, out)
        return out

    def test_a_good_row_passes_and_is_counted(self):
        tv.Builder(OPEN).write(self.books)
        tv.write_csv(self.books / quality.PULLS, quality.PULLS_SCHEMA, [pull_cells(pull_body()), pull_cells(pull_body(8, head_ci_done="", checks=0))])
        code, out = tf.cli("check", self.books)
        self.assertEqual(code, 0, out)
        self.assertIn("ok, ", out)

    def test_rows_are_unique_by_repo_and_number_and_held_to_their_rules(self):
        good = pull_cells(pull_body())
        bad = pull_cells(pull_body(8, merged="2026-11-12 12:00", opened="soon", ci_ms=-1, shas="x", evidence="https://example.com/x"))
        out = self.problems([good, good, bad])
        for message in ("books/pulls.csv:3: duplicate of line 2 (same repo and number)", "books/pulls.csv:4: merged must look like",
                        "books/pulls.csv:4: opened must look like", "books/pulls.csv:4: ci_ms must be a non-negative integer",
                        "books/pulls.csv:4: shas must be a non-negative integer", "books/pulls.csv:4: evidence must look like https://github.com/OWNER/NAME/pull/N"):
            self.assertIn(message, out)

    def test_the_order_of_the_times_the_budget_and_the_link_number_are_held(self):
        out = self.problems([pull_cells(pull_body(7, opened=at("11:00"), ready=at("10:00"))),
                             pull_cells(pull_body(8, ci_ms=3_600_000, wait_ms=3_600_001, ready=at("10:00"))),
                             pull_cells(pull_body(9, evidence=pull_link(SLUG, 10))),
                             pull_cells(pull_body(10, ready=at("12:01")))])
        self.assertIn("books/pulls.csv:2: opened, ready and merged must not run backwards", out)
        self.assertIn("books/pulls.csv:3: ci_ms + wait_ms (7200001) is more than the time from ready to merged", out)
        self.assertIn("books/pulls.csv:4: evidence names pull request 10, not the row's number '9'", out)
        self.assertIn("books/pulls.csv:5: opened, ready and merged must not run backwards", out)

    def test_a_zero_number_leading_zeros_and_a_formula_are_refused(self):
        out = self.problems([pull_cells(pull_body(0, evidence=pull_link(SLUG, 0))), pull_cells(pull_body("08", evidence=pull_link(SLUG, 8))),
                             pull_cells(pull_body(9, head_ci_done="=1+1"))])
        self.assertIn("books/pulls.csv:2: number must be a positive integer without leading zeros", out)
        self.assertIn("books/pulls.csv:3: number must be a positive integer without leading zeros", out)
        self.assertIn("books/pulls.csv:4: head_ci_done must be empty or look like", out)

    def test_the_header_is_held(self):
        tv.Builder(OPEN).write(self.books)
        (self.books / quality.PULLS).write_text("merged,repo\n")
        code, out = tf.cli("check", self.books)
        self.assertEqual(code, 1)
        self.assertIn("books/pulls.csv:1: header does not match the schema: expected " + ",".join(quality.PULLS_SCHEMA), out)


def row(repo: str, number: int, opened: str, merged: str, ci_min: int, wait_min: int, checks: int, slug: str = SLUG,
        day: str = DAY) -> list:
    body = pull_body(number, repo, slug, opened=at(opened, day), ready=at(opened, day), merged=at(merged, day), head_ci_done="",
                     ci_ms=ci_min * 60000, wait_ms=wait_min * 60000, checks=checks)
    return pull_cells(body)


class SummaryPullsTest(tv.TempCase):
    WEEK = ["--week", "2026-W46"]

    def books_with(self, pulls: list) -> None:
        b = tv.Builder(OPEN, SECRET).run("open-lib", SLUG, 1, tv.SHA_OPEN).run("secret-app", "acme/secret-app", 2, tv.SHA_SECRET)
        b.visibility(tv.STAMP, "open-lib", SLUG, "public").visibility(tv.STAMP, "secret-app", "acme/secret-app", "private")
        b.write(self.books)
        tv.write_csv(self.books / quality.PULLS, quality.PULLS_SCHEMA, pulls)

    def summary(self, *extra) -> dict:
        code, out = tf.cli("summary", self.books, *self.WEEK, "--json", *extra)
        self.assertEqual(code, 0, out)
        return json.loads(out)

    def test_the_week_has_a_median_and_a_p95_per_part_and_never_a_sum(self):
        self.books_with([row("open-lib", 1, "10:00", "10:10", 2, 1, 2), row("open-lib", 2, "10:00", "10:30", 10, 5, 3),
                         row("open-lib", 3, "10:00", "12:00", 20, 60, 0),
                         row("open-lib", 4, "10:00", "10:40", 1, 1, 1, day="2026-11-05"),
                         row("secret-app", 5, "10:00", "10:20", 1, 1, 1, slug="acme/secret-app")])
        s = self.summary()
        self.assertEqual(s["repos"]["open-lib"]["pulls"], {
            "count": 3, "no_checks": 1,
            "open_ms": {"p50": 1_800_000, "p95": 7_200_000}, "ci_ms": {"p50": 600_000, "p95": 1_200_000},
            "rework_ms": {"p50": 900_000, "p95": 2_400_000}, "wait_ms": {"p50": 300_000, "p95": 3_600_000}})
        self.assertEqual(s["repos"]["secret-app"]["pulls"]["count"], 1)
        text = tf.cli("summary", self.books, *self.WEEK)[1]
        self.assertIn("  pulls: 3 merged (1 without checks); open p50 1800000 ms (p95 7200000); ci p50 600000 ms (p95 1200000); "
                      "rework p50 900000 ms (p95 2400000); wait p50 300000 ms (p95 3600000)\n", text)

    def test_a_repo_with_no_pull_request_merged_that_week_has_null(self):
        self.books_with([row("open-lib", 4, "10:00", "10:40", 1, 1, 1, day="2026-11-05")])
        s = self.summary()
        self.assertEqual((s["repos"]["open-lib"]["pulls"], s["repos"]["secret-app"]["pulls"]), (None, None))
        self.assertIn("  pulls: none merged this week\n", tf.cli("summary", self.books, *self.WEEK)[1])

    def test_a_merge_belongs_to_the_iso_week_of_its_merged_stamp(self):
        self.books_with([row("open-lib", 1, "23:00", "23:59", 1, 1, 1, day="2026-11-15"), row("open-lib", 2, "00:00", "00:30", 1, 1, 1, day="2026-11-16")])
        self.assertEqual(self.summary()["repos"]["open-lib"]["pulls"]["count"], 1)

    def test_public_only_and_leak_check_keep_a_private_repos_pulls_out(self):
        self.books_with([row("secret-app", 5, "10:00", "10:20", 1, 1, 1, slug="acme/secret-app"), row("open-lib", 1, "10:00", "10:10", 2, 1, 2)])
        self.assertEqual(self.summary()["repos"]["secret-app"]["pulls"]["count"], 1)
        code, out = tf.cli("summary", self.books, *self.WEEK, "--json", "--public-only")
        self.assertEqual(code, 0, out)
        self.assertNotIn("secret-app", out)
        leaky = self.tmp / "post.md"
        leaky.write_text(f"Read {pull_link('acme/secret-app', 5)} for the cause.\n")
        code, out = tf.cli("leak-check", self.books, leaky)
        self.assertEqual(code, 1, out)

    def test_summary_without_the_file_is_what_it_was(self):
        self.books_with([])
        (self.books / quality.PULLS).unlink()
        self.assertNotIn("pulls", json.dumps(self.summary()))


class AppendOnlyPullsTest(tv.TempCase):
    def test_a_booked_row_may_not_change_or_go_with_a_base(self):
        tv.Builder(OPEN).write(self.books)
        tv.write_csv(self.books / quality.PULLS, quality.PULLS_SCHEMA, [pull_cells(pull_body())])
        git = lambda *a: tv.subprocess.run(["git", "-C", str(self.books), "-c", "user.name=t", "-c", "user.email=t@example.com",
                                            "-c", "commit.gpgsign=false", *a], capture_output=True, check=True)
        git("init", "-q")
        git("add", "-A")
        git("commit", "-q", "-m", "books")
        self.assertEqual(tf.cli("check", self.books, "--base", "HEAD")[0], 0)
        with open(self.books / quality.PULLS, "a") as f:
            f.write(",".join(map(str, pull_cells(pull_body(8, evidence=pull_link(SLUG, 8))))) + "\n")
        self.assertEqual(tf.cli("check", self.books, "--base", "HEAD")[0], 0)
        text = (self.books / quality.PULLS).read_text().replace("3300000", "3300001", 1)
        (self.books / quality.PULLS).write_text(text)
        self.assertIn("books/pulls.csv:2: changed since HEAD", tf.cli("check", self.books, "--base", "HEAD")[1])
        (self.books / quality.PULLS).unlink()
        self.assertIn("books/pulls.csv:1: removed since HEAD", tf.cli("check", self.books, "--base", "HEAD")[1])


if __name__ == "__main__":
    unittest.main()
