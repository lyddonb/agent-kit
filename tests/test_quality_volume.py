"""Tests for the volume book (`books/volume.csv`): test and source lines per repo per week
(plugins/bstack/skills/qualitydirector/scripts/quality.py).

Every repo, sha and link here is made up. `fetch` is driven through the fake `gh` of test_quality_fetch with --today set,
and tarballs are built here in memory. UnadoptedVolumeTest holds what books without the file must still do: the same calls,
files and output as before the book existed.
"""
import io
import json
import re
import tarfile
import unittest
import unittest.mock

import test_quality_fetch as tf
import test_quality_ingest as ti
import test_quality_visibility as tv

quality = tf.quality
OPEN, SECRET = tv.OPEN, tv.SECRET
TODAY = tv.TODAY  # a Sunday in 2026-W46, so 2026-W45 is the last complete week
W44, W45 = "2026-W44", "2026-W45"
SHA_A, SHA_B = "a" * 40, "b" * 40


def tarball(files: dict[str, bytes], top: str = "acme-open-lib-aaaaaaa", links: tuple[str, ...] = ()) -> bytes:
    """A gzip tarball shaped like GitHub's: every member under one top folder."""
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz") as archive:
        for path, data in files.items():
            info = tarfile.TarInfo(f"{top}/{path}")
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
        for path in links:
            info = tarfile.TarInfo(f"{top}/{path}")
            info.type, info.linkname = tarfile.SYMTYPE, "src/app.py"
            archive.addfile(info)
    return out.getvalue()


CODE = {"src/app.py": b"a\nb\nc\n", "src/util.py": b"x\ny", "tests/test_app.py": b"1\n2\n3\n4\n", "README.md": b"one\ntwo\n"}
# source: app.py 3 lines + util.py 2 lines (no newline at the end); test: 4 lines; README not counted
COUNTS = {"test_files": 1, "test_lines": 4, "source_files": 2, "source_lines": 5}


def push_run(run_id: int, sha: str, created: str, slug: str = "acme/open-lib", **over) -> dict:
    run = tv.run_obj(run_id, slug, event="push", head_branch="main", head_sha=sha, created_at=created)
    run.update(over)
    return run


class ClassifyTest(unittest.TestCase):
    def test_each_path_is_test_source_or_not_counted(self):
        cases = {"src/app.py": "source", "app.py": "source", "scripts/x.sh": "source", "web/app.tsx": "source",
                 "tests/helpers.py": "test", "pkg/tests/fixtures/x.py": "test", "test_top.py": "test", "pkg/a_test.py": "test",
                 "pkg/a_test.go": "test", "conftest.py": "test", "web/a.test.ts": "test", "web/a.spec.js": "test",
                 "web/__tests__/a.js": "test", "spec/a_spec.rb": "test", "e2e/flow.ts": "test",
                 "README.md": None, "data.json": None, "migrations/1.sql": None, "node_modules/x/index.js": None,
                 "vendor/lib.go": None, "dist/app.js": None, "a/build/x.py": None, "testing.py": "source", "contest.py": "source"}
        for path, kind in cases.items():
            self.assertEqual(quality.classify_path(path), kind, path)


class CountTarballTest(unittest.TestCase):
    def test_lines_are_counted_by_kind_and_a_last_line_without_a_newline_counts(self):
        self.assertEqual(quality.count_tarball(tarball(CODE))._asdict(), COUNTS)

    def test_links_folders_and_empty_files_are_handled(self):
        raw = tarball({**CODE, "src/empty.py": b""}, links=("src/link.py",))
        self.assertEqual(quality.count_tarball(raw)._asdict(), {**COUNTS, "source_files": 3})

    def test_a_file_that_is_not_a_tarball_or_is_over_a_cap_is_rejected(self):
        for raw in (b"not a tarball", tarball(CODE)[:40]):
            with self.assertRaisesRegex(quality.Rejected, "not a readable gzip tarball"):
                quality.count_tarball(raw)
        for cap, value, why in (("MAX_TARBALL_BYTES", 10, "larger than"), ("MAX_TARBALL_MEMBERS", 2, "more than 2 members"),
                                ("MAX_TARBALL_UNPACKED", 8, "holds more than")):
            with unittest.mock.patch.object(quality, cap, value), self.assertRaisesRegex(quality.Rejected, why):
                quality.count_tarball(tarball(CODE))


