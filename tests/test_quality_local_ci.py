"""Tests for local-ci runs in the quality books: a watch-list row whose workflow is `local-ci` is fetched from the repo's
refs/local-ci/records (plugins/bstack/skills/qualitydirector/scripts/quality.py).

Every repo, sha and link here is made up. `fetch` is driven through the fake `gh` of test_quality_fetch, which serves the git
API answers written here; nothing touches the network or the clock.
"""
import base64
import json
import re
import unittest

import test_quality_fetch as tf
import test_quality_ingest as ti
import test_quality_visibility as tv

quality = tf.quality
SLUG, REPO = "acme/secret-app", "secret-app"
SHA_A, SHA_B = "a" * 40, "b" * 40
STARTED_A, STARTED_B = "2026-11-14T10:00:00Z", "2026-11-14T12:00:00Z"
TIP, TREE = "c" * 40, "d" * 40


def record(sha: str, evidence: str = "", fail: bool = False) -> bytes:
    header = {"v": 1, "repo": REPO, "sha": sha, "event": "local", "workflow": "", "python": "3.12", "os": "darwin",
              "started": "2026-11-14T10:00:30Z", "wall_ms": 1500, "exit_code": int(fail), "complete": True, "tests": 2,
              "failed": int(fail), "skipped": 0, "evidence": evidence}
    rows = [{"id": "t.A.test_a", "ms": 3, "outcome": "fail" if fail else "pass"}, {"id": "t.A.test_b", "ms": 4, "outcome": "pass"}]
    return "".join(json.dumps(r) + "\n" for r in [header] + rows).encode()


def manifest(sha: str, started: str, **over) -> bytes:
    body = {"v": 1, "github": SLUG, "sha": sha, "event": "push", "pr": None, "head_branch": "main", "base": "main",
            "started": started, "completed": started.replace("T10", "T10").replace(":00:00Z", ":09:00Z"), "exit_code": 0,
            "host": "testhost"}
    body.update(over)
    return json.dumps(body).encode()


def link(sha: str, started: str) -> str:
    return f"https://github.com/{SLUG}/commit/{sha}#local-ci-{started}"


class LocalBase(tv.FetchBase):
    def setUp(self):
        super().setUp()
        tv.Builder((REPO, SLUG)).write(self.books, jobs=False)
        text = (self.books / quality.WATCHED).read_text().replace(f"{SLUG},ci", f"{SLUG},local-ci")
        (self.books / quality.WATCHED).write_text(text)
        self.put(f"repos/{SLUG}", {"visibility": "private", "default_branch": "main"})
        self.runs_on_ref = {}

    def run_on_ref(self, sha: str, started: str, man: bytes, rec: bytes) -> None:
        self.runs_on_ref[(sha, started)] = (man, rec)

    def serve(self, truncated: bool = False, ref: bool = True) -> None:
        self.put(f"repos/{SLUG}/git/matching-refs/local-ci/records",
                 [{"ref": "refs/local-ci/records", "object": {"sha": TIP}}] if ref else [])
        self.put(f"repos/{SLUG}/git/commits/{TIP}", {"tree": {"sha": TREE}})
        entries, n = [], 0
        for (sha, started), files in self.runs_on_ref.items():
            for name, data in zip(("manifest.json", "test-results.jsonl"), files):
                n += 1
                blob = f"{n:040x}"
                entries.append({"path": f"runs/{sha}/{started}/{name}", "type": "blob", "sha": blob, "size": len(data)})
                self.put(f"repos/{SLUG}/git/blobs/{blob}", {"encoding": "base64", "content": base64.b64encode(data).decode()})
        self.put(f"repos/{SLUG}/git/trees/{TREE}", {"tree": entries, "truncated": truncated})

    def fetch(self, *extra):
        return tf.cli("fetch", self.books, self.out, "--today", tv.TODAY, "--since", "2026-11-13", *extra)

    def ingest(self, *extra):
        return ti.cli("ingest", self.books, self.out, *extra)


