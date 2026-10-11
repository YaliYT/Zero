import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from qwen_coding import CodingWorkspace, run_process, preview
from qwen_context import fit_messages, shorten_result
from qwen_cpu_runner import convert_messages


class Features(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        self.base = Path(self.temp.name)
        self.project = self.base/"project"
        self.project.mkdir()
        self.agent = self.base/"agent"
        self.agent.mkdir()
        self.ws = CodingWorkspace(self.agent, self.project, mode="acceptEdits")
        self.stdout = redirect_stdout(io.StringIO())
        self.stdout.__enter__()

    def tearDown(self):
        self.stdout.__exit__(None, None, None)
        self.temp.cleanup()

    def execute(self, name, **arguments):
        return self.ws.execute(name, arguments, interactive=False)

    def test_create_edit_diff_undo(self):
        self.assertTrue(self.execute("write_file", path="src/main.py", content="print('old')\n")["verified"])
        result = self.execute("edit_file", path="src/main.py", old_text="'old'", new_text="'new'")
        self.assertTrue(result["verified"])
        self.assertIn("+print('new')", self.ws.diff())
        self.ws.undo()
        self.assertEqual((self.project/"src/main.py").read_text(), "print('old')\n")
        self.ws.undo()
        self.assertFalse((self.project/"src/main.py").exists())

    def test_ambiguous_replacement_and_overwrite(self):
        self.execute("write_file", path="a.txt", content="repeat repeat")
        self.assertFalse(self.execute("edit_file", path="a.txt", old_text="repeat", new_text="x")["ok"])
        self.assertFalse(self.execute("write_file", path="a.txt", content="x")["ok"])
        self.assertEqual((self.project/"a.txt").read_text(), "repeat repeat")

    def test_diff_without_final_newline(self):
        diff = preview(b"old", b"new", "file.txt")
        self.assertIn("-old\n\\ No newline at end of file\n+new\n", diff)
        self.assertNotIn("-old+new", diff)

    def test_preserve_bom_crlf(self):
        path = self.project/"a.txt"
        path.write_bytes(b"\xef\xbb\xbfalpha\r\nbeta\r\n")
        self.assertTrue(self.execute("edit_file", path="a.txt", old_text="alpha\nbeta", new_text="alpha\ngamma")["ok"])
        self.assertEqual(path.read_bytes(), b"\xef\xbb\xbfalpha\r\ngamma\r\n")
        self.ws.undo()
        self.assertEqual(path.read_bytes(), b"\xef\xbb\xbfalpha\r\nbeta\r\n")

    def test_external_edit_prevents_undo(self):
        self.execute("write_file", path="a.txt", content="agent")
        (self.project/"a.txt").write_text("human")
        with self.assertRaises(RuntimeError):
            self.ws.undo()
        self.assertEqual((self.project/"a.txt").read_text(), "human")

    def test_scope_agent_state_and_stream(self):
        self.assertFalse(self.execute("write_file", path="../outside.txt", content="x")["ok"])
        self.assertFalse(self.execute("read_file", path=str(self.agent/"state/ui.json"))["ok"])
        self.assertFalse(self.execute("write_file", path="file.txt:stream", content="x")["ok"])
        self.assertFalse((self.base/"outside.txt").exists())

    def test_hardlink_edit_refused(self):
        original = self.project/"a.txt"
        original.write_text("original")
        os.link(original, self.project/"linked.txt")
        self.assertFalse(self.execute("edit_file", path="linked.txt", old_text="original", new_text="changed")["ok"])
        self.assertEqual(original.read_text(), "original")

    def test_read_pagination(self):
        self.execute("write_file", path="a.txt", content="\n".join(f"line{index}" for index in range(60)))
        first = self.execute("read_file", path="a.txt", start_line=3, limit=4)
        self.assertEqual(first["content"], "line2\nline3\nline4\nline5")
        self.assertEqual(first["next_line"], 7)
        last = self.execute("read_file", path="a.txt", start_line=60)
        self.assertEqual(last["content"], "line59")
        self.assertIsNone(last["next_line"])

    def test_search_and_glob(self):
        self.execute("write_file", path="src/main.py", content="answer = 391\n")
        self.execute("write_file", path="node_modules/hidden.py", content="answer = 391\n")
        result = self.execute("search_files", query="391", pattern="*.py")
        self.assertTrue(result["ok"], result)
        self.assertEqual(len(result["matches"]), 1)
        self.assertEqual(result["matches"][0]["line"], 1)
        files = self.execute("list_directory", pattern="**/*.py")
        self.assertEqual(files["files"], ["src/main.py"])

    def test_plan_blocks_mutation_and_command(self):
        self.ws.mode = "plan"
        self.assertFalse(self.execute("write_file", path="no.txt", content="no")["ok"])
        self.assertFalse(self.execute("run_powershell", command="Write-Output no")["ok"])
        self.assertTrue(self.execute("list_directory")["ok"])
        self.assertTrue(self.execute("update_tasks", items=["todo: read"])["ok"])
        self.assertEqual({item["function"]["name"] for item in self.ws.tools()},
                         {"read_file", "list_directory", "search_files", "update_tasks"})

    def test_command_approval_never_inherited_from_edit_mode(self):
        self.assertFalse(self.execute("run_powershell", command="Write-Output approved")["ok"])
        self.assertTrue(self.ws.run_shell("Write-Output 391", human_command=True)["ok"])
        self.ws.mode = "normal"
        self.execute("write_file", path="a.txt", content="original")
        self.assertFalse(self.execute("edit_file", path="a.txt", old_text="original", new_text="changed")["ok"])

    def test_changed_while_awaiting_approval(self):
        self.execute("write_file", path="a.txt", content="original")
        self.ws.mode = "normal"
        def approve(*args):
            (self.project/"a.txt").write_text("human")
            return True
        result = self.ws.execute("edit_file", dict(path="a.txt", old_text="original", new_text="agent"),
                                 interactive=True, approve=approve)
        self.assertFalse(result["ok"])
        self.assertEqual((self.project/"a.txt").read_text(), "human")

    def test_session_resume_tasks_and_crash_recovery(self):
        self.ws.begin_turn("Create marker")
        self.execute("write_file", path="a.txt", content="391")
        self.execute("update_tasks", items=["done: create marker", "todo: test"])
        identifier = self.ws.session["id"]
        recovered = CodingWorkspace(self.agent, self.project, resume=identifier)
        self.assertEqual(recovered.session["history"][0]["status"], "interrupted")
        self.assertEqual(recovered.session["history"][0]["tools"][0]["tool"], "write_file")
        self.assertEqual(recovered.session["tasks"][0], "done: create marker")
        self.assertEqual(recovered.session["history"][0]["tools"][0]["arguments"]["content"], "391")
        recovered.undo()
        self.assertFalse((self.project/"a.txt").exists())
        with self.assertRaises(ValueError):
            recovered.resume_session("../ui")

    def test_completed_session_and_compact(self):
        self.ws.begin_turn("Remember user context")
        self.ws.finish_turn(result={"answer": "ORCHID-7429"})
        identifier = self.ws.session["id"]
        recovered = CodingWorkspace(self.agent, self.project, resume=identifier)
        self.assertIn("ORCHID-7429", recovered.context())
        recovered.compact()
        self.assertEqual(len(recovered.session["history"]), 1)
        self.assertIn("ORCHID-7429", recovered.context())
        self.assertEqual(recovered.session["context_after"], 1)

    def test_project_rules_and_notes(self):
        (self.project/"AGENTS.md").write_text("Use unittest.")
        (self.project/"CLAUDE.md").write_text("Keep files small.")
        self.ws.command("/remember Hebrew output")
        self.assertIn("Use unittest.", self.ws.system())
        self.assertIn("Keep files small.", self.ws.system())
        self.assertIn("Hebrew output", CodingWorkspace(self.agent, self.project).context())

    def test_git_readonly(self):
        run_process([shutil.which("git"), "init", str(self.project)], self.project, 20)
        self.execute("write_file", path="a.txt", content="391")
        self.assertIn("a.txt", self.ws.git("status")["stdout"])
        with self.assertRaises(ValueError):
            self.ws.git("reset --hard")

    def test_owned_command_timeout(self):
        result = self.ws.run_shell("Start-Sleep -Seconds 10", human_command=True, timeout=.15)
        self.assertTrue(result["timed_out"])
        self.assertFalse(result["ok"])

    def test_child_process_is_released(self):
        import psutil
        code = ("import subprocess,sys; p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'],"
                "creationflags=subprocess.CREATE_NO_WINDOW); print(p.pid,flush=True)")
        result = run_process([sys.executable, "-c", code], self.project, 10)
        self.assertTrue(result["ok"], result)
        child = int(result["stdout"].strip())
        deadline = time.monotonic()+5
        while psutil.pid_exists(child) and time.monotonic()<deadline:
            time.sleep(.02)
        self.assertFalse(psutil.pid_exists(child), 'owned background child must not survive the command job')

    def test_excerpt_pagination_does_not_skip_unseen_lines(self):
        value = dict(ok=True, start_line=10, content="alpha\nbeta\ngamma\ndelta", next_line=None)
        excerpt = shorten_result(value, 13)
        self.assertEqual(excerpt["content"], "alpha\nbeta")
        self.assertEqual(excerpt["next_line"], 12)
        self.assertTrue(excerpt["context_excerpt"])

    def test_tool_ids_and_context_compaction(self):
        messages = [{"role":"system", "content":"system"},
                    {"role":"user", "content":"history"*1000, "context_only":True},
                    {"role":"user", "content":"CURRENT REQUEST"},
                    {"role":"assistant", "content":"", "tool_calls":[{"function":{"name":"write_file",
                     "arguments":{"path":"a.txt","content":"a"*1000}}}]},
                    {"role":"tool", "tool_name":"write_file", "content":json.dumps({"ok":True, "path":"a.txt"})},
                    {"role":"assistant", "content":"", "tool_calls":[{"function":{"name":"read_file",
                     "arguments":{"path":"a.txt"}}}]},
                    {"role":"tool", "tool_name":"read_file", "content":json.dumps({"ok":True,"content":"b"*3000})}]
        fitted, count, compacted = fit_messages(messages, [], 0, context=600, output=50,
                                               counter=lambda values: len(json.dumps(values))//4)
        self.assertTrue(compacted)
        self.assertLessEqual(count, 534)
        self.assertEqual(fitted[1]["content"], "CURRENT REQUEST")
        self.assertEqual(len(messages[1]["content"]), 7000, "original transcript unchanged")
        converted = convert_messages(fitted)
        self.assertEqual(converted[-1]["tool_call_id"], converted[-2]["tool_calls"][0]["id"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