class WeeksTest(unittest.TestCase):
    def test_last_week_by_default_then_the_weeks_after_the_latest_booked_or_from_since(self):
        today = quality.date(2026, 11, 15)
        self.assertEqual(quality.volume_weeks(today, None, set()), [W45])
        self.assertEqual(quality.volume_weeks(today, None, {W45}), [])
        self.assertEqual(quality.volume_weeks(today, None, {"2026-W43"}), [W44, W45])
        self.assertEqual(quality.volume_weeks(today, "2026-10-26", {W44}), [W45])
        self.assertEqual(quality.volume_weeks(today, "2026-10-27", set()), [W44, W45])
        self.assertEqual(quality.volume_weeks(quality.date(2026, 11, 16), None, set()), ["2026-W46"])
        self.assertEqual(quality.volume_weeks(quality.date(2026, 1, 1), None, set()), ["2025-W52"])


class FetchVolumeBase(tv.FetchBase):
    def setUp(self):
        super().setUp()
        tv.Builder(OPEN).write(self.books)
        tv.write_csv(self.books / quality.VOLUME, quality.VOLUME_SCHEMA, [])
        self.listing("acme/open-lib")
        self.put("repos/acme/open-lib", {"visibility": "public", "default_branch": "main"})

    def week_runs(self, week: str, *runs: dict, slug: str = "acme/open-lib") -> None:
        monday, sunday = quality._week_days(week)
        query = re.sub(r"[^A-Za-z0-9._-]", "_", f"branch=main&event=push&per_page=100&created={monday}..{sunday}")
        self.put(f"repos/{slug}/actions/runs__q__{query}", {"total_count": len(runs), "workflow_runs": list(runs)})

    def serve_tarball(self, sha: str, raw: bytes, slug: str = "acme/open-lib") -> None:
        (self.data / "api" / (f"repos/{slug}/tarball/{sha}".replace("/", "__") + ".zip")).write_bytes(raw)

    def volume_file(self, week: str, repo: str = "open-lib") -> dict:
        return json.loads((self.out / repo / "volume" / f"{week}.json").read_text())


