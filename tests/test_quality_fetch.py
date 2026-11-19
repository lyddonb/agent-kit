"""Tests for `quality.py fetch` (plugins/bstack/skills/qualitydirector/scripts/quality.py).

`fetch` asks GitHub through the `gh` CLI. These tests give it a fake `gh` (a small script that
serves canned API responses, captured from real `gh api` calls and trimmed, and records the
arguments it was called with), selected through QUALITY_GH. Nothing here touches the network or
reads the clock: "today" is passed with --today.
"""
import contextlib
import copy
import io
import importlib.util
import json
import os
import shutil
import stat
import sys
import tempfile
import unittest
import unittest.mock
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = Path(os.environ.get("QUALITY_SCRIPT")
              or ROOT / "plugins/bstack/skills/qualitydirector/scripts/quality.py")
API = ROOT / "tests/fixtures/quality/api"

spec = importlib.util.spec_from_file_location("quality", SCRIPT)
quality = importlib.util.module_from_spec(spec)
spec.loader.exec_module(quality)

WATCHED = "books/watched.csv"
TODAY = "2026-11-15"
FAKE_GH = f'''#!{sys.executable}
import json, os, sys
data = os.environ["FAKE_GH_DATA"]
args = sys.argv[1:]
with open(os.path.join(data, "calls.log"), "a") as log:
    log.write(json.dumps(args) + "\\n")
if args[:1] != ["api"]:
    sys.stderr.write("fake gh only does `api`\\n")
    sys.exit(2)
endpoint = [a for a in args[1:] if not a.startswith("-")][0]
base = os.path.join(data, "api", endpoint.split("?")[0].replace("/", "__"))
if os.path.exists(base + ".error"):
    sys.stderr.write(open(base + ".error").read())
    sys.exit(1)
for suffix in ("zip", "json"):
    if os.path.exists(base + "." + suffix):
        sys.stdout.buffer.write(open(base + "." + suffix, "rb").read())
        sys.exit(0)
sys.stderr.write("gh: Not Found (HTTP 404)\\n")
sys.exit(1)
'''


def cli(*argv) -> tuple[int, str]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        try:
            code = quality.main([str(a) for a in argv])
        except SystemExit as e:
            code = e.code
    return code, out.getvalue()


