"""Tests for the state-machines spec checker (plugins/bstack/skills/state-machines/scripts/check-machine.py)."""
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "plugins/bstack/skills/state-machines"
SCRIPT = SKILL / "scripts/check-machine.py"
# The documented example is the good fixture, so the doc and the checker can't drift.
GOOD = (SKILL / "references/spec-format.md").read_text().split("```markdown\n", 1)[1].rsplit("\n```", 1)[0]

spec = importlib.util.spec_from_file_location("check_machine", SCRIPT)
cm = importlib.util.module_from_spec(spec)
sys.modules["check_machine"] = cm  # dataclasses look the module up while the class is built
spec.loader.exec_module(cm)


def problems(text: str) -> list[str]:
    m, syntax = cm.parse(text)
    return [msg for _, msg in syntax + cm.check(m)]


def drop_row(text: str, row_start: str) -> str:
    lines = text.splitlines()
    kept = [ln for ln in lines if not ln.startswith(row_start)]
    assert len(kept) == len(lines) - 1, f"expected exactly one row starting {row_start!r}"
    return "\n".join(kept)


class CheckMachineTest(unittest.TestCase):
    def assertProblem(self, text: str, fragment: str):
        found = problems(text)
        self.assertTrue(any(fragment in p for p in found), f"{fragment!r} not in {found}")

    def test_documented_example_is_clean(self):
        self.assertEqual(problems(GOOD), [])

    def test_missing_cell_is_undecided(self):
        self.assertProblem(drop_row(GOOD, "| uploading | cancel |"), "`uploading` has no decision for: `cancel`")

    def test_matrix_marks_undecided_cell(self):
        m, _ = cm.parse(drop_row(GOOD, "| uploading | cancel |"))
        row = next(ln for ln in cm.matrix(m).splitlines() if ln.startswith("| uploading |"))
        self.assertIn("??", row)

    def test_unreachable_state(self):
        text = drop_row(GOOD, "| uploading | fail | failed [same uploadId] |")
        text = drop_row(text, "| uploading | restart | failed |")
        text = text.replace("| uploading | fail | (ignore) [else] | stale upload |",
                            "| uploading | fail | (ignore) | stale upload |")
        text += "\n| uploading | restart | idle | |"
        self.assertProblem(text, "`failed` is unreachable from `idle`")

    def test_trap_state(self):
        text = GOOD.replace("| failed | cancel | idle | |", "| failed | cancel | (ignore) | |")
        text = text.replace("| failed | select | uploading | |", "| failed | select | (ignore) | |")
        text = text.replace("| failed | retry | uploading [attempts < 3] | |", "| failed | retry | failed [attempts < 3] | |")
        self.assertProblem(text, "`failed` is not final but nothing leaves it")

    def test_final_state_cannot_transition(self):
        text = GOOD.replace("| done | * | (ignore) |", "| done | select | uploading | |\n| done | * | (ignore) |")
        self.assertProblem(text, "final state `done` has an outgoing transition on `select`")

    def test_unguarded_duplicate_is_nondeterministic(self):
        text = GOOD.replace("| idle | select | uploading | |", "| idle | select | uploading | |\n| idle | select | failed | |")
        self.assertProblem(text, "nondeterministic")

    def test_guarded_cell_needs_else(self):
        text = GOOD.replace("| failed | retry | failed [else] |", "| failed | retry | failed [attempts >= 3] |")
        self.assertProblem(text, "has no [else] row")

    def test_impossible_needs_reason(self):
        text = GOOD.replace("| idle | cancel | (impossible) | cancel button only renders while uploading |",
                            "| idle | cancel | (impossible) | |")
        self.assertProblem(text, "(impossible) needs a note")

    def test_wildcard_cannot_hide_a_transition(self):
        text = GOOD.replace("| done | * | (ignore) | terminal; the URL is final |", "| done | * | idle | x |")
        self.assertProblem(text, "`*` rows may only say")

    def test_unknown_names(self):
        self.assertProblem(GOOD.replace("| idle | select | uploading |", "| idle | select | uploadin |"),
                           "`uploadin` is neither a declared state")
        self.assertProblem(GOOD.replace("| idle | restart | idle |", "| idle | reboot | idle |"),
                           "event `reboot` is not declared")

    def test_interruption_must_name_an_event(self):
        self.assertProblem(GOOD.replace("- Network timeout: surfaces as `fail`.", "- Network timeout: shows an error."),
                           "interruption names no declared event")

    def test_required_sections(self):
        text = GOOD.split("## Assumptions")[0]
        self.assertProblem(text, "`## Assumptions` section is missing")

    def test_table_with_other_header_is_not_the_transition_table(self):
        self.assertProblem(GOOD.replace("| state | event | next | note |", "| from | on | to | note |"),
                           "no transition table")

    def test_other_tables_and_headings_do_not_interfere(self):
        flags = "| flag | file |\n|---|---|\n| isUploading | a.ts:1 |\n\n"
        text = GOOD.replace("| state | event | next | note |", flags + "## Transition table\n\n| state | event | next | note |")
        self.assertEqual(problems(text), [])

    def test_escaped_pipe_stays_in_note(self):
        m, _ = cm.parse(GOOD.replace("| idle | restart | idle | |", "| idle | restart | idle | data: T \\| null |"))
        self.assertIn("data: T | null", [r.note for r in m.rows])

    def test_duplicate_declaration(self):
        self.assertProblem(GOOD.replace("initial: idle", "initial: idle\nstates: idle"), "`states:` declared twice")

    def test_prose_after_preamble_is_not_a_declaration(self):
        self.assertEqual(problems(GOOD + "\n- events: more of them later\nevents: x\n"), [])

    def test_data_section_names_declared_states(self):
        self.assertEqual(problems(GOOD + "\n## Data\n- `uploading`: uploadId, file\n"), [])
        self.assertProblem(GOOD + "\n## Data\n- `sending`: uploadId\n", "`## Data` bullet starts with a declared state")

    def test_mermaid_omits_self_loops(self):
        m, _ = cm.parse(GOOD)
        self.assertNotIn("idle --> idle", cm.mermaid(m))
        self.assertIn("idle --> uploading: select", cm.mermaid(m))

    def test_cli_exit_codes_and_json(self):
        with tempfile.TemporaryDirectory() as d:
            good, bad = Path(d) / "good.md", Path(d) / "bad.md"
            good.write_text(GOOD)
            bad.write_text(drop_row(GOOD, "| uploading | cancel |"))
            run = lambda *a: subprocess.run([sys.executable, str(SCRIPT), *a], capture_output=True, text=True)
            ok = run(str(good), "--json")
            self.assertEqual(ok.returncode, 0, ok.stderr)
            rows = json.loads(ok.stdout)["transitions"]
            self.assertIn({"state": "failed", "event": "retry", "next": "uploading",
                           "guard": "attempts < 3", "note": ""}, rows)
            fail = run(str(bad))
            self.assertEqual(fail.returncode, 1)
            self.assertIn("bad.md:", fail.stderr)
            self.assertEqual(run().returncode, 2)


if __name__ == "__main__":
    unittest.main()