class FetchVolumeTest(FetchVolumeBase):
    def test_the_newest_push_run_of_the_workflow_on_the_default_branch_names_the_commit(self):
        self.week_runs(W45, push_run(6, SHA_B, "2026-11-03T10:00:00Z"), push_run(7, SHA_A, "2026-11-08T20:00:00Z"),
                       push_run(8, "c" * 40, "2026-11-08T21:00:00Z", name="other"),
                       push_run(9, "d" * 40, "2026-11-08T22:00:00Z", head_branch="feat/x"),
                       push_run(10, "e" * 40, "2026-11-08T23:00:00Z", head_repository={"full_name": "fork/open-lib"}),
                       push_run(11, "f" * 40, "2026-11-08T23:30:00Z", event="pull_request"))
        self.serve_tarball(SHA_A, tarball(CODE))
        code, out = self.fetch()
        self.assertEqual(code, 0, out)
        self.assertEqual(self.volume_file(W45), {"v": 1, "repo": "open-lib", "github": "acme/open-lib", "week": W45, "sha": SHA_A,
                                                 "rule": "v1", "evidence": "https://github.com/acme/open-lib/actions/runs/7/attempts/1", **COUNTS})
        self.assertIn(f"  volume {W45}: {SHA_A[:12]} test 4 lines in 1 files, source 5 lines in 2 files\n", out)
        self.assertTrue(out.endswith("; volume counted for 1 weeks (0 without a push run); 0 failed\n"), out)
        self.assertEqual(self.endpoints()[-3:], ["repos/acme/open-lib", "repos/acme/open-lib/actions/runs", f"repos/acme/open-lib/tarball/{SHA_A}"])

    def test_a_week_without_a_push_run_has_no_file_and_one_commit_is_downloaded_once(self):
        self.week_runs(W44)
        self.week_runs(W45, push_run(7, SHA_A, "2026-11-08T20:00:00Z"))
        self.week_runs("2026-W43", push_run(5, SHA_A, "2026-10-20T20:00:00Z"))
        self.serve_tarball(SHA_A, tarball(CODE))
        code, out = self.fetch("--since", "2026-10-19")
        self.assertEqual(code, 0, out)
        self.assertIn(f"  volume {W44}: no push run of ci on main; no row\n", out)
        self.assertEqual(sorted(p.name for p in (self.out / "open-lib" / "volume").iterdir()), ["2026-W43.json", "2026-W45.json"])
        self.assertEqual(self.endpoints().count(f"repos/acme/open-lib/tarball/{SHA_A}"), 1)
        self.assertIn("; volume counted for 2 weeks (1 without a push run); 0 failed\n", out)

    def test_booked_weeks_are_not_asked_for_again(self):
        tv.write_csv(self.books / quality.VOLUME, quality.VOLUME_SCHEMA,
                     [[W45, "open-lib", SHA_A, "v1", 1, 4, 2, 5, tv.link("acme/open-lib", 7)]])
        code, out = self.fetch()
        self.assertEqual(code, 0, out)
        self.assertNotIn("repos/acme/open-lib/tarball", " ".join(self.endpoints()))
        self.assertFalse((self.out / "open-lib" / "volume").exists())

    def test_a_failed_listing_or_a_bad_tarball_fails_that_week_only(self):
        self.week_runs(W44, push_run(5, SHA_B, "2026-11-01T20:00:00Z"))
        self.week_runs(W45, push_run(7, SHA_A, "2026-11-08T20:00:00Z"))
        self.serve_tarball(SHA_A, b"not a tarball")
        self.serve_tarball(SHA_B, tarball(CODE))
        code, out = self.fetch("--since", "2026-10-27")
        self.assertEqual(code, 1, out)
        self.assertIn(f"  FAILED volume {W45}: tarball of {SHA_A[:12]} is not a readable gzip tarball (ReadError)\n", out)
        self.assertEqual([p.name for p in (self.out / "open-lib" / "volume").iterdir()], ["2026-W44.json"])

    def test_too_many_weeks_are_counted_oldest_first_and_the_rest_left_for_later(self):
        with unittest.mock.patch.object(quality, "MAX_VOLUME_WEEKS", 1):
            self.week_runs(W44)
            code, out = self.fetch("--since", "2026-10-27")
        self.assertEqual(code, 0, out)
        self.assertIn("  volume: 2 weeks to count; counting the oldest 1, the rest on a later fetch\n", out)
        self.assertIn(f"  volume {W44}: no push run", out)
        self.assertNotIn(W45, out)


class UnadoptedVolumeTest(tv.FetchBase):
    def test_fetch_without_the_book_makes_no_volume_call_and_prints_what_it_did_before(self):
        tv.Builder(OPEN).write(self.books, repos=False, jobs=False)
        self.listing("acme/open-lib")
        code, out = self.fetch()
        self.assertEqual((code, out), (0, "open-lib (acme/open-lib, ci): runs created since 2026-11-08\n"
                                          "fetched 0 runs (0 artifacts); listed 0; skipped 0 forks, 0 pushes to a non-default branch, "
                                          "0 already booked, 0 without test-results artifacts; 0 failed\n"))
        self.assertEqual(self.endpoints(), ["repos/acme/open-lib/actions/runs"])

    def test_summary_and_ingest_without_the_book_have_no_volume(self):
        tv.Builder(OPEN).run("open-lib", "acme/open-lib", 1, tv.SHA_OPEN).write(self.books)
        ti.put(self.out, f"open-lib/volume/{W45}.json", json.dumps({"v": 1}))
        self.assertNotIn("volume", tf.cli("summary", self.books, "--json")[1] + tf.cli("summary", self.books)[1])
        code, out = ti.cli("ingest", self.books, self.out, "--json")
        self.assertEqual(code, 0, out)
        self.assertNotIn("volume", out)


def volume_body(week: str = W45, sha: str = SHA_A, repo: str = "open-lib", slug: str = "acme/open-lib", run: int = 7, **over) -> dict:
    body = {"v": 1, "repo": repo, "github": slug, "week": week, "sha": sha, "rule": "v1", "evidence": tv.link(slug, run), **COUNTS}
    body.update(over)
    return body