def dumps(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def tree(folder: Path) -> dict[str, bytes]:
    return {str(p.relative_to(folder)): p.read_bytes() for p in sorted(folder.rglob("*")) if p.is_file()}


def zip_of(members: dict[str, bytes]) -> bytes:
    import io as _io
    buffer = _io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in members.items():
            z.writestr(name, data)
    return buffer.getvalue()


def recorder_text(run_id: int, python: str = "3.12", github: str = "lyddonb/agentfiles", fail: bool = False) -> str:
    rows = [{"id": "t.A.test_a", "ms": 3, "outcome": "fail" if fail else "pass"}, {"id": "t.A.test_b", "ms": 4, "outcome": "pass"}]
    header = {"v": 1, "repo": "agentfiles", "sha": "f" * 40, "event": "pull_request", "workflow": "ci", "python": python,
              "os": "Linux", "started": "2026-11-14T10:00:01Z", "wall_ms": 1500, "exit_code": 1 if fail else 0,
              "complete": True, "tests": 2, "failed": int(fail), "skipped": 0,
              "evidence": f"https://github.com/{github}/actions/runs/{run_id}/attempts/1"}
    return "".join(dumps(r) + "\n" for r in [header] + rows)


REAL_RUN = json.loads((API / "run-agentfiles-43745332984.json").read_text())
REAL_ARTIFACT = json.loads((API / "artifacts-agentfiles-43745332984.json").read_text())["artifacts"][0]


def run_obj(run_id: int, **over) -> dict:
    """A run as the API reports it, from a real response. `over` may hold dotted keys (head_repository.full_name)."""
    run = copy.deepcopy(REAL_RUN)
    run.update(id=run_id, head_sha=f"{run_id:040x}", run_started_at="2026-11-14T10:00:00Z", created_at="2026-11-14T10:00:00Z",
               updated_at="2026-11-14T10:10:00Z", head_branch="feat/x")
    for key, value in over.items():
        node = run
        *path, last = key.split("__")
        for part in path:
            node = node[part]
        node[last] = value
    return run


def artifact_obj(artifact_id: int, name: str, **over) -> dict:
    artifact = dict(copy.deepcopy(REAL_ARTIFACT), id=artifact_id, name=name)
    artifact.update(over)
    return artifact


class FetchCase(unittest.TestCase):
    """A books folder that watches agentfiles, an empty output folder, and a fake gh."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.books = self.tmp / "books-repo"
        self.write_books("agentfiles,lyddonb/agentfiles,ci\n")
        self.out = self.tmp / "out"
        self.data = self.tmp / "data"
        (self.data / "api").mkdir(parents=True)
        self.gh = self.tmp / "bin" / "gh"
        self.gh.parent.mkdir()
        self.gh.write_text(FAKE_GH)
        self.gh.chmod(self.gh.stat().st_mode | stat.S_IXUSR)
        patcher = unittest.mock.patch.dict(os.environ, {"QUALITY_GH": str(self.gh), "FAKE_GH_DATA": str(self.data)})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.put("repos/lyddonb/agentfiles", {"full_name": "lyddonb/agentfiles", "default_branch": "main"})

    # --- the books
    def write_books(self, watched: str, runs: str = "") -> None:
        for rel, schema in quality.SCHEMAS.items():
            (self.books / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.books / rel).write_text(",".join(schema) + "\n")
        (self.books / WATCHED).write_text("repo,github,workflow\n" + watched)
        if runs:
            with open(self.books / quality.RUNS, "a") as f:
                f.write(runs)

    # --- the fake API
    def put(self, endpoint: str, value, suffix: str = "json") -> None:
        data = value if isinstance(value, bytes) else (value if isinstance(value, str) else dumps(value)).encode()
        (self.data / "api" / (endpoint.replace("/", "__") + "." + suffix)).write_bytes(data)

    def runs(self, *pages: list, repo: str = "lyddonb/agentfiles") -> None:
        """Serve the run listing as pages, the way `gh api --paginate` prints them: one object after another."""
        self.put(f"repos/{repo}/actions/runs", "".join(dumps({"total_count": sum(map(len, pages)), "workflow_runs": p}) for p in pages))

    def artifacts(self, run_id: int, *artifacts: dict, repo: str = "lyddonb/agentfiles") -> None:
        self.put(f"repos/{repo}/actions/runs/{run_id}/artifacts", dumps({"total_count": len(artifacts), "artifacts": list(artifacts)}))

    def archive(self, artifact: dict, members: dict[str, bytes], repo: str = "lyddonb/agentfiles") -> None:
        self.put(f"repos/{repo}/actions/artifacts/{artifact['id']}/zip", zip_of(members), "zip")

    def run_with_artifact(self, run_id: int, name: str = "test-results-agentfiles", python: str = "3.12", **over) -> dict:
        run = run_obj(run_id, **over)
        artifact = artifact_obj(run_id * 10, name)
        self.artifacts(run_id, artifact)
        self.archive(artifact, {"test-results.jsonl": recorder_text(run_id, python).encode()})
        return run

    def calls(self) -> list[list[str]]:
        log = self.data / "calls.log"
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    def endpoints(self) -> list[str]:
        return [next(a for a in call[1:] if not a.startswith("-")) for call in self.calls()]

    # --- the command
    def fetch(self, *extra) -> tuple[int, str]:
        return cli("fetch", self.books, self.out, "--today", TODAY, *extra)

    def manifest(self, run_id: int, repo: str = "agentfiles") -> dict:
        return json.loads((self.out / repo / str(run_id) / "manifest.json").read_text())


class ListingTest(FetchCase):
    def setUp(self):
        super().setUp()
        self.pull = self.run_with_artifact(101, event="pull_request")
        self.main = self.run_with_artifact(102, event="push", head_branch="main")
        self.dev = self.run_with_artifact(103, event="push", head_branch="dev")
        self.fork = self.run_with_artifact(104, event="pull_request", head_repository__full_name="evil/agentfiles")
        self.other = run_obj(105, name="release")
        self.runs([self.pull, self.main, self.other], [self.dev, self.fork])  # two pages

    def test_every_page_is_read_and_each_fetched_run_gets_a_manifest_and_its_artifacts(self):
        code, out = self.fetch()
        self.assertEqual(code, 0, out)
        self.assertEqual(sorted(p.name for p in (self.out / "agentfiles").iterdir()), ["101", "102"])
        for run_id in (101, 102):
            self.assertEqual((self.out / "agentfiles" / str(run_id) / "artifacts/test-results-agentfiles/test-results.jsonl").read_text(),
                             recorder_text(run_id))
        self.assertIn("fetched 2 runs (2 artifacts); listed 4;", out)

    def test_the_manifest_holds_only_what_the_api_reported(self):
        self.fetch()
        self.assertEqual(self.manifest(101), {
            "v": 1, "repo": "agentfiles", "github": "lyddonb/agentfiles", "run_id": 101, "run_attempt": 1, "workflow": "ci",
            "event": "pull_request", "head_sha": f"{101:040x}", "head_branch": "feat/x", "default_branch": "main",
            "started": "2026-11-14T10:00:00Z", "updated": "2026-11-14T10:10:00Z", "conclusion": "success", "fork": False})
        self.assertEqual(self.manifest(102)["event"], "push")
        self.assertEqual(self.manifest(102)["head_branch"], "main")

    def test_a_fork_run_is_listed_and_not_downloaded(self):
        code, out = self.fetch()
        self.assertEqual(code, 0, out)
        self.assertRegex(out, r"(?m)^\s+skipped 104: .*fork")
        self.assertFalse((self.out / "agentfiles" / "104").exists())
        self.assertFalse(any("/104" in e or "1040" in e for e in self.endpoints()), self.endpoints())
        self.assertIn("1 forks", out)

    def test_a_push_to_a_branch_that_is_not_the_default_is_skipped_and_the_default_branch_is_fetched(self):
        code, out = self.fetch()
        self.assertEqual(code, 0, out)
        self.assertRegex(out, r"(?m)^\s+skipped 103: push to dev, not the default branch main")
        self.assertFalse((self.out / "agentfiles" / "103").exists())
        self.assertFalse(any("/103" in e or "1030" in e for e in self.endpoints()))
        self.assertTrue((self.out / "agentfiles" / "102" / "manifest.json").exists())
        self.assertIn("1 pushes to a non-default branch", out)

    def test_a_pull_request_from_a_branch_of_the_repo_is_not_a_fork(self):
        self.fetch()
        self.assertIs(self.manifest(101)["fork"], False)

    def test_runs_of_another_workflow_are_not_listed_or_fetched(self):
        self.runs([run_obj(201, name="release"), self.pull])
        code, out = self.fetch()
        self.assertEqual(code, 0, out)
        self.assertFalse((self.out / "agentfiles" / "201").exists())
        self.assertIn("listed 1;", out)

    def test_only_artifacts_named_test_results_are_downloaded(self):
        run = run_obj(301)
        keep, coverage = artifact_obj(3010, "test-results-py3.13"), artifact_obj(3011, "coverage")
        self.artifacts(301, keep, coverage)
        self.archive(keep, {"test-results.jsonl": b"x\n"})
        self.runs([run])
        code, out = self.fetch()
        self.assertEqual(code, 0, out)
        self.assertEqual(sorted(p.name for p in (self.out / "agentfiles/301/artifacts").iterdir()), ["test-results-py3.13"])
        self.assertNotIn("repos/lyddonb/agentfiles/actions/artifacts/3011/zip", self.endpoints())

    def test_a_run_without_test_results_artifacts_is_noted_and_is_not_an_error(self):
        self.artifacts(101, artifact_obj(1010, "coverage"))
        self.runs([self.pull])
        code, out = self.fetch()
        self.assertEqual(code, 0, out)
        self.assertIn("1 without test-results artifacts", out)
        self.assertFalse((self.out / "agentfiles" / "101").exists())

    def test_the_calls_gh_gets(self):
        self.fetch()
        listing = [c for c in self.calls() if any("actions/runs?" in a for a in c)]
        self.assertEqual(listing, [["api", "--paginate", "repos/lyddonb/agentfiles/actions/runs?status=completed&per_page=100&created=%3E%3D2026-11-08"]])
        self.assertIn("repos/lyddonb/agentfiles", self.endpoints())
        self.assertIn("repos/lyddonb/agentfiles/actions/runs/101/artifacts?per_page=100", self.endpoints())
        self.assertIn("repos/lyddonb/agentfiles/actions/artifacts/1010/zip", self.endpoints())
        self.assertTrue(all(c[0] == "api" for c in self.calls()))


class FailureTest(FetchCase):
    def test_an_expired_artifact_is_reported_exits_1_and_the_others_are_fetched(self):
        good, gone = self.run_with_artifact(401), run_obj(402)
        self.artifacts(402, artifact_obj(4020, "test-results-agentfiles", expired=True))
        self.runs([good, gone])
        code, out = self.fetch()
        self.assertEqual(code, 1, out)
        self.assertRegex(out, r"(?m)^\s+FAILED 402: artifact test-results-agentfiles expired")
        self.assertTrue((self.out / "agentfiles/401/artifacts/test-results-agentfiles/test-results.jsonl").exists())
        self.assertIn("1 failed", out)
        self.assertNotIn("repos/lyddonb/agentfiles/actions/artifacts/4020/zip", self.endpoints())

    def test_one_expired_artifact_of_a_run_does_not_stop_the_run_s_others(self):
        run = run_obj(403)
        keep, gone = artifact_obj(4030, "test-results-py3.12"), artifact_obj(4031, "test-results-py3.13", expired=True)
        self.artifacts(403, keep, gone)
        self.archive(keep, {"test-results.jsonl": b"x\n"})
        self.runs([run])
        code, out = self.fetch()
        self.assertEqual(code, 1, out)
        self.assertEqual(sorted(p.name for p in (self.out / "agentfiles/403/artifacts").iterdir()), ["test-results-py3.12"])

    def test_a_download_that_fails_is_reported_and_the_next_run_is_fetched(self):
        bad, good = run_obj(411), self.run_with_artifact(412)
        artifact = artifact_obj(4110, "test-results-agentfiles")
        self.artifacts(411, artifact)
        (self.data / "api" / "repos__lyddonb__agentfiles__actions__artifacts__4110__zip.error").write_text("gh: HTTP 410: Gone\n")
        self.runs([bad, good])
        code, out = self.fetch()
        self.assertEqual(code, 1, out)
        self.assertRegex(out, r"(?m)^\s+FAILED 411: .*4110")
        self.assertTrue((self.out / "agentfiles/412/manifest.json").exists())
        self.assertFalse((self.out / "agentfiles/411/artifacts/test-results-agentfiles").exists())

    def test_a_listing_that_fails_is_reported_and_the_other_repos_are_fetched(self):
        self.write_books("agentfiles,lyddonb/agentfiles,ci\nledger,lyddonb/agent-ledger,test\n")
        self.put("repos/lyddonb/agent-ledger", {"default_branch": "main"})
        run = self.run_with_artifact(421)
        self.runs([run])
        (self.data / "api" / "repos__lyddonb__agent-ledger__actions__runs.error").write_text("gh: HTTP 500\n")
        code, out = self.fetch()
        self.assertEqual(code, 1, out)
        self.assertRegex(out, r"(?m)^\s+FAILED listing: .*HTTP 500")
        self.assertTrue((self.out / "agentfiles/421/manifest.json").exists())

    def test_a_response_that_is_not_json_is_a_failure_not_a_crash(self):
        self.put("repos/lyddonb/agentfiles/actions/runs", "<html>not the api</html>")
        code, out = self.fetch()
        self.assertEqual(code, 1, out)
        self.assertIn("FAILED listing", out)

    def test_a_run_without_a_start_time_is_reported(self):
        self.runs([run_obj(431, run_started_at=None)])
        code, out = self.fetch()
        self.assertEqual(code, 1, out)
        self.assertRegex(out, r"(?m)^\s+FAILED 431: .*run_started_at")

    def test_a_zip_with_names_that_climb_out_or_links_is_refused_and_nothing_lands_outside(self):
        run = run_obj(441)
        artifact = artifact_obj(4410, "test-results-agentfiles")
        self.artifacts(441, artifact)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as z:
            z.writestr("../../escape.jsonl", "x\n")
            z.writestr("/abs.jsonl", "x\n")
            z.writestr("a/../../up.jsonl", "x\n")
            link = zipfile.ZipInfo("link.jsonl")
            link.external_attr = (stat.S_IFLNK | 0o777) << 16
            z.writestr(link, "/etc/passwd")
            z.writestr("fine.jsonl", "ok\n")
        self.put(f"repos/lyddonb/agentfiles/actions/artifacts/4410/zip", buffer.getvalue(), "zip")
        self.runs([run])
        code, out = self.fetch()
        self.assertEqual(code, 1, out)
        self.assertFalse((self.tmp / "escape.jsonl").exists())
        self.assertFalse((self.out.parent / "escape.jsonl").exists())
        self.assertFalse((self.out / "agentfiles/441/artifacts/up.jsonl").exists())
        files = [str(p.relative_to(self.out)) for p in self.out.rglob("*") if p.is_file() or p.is_symlink()]
        self.assertEqual(sorted(f for f in files if f.endswith(".jsonl")), [])
        self.assertIn("unsafe", out)

    def test_a_zip_member_over_the_size_cap_is_refused(self):
        run = run_obj(451)
        artifact = artifact_obj(4510, "test-results-agentfiles")
        self.artifacts(451, artifact)
        self.archive(artifact, {"test-results.jsonl": b"x" * ((8 << 20) + 1)})
        self.runs([run])
        code, out = self.fetch()
        self.assertEqual(code, 1, out)
        self.assertRegex(out, r"(?m)^\s+FAILED 451: .*larger than 8 MB")

    def test_an_artifact_name_that_is_not_a_plain_name_is_not_downloaded(self):
        run = run_obj(461)
        self.artifacts(461, artifact_obj(4610, "test-results-../../x"), artifact_obj(4611, "test-results-a b"))
        self.runs([run])
        code, out = self.fetch()
        self.assertEqual(code, 1, out)
        self.assertEqual(out.count("FAILED 461"), 2)
        self.assertFalse(any("zip" in e for e in self.endpoints()))


def big_members(*sizes: int) -> dict[str, bytes]:
    return {f"m{i}.jsonl": b"x" * size for i, size in enumerate(sizes)}


class UnpackedSizeCapTest(FetchCase):
    """Item 1: what an archive unpacks to is capped per archive and per run, counted while streaming."""
    MB = 1 << 20

    def serve(self, run_id: int, *archives: dict[str, bytes]) -> dict:
        run = run_obj(run_id)
        arts = [artifact_obj(run_id * 100 + i, f"test-results-a{i}") for i in range(len(archives))]
        self.artifacts(run_id, *arts)
        for art, members in zip(arts, archives):
            self.archive(art, members)
        return run

    def tree_files(self) -> list[str]:
        return [str(p) for p in self.out.rglob("*") if p.is_file()]

    def test_an_archive_unpacking_to_exactly_16_mb_is_fetched(self):
        self.runs([self.serve(801, big_members(8 * self.MB, 8 * self.MB))])
        code, out = self.fetch()
        self.assertEqual(code, 0, out)
        self.assertEqual(len([f for f in self.tree_files() if f.endswith(".jsonl")]), 2)

    def test_an_archive_unpacking_one_byte_past_16_mb_fails_its_run_and_leaves_no_files(self):
        self.runs([self.serve(802, big_members(8 * self.MB, 8 * self.MB, 1))])
        code, out = self.fetch()
        self.assertEqual(code, 1, out)
        self.assertRegex(out, r"(?m)^\s+FAILED 802: .*16 MB")
        self.assertEqual(self.tree_files(), [])
        self.assertEqual([p for p in self.out.rglob("*.partial")], [])

    def test_a_run_unpacking_to_exactly_32_mb_is_fetched_and_one_byte_more_fails_the_run(self):
        full = big_members(8 * self.MB, 8 * self.MB)
        self.runs([self.serve(804, full, full)])
        code, out = self.fetch()
        self.assertEqual(code, 0, out)
        self.assertEqual(len([f for f in self.tree_files() if f.endswith(".jsonl")]), 4)
        shutil.rmtree(self.out)
        self.runs([self.serve(805, full, full, {"one.jsonl": b"x"}), self.serve(806, {"ok.jsonl": recorder_text(806).encode()})])
        code, out = self.fetch()
        self.assertEqual(code, 1, out)
        self.assertRegex(out, r"(?m)^\s+FAILED 805: .*32 MB")
        self.assertFalse((self.out / "agentfiles" / "805").exists(), self.tree_files())
        self.assertTrue((self.out / "agentfiles" / "806" / "manifest.json").exists(), "the other runs are still fetched")

    def test_twelve_artifacts_are_fetched_and_thirteen_fail_the_run_before_any_download(self):
        small = {"t.jsonl": recorder_text(1).encode()}
        self.runs([self.serve(807, *[small] * 12)])
        code, out = self.fetch()
        self.assertEqual(code, 0, out)
        shutil.rmtree(self.out)
        before = len(self.calls())
        self.runs([self.serve(808, *[small] * 13)])
        code, out = self.fetch()
        self.assertEqual(code, 1, out)
        self.assertRegex(out, r"(?m)^\s+FAILED 808: .*12")
        self.assertFalse((self.out / "agentfiles" / "808").exists())
        self.assertFalse(any("zip" in e for e in self.endpoints()[before:]))


class WindowAndStatusTest(FetchCase):
    def test_a_run_that_is_not_completed_is_skipped_without_a_manifest(self):
        pending = self.run_with_artifact(811, status="in_progress")
        done = self.run_with_artifact(812)
        self.runs([pending, done])
        code, out = self.fetch()
        self.assertEqual(code, 0, out)
        self.assertRegex(out, r"(?m)^\s+skipped 811: .*not completed")
        self.assertFalse((self.out / "agentfiles" / "811").exists())
        self.assertTrue((self.out / "agentfiles" / "812" / "manifest.json").exists())

    def test_a_run_whose_head_repository_is_null_is_a_fork_and_nothing_is_downloaded(self):
        run = self.run_with_artifact(813, head_repository=None)
        self.runs([run])
        code, out = self.fetch()
        self.assertEqual(code, 0, out)
        self.assertRegex(out, r"(?m)^\s+skipped 813: fork")
        self.assertIn("1 forks", out)
        self.assertFalse((self.out / "agentfiles" / "813").exists())
        self.assertFalse(any("8130" in e or "813/" in e for e in self.endpoints()), self.endpoints())


class SinceTest(FetchCase):
    def listing_call(self) -> str:
        return next(e for e in self.endpoints() if "actions/runs?" in e)

    def test_without_since_it_is_seven_days_before_today(self):
        self.runs([])
        self.fetch()
        self.assertTrue(self.listing_call().endswith("created=%3E%3D2026-11-08"), self.listing_call())

    def test_since_defaults_to_three_days_before_the_latest_started_in_the_books_for_that_repo(self):
        runs = ("2026-11-10T10:00:00Z,agentfiles,{s},push,ci,3.12,1,0,0,1,0,https://github.com/lyddonb/agentfiles/actions/runs/1/attempts/1\n"
                "2026-11-12T23:59:59Z,agentfiles,{s},push,ci,3.12,1,0,0,1,0,https://github.com/lyddonb/agentfiles/actions/runs/2/attempts/1\n"
                "2026-11-14T10:00:00Z,other,{s},push,ci,3.12,1,0,0,1,0,https://github.com/lyddonb/other/actions/runs/3/attempts/1\n").format(s="a" * 40)
        self.write_books("agentfiles,lyddonb/agentfiles,ci\n", runs)
        self.runs([])
        code, out = self.fetch()
        self.assertEqual(code, 0, out)
        self.assertTrue(self.listing_call().endswith("created=%3E%3D2026-11-09"), self.listing_call())

    def test_since_wins(self):
        self.runs([])
        self.fetch("--since", "2026-10-01")
        self.assertTrue(self.listing_call().endswith("created=%3E%3D2026-10-01"), self.listing_call())

    def test_the_default_is_per_repo(self):
        runs = "2026-11-12T10:00:00Z,agentfiles,{s},push,ci,3.12,1,0,0,1,0,https://github.com/lyddonb/agentfiles/actions/runs/2/attempts/1\n".format(s="a" * 40)
        self.write_books("agentfiles,lyddonb/agentfiles,ci\nledger,lyddonb/agent-ledger,test\n", runs)
        self.runs([])
        self.runs([], repo="lyddonb/agent-ledger")
        self.put("repos/lyddonb/agent-ledger", {"default_branch": "main"})
        self.fetch()
        listings = [e for e in self.endpoints() if "actions/runs?" in e]
        self.assertEqual([e.split("created=")[1] for e in listings], ["%3E%3D2026-11-09", "%3E%3D2026-11-08"])

    def test_a_bad_since_is_a_usage_error(self):
        for bad in ("yesterday", "2026-13-01", "2026-11-1", "20261101"):
            with self.subTest(bad):
                self.assertEqual(self.fetch("--since", bad)[0], 2)
        self.assertEqual(cli("fetch", self.books, self.out, "--today", "tomorrow")[0], 2)
        self.assertEqual(self.calls(), [])


class WhatIsAlreadyBookedTest(FetchCase):
    BOOKED = ("2026-11-14T10:00:00Z,agentfiles,{s},pull_request,ci,3.12,2,0,0,1500,0,"
              "https://github.com/lyddonb/agentfiles/actions/runs/{run}/attempts/1\n")

    def test_a_run_whose_every_artifact_is_booked_is_skipped_without_a_download(self):
        run = self.run_with_artifact(501)
        self.write_books("agentfiles,lyddonb/agentfiles,ci\n", self.BOOKED.format(s="a" * 40, run=501))
        self.runs([run, self.run_with_artifact(502)])
        code, out = self.fetch("--since", "2026-11-01")
        self.assertEqual(code, 0, out)
        self.assertRegex(out, r"(?m)^\s+skipped 501: already booked")
        self.assertFalse((self.out / "agentfiles/501").exists())
        self.assertTrue((self.out / "agentfiles/502/manifest.json").exists())
        self.assertNotIn("repos/lyddonb/agentfiles/actions/artifacts/5010/zip", self.endpoints())
        self.assertIn("1 already booked", out)

    def test_a_run_with_more_artifacts_than_booked_rows_is_fetched(self):
        run = run_obj(511)
        a, b = artifact_obj(5110, "test-results-py3.12"), artifact_obj(5111, "test-results-py3.13")
        self.artifacts(511, a, b)
        self.archive(a, {"test-results.jsonl": b"x\n"})
        self.archive(b, {"test-results.jsonl": b"x\n"})
        self.write_books("agentfiles,lyddonb/agentfiles,ci\n", self.BOOKED.format(s="a" * 40, run=511))
        self.runs([run])
        code, out = self.fetch("--since", "2026-11-01")
        self.assertEqual(code, 0, out)
        self.assertEqual(len(list((self.out / "agentfiles/511/artifacts").iterdir())), 2)

    def test_another_attempt_is_not_booked(self):
        run = self.run_with_artifact(521, run_attempt=2)
        self.write_books("agentfiles,lyddonb/agentfiles,ci\n", self.BOOKED.format(s="a" * 40, run=521))  # attempt 1 only
        self.runs([run])
        code, out = self.fetch("--since", "2026-11-01")
        self.assertEqual(code, 0, out)
        self.assertTrue((self.out / "agentfiles/521/manifest.json").exists())
        self.assertEqual(self.manifest(521)["run_attempt"], 2)


class UsageTest(FetchCase):
    def test_fetch_never_writes_inside_the_books_folder(self):
        run = self.run_with_artifact(601)
        self.runs([run])
        before = tree(self.books)
        code, out = self.fetch()
        self.assertEqual(code, 0, out)
        self.assertEqual(tree(self.books), before)
        self.assertEqual(sorted(p.name for p in self.books.iterdir()), ["books"])

    def test_an_output_folder_inside_the_books_folder_is_refused(self):
        before = tree(self.books)
        for inside in (self.books / "out", self.books / "books", self.books, self.books / "x" / ".." / "y"):
            with self.subTest(inside):
                code, out = cli("fetch", self.books, inside, "--today", TODAY)
                self.assertEqual(code, 2, out)
                self.assertIn("inside the books folder", out)
        self.assertEqual(tree(self.books), before)
        self.assertEqual(self.calls(), [])

    def test_an_output_folder_that_is_the_books_folder_through_a_link_is_refused(self):
        link = self.tmp / "link"
        link.symlink_to(self.books, target_is_directory=True)
        self.assertEqual(cli("fetch", self.books, link / "out", "--today", TODAY)[0], 2)

    def test_gh_is_taken_from_QUALITY_GH_or_else_PATH(self):
        self.runs([self.run_with_artifact(611)])
        with unittest.mock.patch.dict(os.environ, {"PATH": str(self.gh.parent)}):
            os.environ.pop("QUALITY_GH")
            code, out = self.fetch()
        self.assertEqual(code, 0, out)
        self.assertTrue((self.out / "agentfiles/611/manifest.json").exists())

    def test_a_missing_gh_is_a_usage_error(self):
        with unittest.mock.patch.dict(os.environ, {"QUALITY_GH": str(self.tmp / "nope")}):
            code, out = self.fetch()
        self.assertEqual(code, 2, out)
        self.assertIn("gh", out)
        with unittest.mock.patch.dict(os.environ, {"PATH": str(self.tmp / "empty")}):
            os.environ.pop("QUALITY_GH")
            self.assertEqual(self.fetch()[0], 2)
        self.assertFalse(self.out.exists())

    def test_usage_errors_exit_2(self):
        self.assertEqual(cli("fetch", self.tmp / "nope", self.out)[0], 2)
        self.assertEqual(cli("fetch", self.books)[0], 2)
        self.assertEqual(self.fetch("--repo", "nope")[0], 2)
        (self.books / WATCHED).unlink()
        code, out = self.fetch()
        self.assertEqual(code, 1, out)
        self.assertIn("books/watched.csv:1: missing file", out)
        self.assertEqual(self.calls(), [])

    def test_repo_limits_the_fetch_to_one_watched_repo(self):
        self.write_books("agentfiles,lyddonb/agentfiles,ci\nledger,lyddonb/agent-ledger,test\n")
        self.put("repos/lyddonb/agent-ledger", {"default_branch": "main"})
        self.runs([self.run_with_artifact(621)])
        self.runs([], repo="lyddonb/agent-ledger")
        code, out = self.fetch("--repo", "agentfiles")
        self.assertEqual(code, 0, out)
        self.assertFalse(any("agent-ledger" in e for e in self.endpoints()))

    def test_a_repo_that_is_not_watched_is_never_asked_about(self):
        self.write_books("")
        code, out = self.fetch()
        self.assertEqual(code, 0, out)
        self.assertEqual(self.calls(), [])

    def test_hostile_text_from_the_api_is_never_printed_raw(self):
        self.runs([run_obj(631, head_branch="dev\x1b[2J", event="push")])
        code, out = self.fetch()
        self.assertEqual(code, 0, out)
        self.assertNotIn("\x1b", out)


class TwoRoundsTest(FetchCase):
    """fetch, then ingest into the same books, then again: the second round changes nothing."""

    def test_fetch_then_ingest_books_the_runs_and_a_second_round_changes_nothing(self):
        passing, failing = self.run_with_artifact(701, event="pull_request"), run_obj(702, event="push", head_branch="main")
        art = artifact_obj(7020, "test-results-agentfiles")
        self.artifacts(702, art)
        self.archive(art, {"test-results.jsonl": recorder_text(702, fail=True).encode()})
        self.runs([passing, failing])
        code, out = self.fetch()
        self.assertEqual(code, 0, out)
        code, out = cli("ingest", self.books, self.out)
        self.assertEqual(code, 0, out)
        self.assertIn("booked 2 runs, 1 failures", out)
        self.assertEqual(cli("check", self.books)[0], 0)
        after_first = tree(self.books)
        first_calls = len(self.calls())

        shutil.rmtree(self.out)
        code, out = self.fetch("--since", "2026-11-01")
        self.assertEqual(code, 0, out)
        self.assertEqual(out.count("already booked"), 3)  # two runs, and the totals line
        self.assertEqual(tree(self.out), {})
        code, out = cli("ingest", self.books, self.out)
        self.assertEqual(code, 0, out)
        self.assertEqual(tree(self.books), after_first)
        self.assertGreater(len(self.calls()), first_calls)

    def test_a_refetch_of_a_run_rewrites_the_same_bytes(self):
        self.runs([self.run_with_artifact(711)])
        self.fetch()
        before = tree(self.out)
        self.assertEqual(self.fetch()[0], 0)
        self.assertEqual(tree(self.out), before)

    def test_the_summary_after_ingest_names_the_failure_on_push(self):
        failing = run_obj(721, event="push", head_branch="main")
        art = artifact_obj(7210, "test-results-agentfiles")
        self.artifacts(721, art)
        self.archive(art, {"test-results.jsonl": recorder_text(721, fail=True).encode()})
        self.runs([failing])
        self.fetch()
        cli("ingest", self.books, self.out)
        code, out = cli("summary", self.books, "--json")
        repo = json.loads(out)["repos"]["agentfiles"]
        self.assertEqual([f["test_id"] for f in repo["failed_on_main"]], ["t.A.test_a"])


def job_obj(job_id: int, name: str = "validate", **over) -> dict:
    """A job as the Actions API reports it (shape from a real answer), with three steps."""
    job = {"id": job_id, "run_id": 1, "name": name, "status": "completed", "conclusion": "success",
           "created_at": "2026-11-14T10:00:01Z", "started_at": "2026-11-14T10:00:04Z", "completed_at": "2026-11-14T10:01:10Z",
           "html_url": "https://example.invalid/job", "labels": ["ubuntu-latest"],
           "steps": [{"name": f"step {n}", "status": "completed", "conclusion": "success", "number": n,
                      "started_at": f"2026-11-14T10:00:{4 + n:02d}Z", "completed_at": f"2026-11-14T10:00:{5 + n:02d}Z"} for n in (1, 2, 3)]}
    job.update(over)
    return job


class JobsTest(FetchCase):
    JOBS_ENDPOINT = "repos/lyddonb/agentfiles/actions/runs/{run}/attempts/1/jobs?per_page=100"

    def adopt(self, header: str = "started,repo,evidence\n", rows: str = "") -> None:
        (self.books / "books/jobs.csv").write_text(header + rows)

    def serve_jobs(self, run_id: int, *jobs: dict, pages: int = 1) -> None:
        per = max(1, -(-len(jobs) // pages))
        chunks = [list(jobs[i:i + per]) for i in range(0, len(jobs), per)] or [[]]
        self.put(f"repos/lyddonb/agentfiles/actions/runs/{run_id}/attempts/1/jobs",
                 "".join(dumps({"total_count": len(jobs), "jobs": c}) for c in chunks))

    def jobs_file(self, run_id: int) -> dict:
        return json.loads((self.out / "agentfiles" / str(run_id) / "jobs.json").read_text())

    def jobs_calls(self) -> list[str]:
        return [e for e in self.endpoints() if "/attempts/" in e]

    def test_without_jobs_csv_nothing_about_jobs_is_called_written_or_printed(self):
        run = self.run_with_artifact(601, event="pull_request")
        self.serve_jobs(601, job_obj(6010))
        self.runs([run, run_obj(602)])
        self.artifacts(602, artifact_obj(6020, "coverage"))
        code, out = self.fetch()
        self.assertEqual(code, 0, out)
        self.assertEqual(self.jobs_calls(), [])
        self.assertEqual(sorted(tree(self.out)), ["agentfiles/601/artifacts/test-results-agentfiles/test-results.jsonl", "agentfiles/601/manifest.json"])
        self.assertEqual(out, "agentfiles (lyddonb/agentfiles, ci): runs created since 2026-11-08\n"
                              "  fetched 601: pull_request feat/x attempt 1, 1 artifact\n"
                              "fetched 1 runs (1 artifacts); listed 2; skipped 0 forks, 0 pushes to a non-default branch, "
                              "0 already booked, 1 without test-results artifacts; 0 failed\n")

    def test_a_jobs_csv_without_an_evidence_column_is_a_usage_error_and_nothing_is_called(self):
        self.adopt(header="started,repo\n")
        self.runs([self.run_with_artifact(601)])
        code, out = self.fetch()
        self.assertEqual(code, 2, out)
        self.assertIn("evidence", out)
        self.assertEqual(self.calls(), [])

    def test_a_run_with_an_artifact_gets_the_artifact_the_manifest_and_jobs_json(self):
        self.adopt()
        self.runs([self.run_with_artifact(601, event="pull_request")])
        self.serve_jobs(601, job_obj(6012, "lint"), job_obj(6011, "validate"))
        code, out = self.fetch()
        self.assertEqual(code, 0, out)
        self.assertEqual(sorted(tree(self.out)), ["agentfiles/601/artifacts/test-results-agentfiles/test-results.jsonl",
                                                  "agentfiles/601/jobs.json", "agentfiles/601/manifest.json"])
        steps = [{"number": n, "name": f"step {n}", "conclusion": "success",
                  "started": f"2026-11-14T10:00:{4 + n:02d}Z", "completed": f"2026-11-14T10:00:{5 + n:02d}Z"} for n in (1, 2, 3)]
        job = {"conclusion": "success", "created": "2026-11-14T10:00:01Z", "started": "2026-11-14T10:00:04Z",
               "completed": "2026-11-14T10:01:10Z", "steps": steps}
        self.assertEqual(self.jobs_file(601), {"v": 1, "run_id": 601, "run_attempt": 1,
                                               "jobs": [dict(job, id=6011, name="validate"), dict(job, id=6012, name="lint")]})
        self.assertIn("  fetched 601: pull_request feat/x attempt 1, 1 artifact, 2 jobs\n", out)
        self.assertIn("0 without test-results artifacts; 1 runs with jobs (2 jobs); 0 failed\n", out)

    def test_a_run_without_artifacts_still_gets_the_manifest_and_jobs_json(self):
        self.adopt()
        self.artifacts(601, artifact_obj(6010, "coverage"))
        self.serve_jobs(601, job_obj(6011))
        self.runs([run_obj(601)])
        code, out = self.fetch()
        self.assertEqual(code, 0, out)
        self.assertEqual(sorted(tree(self.out)), ["agentfiles/601/jobs.json", "agentfiles/601/manifest.json"])
        self.assertEqual(self.manifest(601)["run_id"], 601)
        self.assertIn("  fetched 601: jobs only (1 job)\n", out)
        self.assertIn("1 without test-results artifacts; 1 runs with jobs (1 jobs); 0 failed\n", out)

    def test_a_run_whose_test_record_is_booked_but_not_its_jobs_gets_jobs_without_artifacts(self):
        self.adopt()
        run = self.run_with_artifact(601)
        self.write_books("agentfiles,lyddonb/agentfiles,ci\n", WhatIsAlreadyBookedTest.BOOKED.format(s="a" * 40, run=601))
        self.serve_jobs(601, job_obj(6011))
        self.runs([run])
        code, out = self.fetch("--since", "2026-11-01")
        self.assertEqual(code, 0, out)
        self.assertEqual(sorted(tree(self.out)), ["agentfiles/601/jobs.json", "agentfiles/601/manifest.json"])
        self.assertIn("1 already booked", out)
        self.assertIn("  fetched 601: jobs only (1 job)\n", out)
        self.assertNotIn("repos/lyddonb/agentfiles/actions/artifacts/6010/zip", self.endpoints())

    def test_a_run_whose_evidence_is_in_jobs_csv_is_not_asked_about_its_jobs(self):
        link = "https://github.com/lyddonb/agentfiles/actions/runs/601/attempts/1"
        self.adopt(header="evidence,started\n", rows=f"{link},2026-11-14T10:00:00Z\nshort\n")
        self.serve_jobs(601, job_obj(6011))
        self.serve_jobs(602, job_obj(6021))
        self.runs([self.run_with_artifact(601), self.run_with_artifact(602)])
        code, out = self.fetch()
        self.assertEqual(code, 0, out)
        self.assertEqual(self.jobs_calls(), [self.JOBS_ENDPOINT.format(run=602)])
        self.assertFalse((self.out / "agentfiles/601/jobs.json").exists())
        self.assertTrue((self.out / "agentfiles/601/manifest.json").exists())
        self.assertTrue((self.out / "agentfiles/602/jobs.json").exists())

    def test_a_fork_and_a_push_to_a_non_default_branch_get_nothing(self):
        self.adopt()
        fork = self.run_with_artifact(601, head_repository__full_name="evil/agentfiles")
        push = self.run_with_artifact(602, event="push", head_branch="dev")
        self.serve_jobs(601, job_obj(6011))
        self.serve_jobs(602, job_obj(6021))
        self.runs([fork, push])
        code, out = self.fetch()
        self.assertEqual(code, 0, out)
        self.assertEqual(self.jobs_calls(), [])
        self.assertFalse(self.out.exists() and any(self.out.rglob("*.json")))
        self.assertIn("0 runs with jobs (0 jobs)", out)

    def test_skipped_jobs_and_cancelled_steps_are_written_as_reported_with_empty_text_for_null(self):
        self.adopt()
        skipped = job_obj(6011, "release", conclusion="skipped", steps=[])
        cancelled = job_obj(6012, "tests", conclusion="cancelled", started_at=None, completed_at=None)
        del cancelled["created_at"]
        cancelled["steps"][2].update(conclusion=None, completed_at=None)
        cancelled["steps"][1].update(conclusion="cancelled")
        self.artifacts(601)
        self.serve_jobs(601, cancelled, skipped)
        self.runs([run_obj(601)])
        code, out = self.fetch()
        self.assertEqual(code, 0, out)
        jobs = self.jobs_file(601)["jobs"]
        self.assertEqual([j["id"] for j in jobs], [6011, 6012])
        self.assertEqual((jobs[0]["conclusion"], jobs[0]["steps"]), ("skipped", []))
        self.assertEqual((jobs[1]["created"], jobs[1]["started"], jobs[1]["completed"], jobs[1]["conclusion"]), ("", "", "", "cancelled"))
        self.assertEqual([(s["conclusion"], s["completed"]) for s in jobs[1]["steps"][1:]], [("cancelled", "2026-11-14T10:00:07Z"), ("", "")])

    def test_names_are_stored_as_they_are_and_printed_only_escaped(self):
        self.adopt()
        evil = "x\x1b[31m\nFAKE"
        self.artifacts(601)
        self.serve_jobs(601, job_obj(6011, evil))
        self.put("repos/lyddonb/agentfiles/actions/runs/602/attempts/1/jobs", dumps({"jobs": [job_obj(6021, 5)]}))
        self.artifacts(602)
        self.runs([run_obj(601), run_obj(602)])
        code, out = self.fetch()
        self.assertEqual(code, 1, out)
        self.assertEqual(self.jobs_file(601)["jobs"][0]["name"], evil)
        self.assertNotIn("\x1b", out)

    def test_a_failed_jobs_call_fails_the_run_s_jobs_only_and_its_artifacts_are_still_fetched(self):
        self.adopt()
        self.runs([self.run_with_artifact(601)])  # no jobs answer: the fake gh says 404
        code, out = self.fetch()
        self.assertEqual(code, 1, out)
        self.assertRegex(out, r"(?m)^  FAILED 601: jobs .*404")
        self.assertEqual(sorted(tree(self.out)), ["agentfiles/601/artifacts/test-results-agentfiles/test-results.jsonl", "agentfiles/601/manifest.json"])
        self.assertIn("  fetched 601: pull_request feat/x attempt 1, 1 artifact\n", out)
        self.assertIn("0 runs with jobs (0 jobs); 1 failed", out)

    def test_a_failed_jobs_call_for_a_run_without_artifacts_leaves_nothing_behind(self):
        self.adopt()
        self.artifacts(601)
        self.runs([run_obj(601), run_obj(602)])
        self.serve_jobs(602, job_obj(6021))
        self.artifacts(602)
        code, out = self.fetch()
        self.assertEqual(code, 1, out)
        self.assertFalse((self.out / "agentfiles/601").exists())
        self.assertTrue((self.out / "agentfiles/602/jobs.json").exists())

    def test_a_malformed_job_or_step_fails_the_run_s_jobs_whole(self):
        bad_job = [job_obj(6011), job_obj("7")]
        no_name = [job_obj(6011), {k: v for k, v in job_obj(6012).items() if k != "name"}]
        bad_step = job_obj(6013)
        bad_step["steps"][1]["number"] = "2"
        nameless_step = job_obj(6014)
        del nameless_step["steps"][0]["name"]
        for n, jobs in enumerate([bad_job, no_name, [bad_step], [nameless_step]], start=1):
            with self.subTest(n=n):
                shutil.rmtree(self.out, ignore_errors=True)
                self.artifacts(601)
                self.serve_jobs(601, *jobs)
                self.adopt()
                self.runs([run_obj(601)])
                code, out = self.fetch()
                self.assertEqual(code, 1, out)
                self.assertRegex(out, r"(?m)^  FAILED 601: jobs ")
                self.assertFalse((self.out / "agentfiles/601").exists())

    def test_sixty_four_jobs_are_stored_and_sixty_five_are_refused_whole(self):
        self.adopt()
        self.artifacts(601)
        self.serve_jobs(601, *[job_obj(6000 + n) for n in range(64)], pages=2)
        self.artifacts(602)
        self.serve_jobs(602, *[job_obj(7000 + n) for n in range(65)], pages=2)
        self.runs([run_obj(601), run_obj(602)])
        code, out = self.fetch()
        self.assertEqual(code, 1, out)
        self.assertEqual(len(self.jobs_file(601)["jobs"]), 64)
        self.assertRegex(out, r"(?m)^  FAILED 602: jobs .*64")
        self.assertFalse((self.out / "agentfiles/602").exists())

    def test_a_hundred_steps_are_stored_and_a_hundred_and_one_refuse_the_run_whole(self):
        def steps(count):
            return [{"name": f"s{n}", "conclusion": "success", "number": n, "started_at": None, "completed_at": None} for n in range(count, 0, -1)]
        self.adopt()
        self.artifacts(601)
        self.serve_jobs(601, job_obj(6011, steps=steps(100)))
        self.artifacts(602)
        self.serve_jobs(602, job_obj(7011), job_obj(7012, steps=steps(101)))
        self.runs([run_obj(601), run_obj(602)])
        code, out = self.fetch()
        self.assertEqual(code, 1, out)
        self.assertEqual([s["number"] for s in self.jobs_file(601)["jobs"][0]["steps"]], list(range(1, 101)))
        self.assertRegex(out, r"(?m)^  FAILED 602: jobs .*100")
        self.assertFalse((self.out / "agentfiles/602").exists())

    def test_a_jobs_answer_without_a_jobs_list_is_a_failure_not_an_empty_run(self):
        self.adopt()
        self.artifacts(601)
        self.put("repos/lyddonb/agentfiles/actions/runs/601/attempts/1/jobs", dumps({"message": "odd"}))
        self.runs([run_obj(601)])
        code, out = self.fetch()
        self.assertEqual(code, 1, out)
        self.assertRegex(out, r"(?m)^  FAILED 601: jobs ")
        self.assertFalse((self.out / "agentfiles/601").exists())

    def test_a_run_with_too_many_test_artifacts_fails_but_keeps_the_jobs_it_stored(self):
        self.adopt()
        run = run_obj(601)
        self.artifacts(601, *[artifact_obj(6100 + n, f"test-results-{n}") for n in range(13)])
        self.serve_jobs(601, job_obj(6011))
        self.runs([run])
        code, out = self.fetch()
        self.assertEqual(code, 1, out)
        self.assertRegex(out, r"(?m)^  FAILED 601: has 13 test-results artifacts")
        self.assertEqual(sorted(tree(self.out)), ["agentfiles/601/jobs.json", "agentfiles/601/manifest.json"])

    def test_exactly_one_gh_call_is_added_per_run(self):
        runs = [self.run_with_artifact(601), self.run_with_artifact(602)]
        self.runs(runs)
        self.fetch()
        before = len(self.calls())
        (self.data / "calls.log").unlink()
        shutil.rmtree(self.out)
        self.adopt()
        self.serve_jobs(601, job_obj(6011))
        self.serve_jobs(602, job_obj(6021))
        code, out = self.fetch()
        self.assertEqual(code, 0, out)
        self.assertEqual(len(self.calls()), before + 2)
        self.assertEqual(sorted(self.jobs_calls()), [self.JOBS_ENDPOINT.format(run=601), self.JOBS_ENDPOINT.format(run=602)])
        self.assertTrue(all(c[1] == "--paginate" for c in self.calls() if any("/jobs" in a for a in c)))


if __name__ == "__main__":
    unittest.main()