class FetchLocalTest(LocalBase):
    def test_local_runs_are_fetched_from_the_ref_booked_and_pass_check(self):
        self.run_on_ref(SHA_A, STARTED_A, manifest(SHA_A, STARTED_A), record(SHA_A))
        self.run_on_ref(SHA_B, STARTED_B, manifest(SHA_B, STARTED_B, event="pull_request", pr=7, head_branch="feat/x",
                                                  exit_code=1), record(SHA_B, fail=True))
        self.serve()
        code, out = self.fetch()
        self.assertEqual(code, 0, out)
        self.assertIn(f"{REPO} ({SLUG}, local-ci): local runs started since 2026-11-13\n", out)
        self.assertIn("fetched 2 runs (2 artifacts); listed 2;", out)
        self.assertNotIn("actions/runs", " ".join(self.endpoints()))
        m = json.loads(next(self.out.glob(f"{REPO}/*/manifest.json")).read_text())
        self.assertEqual((m["workflow"], m["run_attempt"]), ("local-ci", 1))
        code, out = self.ingest()
        self.assertEqual(code, 0, out)
        rows = ti.csv_rows(self.books / quality.RUNS)[1:]
        self.assertEqual([(r[3], r[4], r[11]) for r in rows if r[1] == REPO and r[4] == "local-ci"],
                         [("push", "local-ci", link(SHA_A, STARTED_A)), ("pull_request", "local-ci", link(SHA_B, STARTED_B))])
        failures = ti.csv_rows(self.books / quality.FAILURES)[1:]
        self.assertIn(link(SHA_B, STARTED_B), [f[6] for f in failures])
        self.assertEqual(tf.cli("check", self.books)[0], 0)
        code, out = self.fetch()
        self.assertIn("2 already booked", out)

    def test_a_record_that_names_an_actions_run_is_refused(self):
        self.run_on_ref(SHA_A, STARTED_A, manifest(SHA_A, STARTED_A), record(SHA_A, evidence=f"https://github.com/{SLUG}/actions/runs/1/attempts/1"))
        self.serve()
        self.fetch()
        code, out = self.ingest()
        self.assertEqual(code, 1, out)
        self.assertIn("header evidence of a local run must be empty", out)

    def test_a_manifest_that_disagrees_with_its_folder_fails_that_run_only(self):
        self.run_on_ref(SHA_A, STARTED_A, manifest(SHA_B, STARTED_A), record(SHA_A))
        self.run_on_ref(SHA_B, STARTED_B, manifest(SHA_B, STARTED_B, github="acme/other"), record(SHA_B))
        self.run_on_ref(SHA_A, "2026-11-14T11:00:00Z", manifest(SHA_A, "2026-11-14T11:00:00Z", event="schedule"), record(SHA_A))
        self.run_on_ref(SHA_B, "2026-11-14T13:00:00Z", manifest(SHA_B, "2026-11-14T13:00:00Z"), record(SHA_B))
        self.serve()
        code, out = self.fetch()
        self.assertEqual(code, 1, out)
        self.assertEqual(out.count("does not match its folder or the watch list"), 2, out)
        self.assertIn("bad event", out)
        self.assertIn("fetched 1 runs", out)

    def test_no_ref_is_no_runs_and_no_failure(self):
        self.serve(ref=False)
        code, out = self.fetch()
        self.assertEqual(code, 0, out)
        self.assertIn("fetched 0 runs (0 artifacts); listed 0;", out)

    def test_runs_before_since_are_not_fetched_and_a_truncated_tree_fails(self):
        self.run_on_ref(SHA_A, "2026-11-01T10:00:00Z", manifest(SHA_A, "2026-11-01T10:00:00Z"), record(SHA_A))
        self.serve()
        code, out = self.fetch()
        self.assertIn("listed 0;", out)
        self.serve(truncated=True)
        code, out = self.fetch()
        self.assertEqual(code, 1, out)
        self.assertIn("came back truncated", out)

    def test_a_push_to_another_branch_is_skipped(self):
        self.run_on_ref(SHA_A, STARTED_A, manifest(SHA_A, STARTED_A, head_branch="hotfix"), record(SHA_A))
        self.serve()
        code, out = self.fetch()
        self.assertIn(f"skipped {SHA_A[:12]}", out)
        self.assertIn("push to hotfix, not the default branch main", out)

    def test_volume_takes_the_weeks_newest_local_push(self):
        tv.write_csv(self.books / quality.VOLUME, quality.VOLUME_SCHEMA, [])
        late = "2026-11-08T20:00:00Z"
        self.run_on_ref(SHA_B, "2026-11-03T10:00:00Z", manifest(SHA_B, "2026-11-03T10:00:00Z"), record(SHA_B))
        self.run_on_ref(SHA_A, late, manifest(SHA_A, late), record(SHA_A))
        self.run_on_ref("e" * 40, "2026-11-08T21:00:00Z", manifest("e" * 40, "2026-11-08T21:00:00Z", event="pull_request", pr=3,
                                                                  head_branch="feat/y"), record("e" * 40))
        self.serve()
        (self.data / "api" / (f"repos/{SLUG}/tarball/{SHA_A}".replace("/", "__") + ".zip")).write_bytes(
            __import__("test_quality_volume").tarball({"src/a.py": b"x\n", "tests/test_a.py": b"y\n"}))
        code, out = tf.cli("fetch", self.books, self.out, "--today", tv.TODAY, "--since", "2026-11-02")
        self.assertEqual(code, 0, out)
        v = json.loads((self.out / REPO / "volume" / "2026-W45.json").read_text())
        self.assertEqual((v["sha"], v["evidence"]), (SHA_A, link(SHA_A, late)))
        code, out = self.ingest()
        self.assertEqual(code, 0, out)
        self.assertEqual([r[2] for r in ti.csv_rows(self.books / quality.VOLUME)[1:]], [SHA_A])


    def test_a_run_that_cannot_be_read_stops_the_volume_book_guessing_the_weeks_commit(self):
        tv.write_csv(self.books / quality.VOLUME, quality.VOLUME_SCHEMA, [])
        late = "2026-11-08T20:00:00Z"
        self.run_on_ref(SHA_B, "2026-11-03T10:00:00Z", manifest(SHA_B, "2026-11-03T10:00:00Z"), record(SHA_B))
        self.run_on_ref(SHA_A, late, b"not json", record(SHA_A))
        self.serve()
        code, out = tf.cli("fetch", self.books, self.out, "--today", tv.TODAY, "--since", "2026-11-02")
        self.assertEqual(code, 1, out)
        self.assertIn("volume: not counted this time", out)
        self.assertFalse((self.out / REPO / "volume").exists())

    def test_two_runs_started_the_same_second_are_fetched_one_per_fetch(self):
        self.run_on_ref(SHA_A, STARTED_A, manifest(SHA_A, STARTED_A), record(SHA_A))
        self.run_on_ref(SHA_B, STARTED_A, manifest(SHA_B, STARTED_A, event="pull_request", pr=4, head_branch="feat/z"), record(SHA_B))
        self.serve()
        code, out = self.fetch()
        self.assertIn("another run started the same second; fetched next time", out)
        self.assertEqual(self.ingest()[0], 0)
        import shutil
        shutil.rmtree(self.out)
        self.fetch()
        self.assertEqual(self.ingest()[0], 0)
        rows = [r for r in ti.csv_rows(self.books / quality.RUNS)[1:] if r[4] == "local-ci"]
        self.assertEqual(sorted(r[2] for r in rows), [SHA_A, SHA_B])

    def test_a_manifest_ingest_would_reject_fails_at_fetch(self):
        self.run_on_ref(SHA_A, STARTED_A, manifest(SHA_A, STARTED_A, completed="2026-11-14T09:00:00Z"), record(SHA_A))
        self.run_on_ref(SHA_B, STARTED_B, manifest(SHA_B, STARTED_B, event="pull_request", pr=None, head_branch=""), record(SHA_B))
        self.serve()
        code, out = self.fetch()
        self.assertEqual(code, 1, out)
        self.assertEqual(out.count("no head branch, or completed before it started"), 2, out)
        self.assertIn("fetched 0 runs", out)