class IngestVolumeTest(tv.TempCase):
    def setUp(self):
        super().setUp()
        self.art = self.tmp / "art"
        self.art.mkdir()
        tv.Builder(OPEN, SECRET).write(self.books)
        tv.write_csv(self.books / quality.VOLUME, quality.VOLUME_SCHEMA, [])

    def put(self, body, repo: str = "open-lib", week: str = W45) -> None:
        ti.put(self.art, f"{repo}/volume/{week}.json", body if isinstance(body, str) else json.dumps(body))

    def ingest(self, *extra) -> tuple[int, str]:
        return ti.cli("ingest", self.books, self.art, *extra)

    def rows(self) -> list[list[str]]:
        return ti.csv_rows(self.books / quality.VOLUME)[1:]

    def test_a_week_is_booked_once_and_check_passes(self):
        self.put(volume_body())
        code, out = self.ingest()
        self.assertEqual(code, 0, out)
        self.assertIn(f"booked volume open-lib {W45}: test 4 lines, source 5 lines\n", out)
        self.assertIn("booked volume of 1 weeks; 0 already booked, rejected 0\n", out)
        self.assertEqual(self.rows(), [[W45, "open-lib", SHA_A, "v1", "1", "4", "2", "5", tv.link("acme/open-lib", 7)]])
        self.assertEqual(tf.cli("check", self.books)[0], 0)
        code, out = self.ingest("--json")
        self.assertEqual(code, 0, out)
        self.assertEqual(json.loads(out)["volume"], [{"path": f"open-lib/volume/{W45}.json", "status": "unchanged", "week": W45, "sha": SHA_A}])
        self.assertEqual(len(self.rows()), 1)

    def test_a_week_booked_with_other_counts_is_rejected_never_changed(self):
        self.put(volume_body())
        self.ingest()
        self.put(volume_body(sha=SHA_B))
        code, out = self.ingest()
        self.assertEqual(code, 1, out)
        self.assertIn(f"rejected: open-lib/volume/{W45}.json: open-lib {W45} is booked already with {SHA_A[:12]} (v1); a row is never changed\n", out)
        self.assertEqual(len(self.rows()), 1)

    def test_a_bad_file_is_rejected_by_name_and_the_good_one_is_booked(self):
        bad = {"wrong repo": (volume_body(repo="secret-app"), "repo secret-app is not in folder open-lib"),
               "wrong week": (volume_body(week=W44), f"week {W44} is not the file's name"),
               "other github": (volume_body(slug="acme/other"), "github acme/other is not acme/open-lib"),
               "other run": (volume_body(evidence=tv.link("acme/other", 7)), "is not a run of acme/open-lib"),
               "bad sha": (volume_body(sha="XYZ"), "sha must be 40 lowercase hex"),
               "bad rule": (volume_body(rule="v9"), "rule must be one of v1"),
               "a float": (volume_body(test_lines=1.5), "test_lines must be int"),
               "extra key": ({**volume_body(), "path": "x"}, "unknown key"),
               "not json": ("{", "")}
        for name, (body, why) in bad.items():
            with self.subTest(name):
                self.put(body)
                code, out = self.ingest()
                self.assertEqual(code, 1, out)
                self.assertIn(f"rejected: open-lib/volume/{W45}.json: ", out)
                self.assertIn(why, out)
                self.assertEqual(self.rows(), [])
        self.put(volume_body())
        self.put(volume_body(repo="stray", slug="acme/stray"), repo="stray")
        code, out = self.ingest()
        self.assertEqual(code, 1, out)
        self.assertIn("repo stray is not on the watch list", out)
        self.assertEqual(len(self.rows()), 1)

    def test_only_jobs_or_visibility_leaves_the_book_alone(self):
        self.put(volume_body())
        for only in ("jobs", "visibility"):
            code, out = self.ingest("--only", only)
            self.assertNotIn("volume", out)
        self.assertEqual(self.rows(), [])


