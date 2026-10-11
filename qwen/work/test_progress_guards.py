"""Offline tests: duplicate-mutation guard, no-progress repeat guard, session cache, context priority,
cumulative /compact, fit_messages count memoisation. No model, no real memory purge."""
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import qwen_coding
from qwen_coding import CodingWorkspace, REPEAT_LIMIT
from qwen_context import fit_messages


class Guards(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        self.base = Path(self.temp.name)
        self.project, self.agent = self.base / "project", self.base / "agent"
        self.project.mkdir(); self.agent.mkdir()
        self.ws = CodingWorkspace(self.agent, self.project, mode="acceptEdits")
        self.stdout = redirect_stdout(io.StringIO()); self.stdout.__enter__()

    def tearDown(self):
        self.stdout.__exit__(None, None, None)
        self.temp.cleanup()

    def run_tool(self, name, **arguments):
        return self.ws.execute(name, arguments, interactive=False)

    # ---- idempotent mutations
    def test_duplicate_edit_is_not_applied_twice(self):
        self.ws.begin_turn("t")
        self.run_tool("write_file", path="a.py", content="x = 1\n")
        edit = dict(path="a.py", old_text="x = 1", new_text="x = 1\ny = 2")   # new text contains old text
        first = self.run_tool("edit_file", **edit)
        self.assertTrue(first["ok"] and first.get("changed", True))
        second = self.run_tool("edit_file", **edit)
        self.assertTrue(second["ok"] and second["guard"] == "duplicate" and second["changed"] is False)
        self.assertEqual((self.project / "a.py").read_text(), "x = 1\ny = 2\n")
        self.assertEqual(len(self.ws.session["checkpoints"]), 2, "no extra checkpoint for the duplicate")

    def test_duplicate_guard_releases_after_undo_and_new_turn(self):
        self.ws.begin_turn("t")
        self.run_tool("write_file", path="a.py", content="x = 1\n")
        edit = dict(path="a.py", old_text="x = 1", new_text="x = 1\ny = 2")
        self.run_tool("edit_file", **edit)
        self.ws.undo()                                    # file differs from the recorded result now
        again = self.run_tool("edit_file", **edit)
        self.assertNotIn("guard", again)
        self.assertEqual((self.project / "a.py").read_text(), "x = 1\ny = 2\n")
        self.ws.begin_turn("another request")             # guards are per user turn
        (self.project / "a.py").write_text("x = 1\n")
        self.assertNotIn("guard", self.run_tool("edit_file", **edit))

    def test_duplicate_guard_does_not_ask_approval_again(self):
        self.ws.mode = "normal"
        self.run_tool("write_file", path="a.py", content="x = 1\n")
        questions = []
        def approve(text, interactive):
            questions.append(text); return True
        edit = dict(path="a.py", old_text="x = 1", new_text="x = 1\ny = 2")
        self.ws.execute("edit_file", edit, True, approve)
        result = self.ws.execute("edit_file", edit, True, approve)
        self.assertEqual(len(questions), 1)
        self.assertEqual(result["guard"], "duplicate")

    def test_plan_mode_and_scope_still_win(self):
        self.ws.mode = "plan"
        self.assertFalse(self.run_tool("edit_file", path="a.py", old_text="a", new_text="b")["ok"])
        self.ws.mode = "acceptEdits"
        self.assertFalse(self.run_tool("write_file", path="../outside.txt", content="x")["ok"])
        self.assertFalse((self.base / "outside.txt").exists())

    # ---- no-progress detection
    def test_repeated_read_is_refused_third_time_and_released_by_a_change(self):
        (self.project / "a.txt").write_text("hello")
        self.ws.begin_turn("t")
        results = [self.run_tool("read_file", path="a.txt") for _ in range(REPEAT_LIMIT)]
        self.assertTrue(all(item["ok"] for item in results))
        refused = self.run_tool("read_file", path="a.txt")
        self.assertEqual(refused["guard"], "repeat"); self.assertFalse(refused["ok"])
        self.run_tool("write_file", path="b.txt", content="new")   # a mutation invalidates the evidence
        self.assertTrue(self.run_tool("read_file", path="a.txt")["ok"])
        self.ws.begin_turn("next"); self.assertTrue(self.run_tool("read_file", path="a.txt")["ok"])

    def test_different_arguments_are_not_a_repeat(self):
        (self.project / "a.txt").write_text("\n".join(str(i) for i in range(50)))
        self.ws.begin_turn("t")
        for start in range(1, 8):
            self.assertTrue(self.run_tool("read_file", path="a.txt", start_line=start)["ok"])

    def test_identical_failing_edit_is_refused_after_two_failures(self):
        (self.project / "a.txt").write_text("alpha")
        self.ws.begin_turn("t")
        call = dict(path="a.txt", old_text="missing", new_text="x")
        self.assertFalse(self.run_tool("edit_file", **call).get("guard"))
        self.assertFalse(self.run_tool("edit_file", **call).get("guard"))
        self.assertEqual(self.run_tool("edit_file", **call)["guard"], "repeat")

    def test_denied_command_is_not_asked_a_third_time_and_approved_reruns_are_never_blocked(self):
        self.ws.begin_turn("t")
        asked = []
        def deny(text, interactive):
            asked.append(text); return False
        for _ in range(4):
            self.ws.execute("run_powershell", {"command": "Write-Output 1"}, True, deny)
        self.assertEqual(len(asked), REPEAT_LIMIT, "user is not nagged again for a command they already refused")
        runs = []
        def fake_run(args, cwd, timeout=120):
            runs.append(1)
            return {"ok": False, "exit_code": 1, "stdout": "FAILED", "stderr": "", "timed_out": False, "truncated": False}
        with patch.object(qwen_coding, "run_process", fake_run):
            for _ in range(4):
                self.ws.execute("run_powershell", {"command": "pytest"}, True, lambda *a: True)
        self.assertEqual(len(runs), 4, "approved test reruns stay available (fix/retest loops)")

    def test_blocked_calls_never_execute_and_are_audited(self):
        (self.project / "a.txt").write_text("hello")
        self.ws.begin_turn("t")
        with patch.object(self.ws, "read_file", wraps=self.ws.read_file) as spy:
            for _ in range(5):
                self.run_tool("read_file", path="a.txt")
            self.assertEqual(spy.call_count, REPEAT_LIMIT)
        entries = [json.loads(line) for line in (self.agent / "qwen-agent-actions.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(sum(1 for item in entries if item["result"].get("guard") == "repeat"), 3)

    # ---- sessions cache
    def test_sessions_listing_reparses_only_changed_files(self):
        for index in range(3):
            self.ws.new_session()
        calls = []
        original = Path.read_text
        def counting(path, *args, **kwargs):
            calls.append(path.name); return original(path, *args, **kwargs)
        with patch.object(Path, "read_text", counting):
            first = self.ws.sessions()
            reads = len(calls)
            second = self.ws.sessions()
            self.assertEqual(len(calls), reads, "unchanged session files must not be re-read")
            self.assertEqual(first, second)
            self.ws.begin_turn("changed"); self.ws.finish_turn(result={"answer": "x"})
            third = self.ws.sessions()
            self.assertEqual(len(calls) - reads, 1, "only the modified session is re-read")
        self.assertEqual(len(third), 4)
        self.assertEqual(third[0]["id"], self.ws.session["id"])
        self.ws.session_path.unlink()
        self.assertEqual(len(self.ws.sessions()), 3)

    # ---- context priority and compaction
    def test_notes_and_tasks_survive_long_recent_turns(self):
        self.ws.command("/remember NOTE-ORCHID-7429 always answer in Hebrew")
        self.ws.session["tasks"] = ["todo: TASK-LILAC-31"]
        for index in range(3):
            self.ws.begin_turn(f"prompt{index} " + "p" * 500)
            self.ws.finish_turn(result={"answer": "a" * 700})
        context = self.ws.context()
        self.assertLessEqual(len(context), 1800)
        self.assertIn("NOTE-ORCHID-7429", context)
        self.assertIn("TASK-LILAC-31", context)
        self.assertTrue(context.rstrip().endswith("Executed tools:"), "newest turn is kept")

    def test_short_context_is_unchanged(self):
        self.ws.begin_turn("hi"); self.ws.finish_turn(result={"answer": "ORCHID"})
        self.assertEqual(self.ws.context(), "User: hi\nAssistant: ORCHID\nExecuted tools: ")

    def test_compact_is_cumulative_and_records_failures_and_commands(self):
        self.ws.begin_turn("first request FIRST-MARK"); self.ws.finish_turn(result={"answer": "done one"})
        self.ws.compact()
        self.assertIn("FIRST-MARK", self.ws.session["summary"])
        self.ws.begin_turn("second request SECOND-MARK")
        self.ws.audit("edit_file", {"path": "q.py"}, {"ok": False, "error": "old_text must match exactly once"})
        self.ws.audit("run_powershell", {"command": "pytest -q"}, {"ok": True, "exit_code": 0})
        self.ws.finish_turn(result={"answer": "done two"})
        summary = self.ws.compact()
        for fragment in ("FIRST-MARK", "SECOND-MARK", "failed edit_file", "run pytest -q exit=0"):
            self.assertIn(fragment, summary)
        self.assertEqual(self.ws.compact(), summary, "compact with nothing new is stable")
        self.assertLessEqual(len(summary), 900)

    # ---- token counting
    def test_fit_messages_reuses_identical_counts(self):
        messages = [{"role": "system", "content": "s"},
                    {"role": "user", "content": "h" * 7000, "context_only": True},
                    {"role": "user", "content": "REQUEST"}]
        calls = []
        def counter(values):
            calls.append(1); return len(json.dumps(values)) // 4
        fitted, count, compacted = fit_messages(messages, [], 0, context=600, output=50, counter=counter)
        self.assertTrue(compacted); self.assertEqual(fitted[-1]["content"], "REQUEST")
        self.assertEqual(len(calls), 2, "original + after dropping the context-only message; no repeated identical counts")
        bad = [{"role": "system", "content": "s"}, {"role": "user", "content": "REQUEST"},
               {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "read_file", "arguments": '{"path": '}}]},
               {"role": "tool", "tool_name": "read_file", "content": json.dumps({"ok": False, "error": "x" * 4000})}]
        fit_messages(bad, [], 0, context=600, output=50, counter=lambda values: len(json.dumps(values)) // 4)


if __name__ == "__main__":
    unittest.main(verbosity=2)