class LocalLinkTest(tv.TempCase):
    def test_the_local_link_passes_check_ties_the_slug_and_is_caught_by_leak_check(self):
        b = tv.Builder((REPO, SLUG)).visibility(tv.STAMP, REPO, SLUG, "private")
        b.write(self.books, jobs=False)
        evidence = link(SHA_A, STARTED_A)
        with open(self.books / quality.RUNS, "a") as f:
            f.write(f"{STARTED_A},{REPO},{SHA_A},push,local-ci,3.12,1,0,0,10,0,{evidence}\n")
        self.assertEqual(tf.cli("check", self.books)[0], 0)
        books = quality.load(str(self.books))
        self.assertIn(SLUG, quality.repo_slugs(books)[REPO])
        post = self.tmp / "post.md"
        post.write_text(f"See {evidence} for the run.\n")
        code, out = tf.cli("leak-check", self.books, post)
        self.assertEqual(code, 1, out)
        for row in (f"{STARTED_A},{REPO},{SHA_A},push,ci,3.12,1,0,0,10,0,{evidence}\n",
                    f"{STARTED_B},{REPO},{SHA_B},push,local-ci,3.12,1,0,0,10,0,{link(SHA_A, STARTED_B)}\n",
                    f"{STARTED_B},{REPO},{SHA_B},push,local-ci,3.12,1,0,0,10,0,https://github.com/{SLUG}/actions/runs/5/attempts/1\n"):
            body = (self.books / quality.RUNS).read_text()
            (self.books / quality.RUNS).write_text(body + row)
            self.assertEqual(tf.cli("check", self.books)[0], 1, row)
            (self.books / quality.RUNS).write_text(body)
        for bad in (f"https://github.com/{SLUG}/commit/{SHA_A}#local-ci-yesterday", f"https://github.com/{SLUG}/commit/abc#local-ci-{STARTED_A}"):
            self.assertIsNone(quality._RUN_LINK.fullmatch(bad), bad)


if __name__ == "__main__":
    unittest.main()