class CheckVolumeTest(tv.TempCase):
    def test_rows_are_unique_by_week_and_repo_and_held_to_their_rules(self):
        tv.Builder(OPEN).write(self.books)
        good = [W45, "open-lib", SHA_A, "v1", 1, 4, 2, 5, tv.link("acme/open-lib", 7)]
        tv.write_csv(self.books / quality.VOLUME, quality.VOLUME_SCHEMA,
                     [good, good, [W44, "open-lib", SHA_A, "v2", -1, 4, 2, 5, "x"]])
        code, out = tf.cli("check", self.books)
        self.assertEqual(code, 1)
        for message in ("books/volume.csv:3: duplicate of line 2 (same week and repo)", "books/volume.csv:4: rule must be one of v1",
                        "books/volume.csv:4: test_files must be a non-negative integer", "books/volume.csv:4: evidence must look like"):
            self.assertIn(message, out)


class SummaryVolumeTest(tv.TempCase):
    def books_with(self, volume: list) -> None:
        b = tv.Builder(OPEN, SECRET).run("open-lib", "acme/open-lib", 1, tv.SHA_OPEN).run("secret-app", "acme/secret-app", 2, tv.SHA_SECRET)
        b.visibility(tv.STAMP, "open-lib", "acme/open-lib", "public").visibility(tv.STAMP, "secret-app", "acme/secret-app", "private")
        b.write(self.books)
        tv.write_csv(self.books / quality.VOLUME, quality.VOLUME_SCHEMA, volume)

    def summary(self, *extra) -> dict:
        code, out = tf.cli("summary", self.books, "--week", "2026-W46", "--json", *extra)
        self.assertEqual(code, 0, out)
        return json.loads(out)

    def test_the_week_row_and_its_change_since_the_latest_earlier_row(self):
        self.books_with([["2026-W46", "open-lib", SHA_B, "v1", 2, 10, 3, 7, tv.link("acme/open-lib", 9)],
                         ["2026-W44", "open-lib", SHA_A, "v1", 1, 4, 2, 5, tv.link("acme/open-lib", 7)],
                         ["2026-W43", "open-lib", SHA_A, "v1", 1, 1, 1, 1, tv.link("acme/open-lib", 6)]])
        s = self.summary()
        self.assertEqual(s["repos"]["open-lib"]["volume"], {
            "evidence": tv.link("acme/open-lib", 9), "rule": "v1", "sha": SHA_B, "test_files": 2, "test_lines": 10,
            "source_files": 3, "source_lines": 7, "prior_week": W44, "test_lines_change": 6, "source_lines_change": 2})
        self.assertIsNone(s["repos"]["secret-app"]["volume"])
        text = tf.cli("summary", self.books, "--week", "2026-W46")[1]
        self.assertIn("  volume: test 10 lines in 2 files, source 7 lines in 3 files; since 2026-W44: test +6, source +2\n", text)
        self.assertIn("  volume: no row this week\n", text)

    def test_a_first_row_has_no_change(self):
        self.books_with([["2026-W46", "open-lib", SHA_B, "v1", 2, 10, 3, 7, tv.link("acme/open-lib", 9)]])
        v = self.summary()["repos"]["open-lib"]["volume"]
        self.assertEqual((v["prior_week"], v["test_lines_change"], v["source_lines_change"]), (None, None, None))
        self.assertIn("; no earlier week\n", tf.cli("summary", self.books, "--week", "2026-W46")[1])

    def test_public_only_and_leak_check_keep_a_private_repos_volume_out(self):
        secret_sha = "5" * 40
        self.books_with([["2026-W46", "secret-app", secret_sha, "v1", 2, 10, 3, 7, tv.link("acme/secret-app", 9)],
                         ["2026-W46", "open-lib", SHA_B, "v1", 2, 10, 3, 7, tv.link("acme/open-lib", 9)]])
        self.assertEqual(self.summary()["repos"]["secret-app"]["volume"]["sha"], secret_sha)
        code, out = tf.cli("summary", self.books, "--week", "2026-W46", "--json", "--public-only")
        self.assertEqual(code, 0, out)
        self.assertNotIn(secret_sha, out)
        self.assertNotIn("secret-app", out)
        leaky = self.tmp / "post.md"
        leaky.write_text(f"Counted at {secret_sha[:12]} this week.\n")
        code, out = tf.cli("leak-check", self.books, leaky)
        self.assertEqual(code, 1, out)


if __name__ == "__main__":
    unittest.main()
