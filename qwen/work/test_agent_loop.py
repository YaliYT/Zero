"""Offline tests of the agent tool loop with a scripted model. No llama-server, no memory guard."""
import importlib.util
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import sys
import tempfile
import unittest

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from qwen_coding import CodingWorkspace

spec = importlib.util.spec_from_file_location("agent_under_test", root / "Qwen-Agent.py")
agent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent)


def call(name, arguments):
    return {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": name, "arguments": arguments}}]}


def say(text):
    return {"role": "assistant", "content": text}


class AgentLoop(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        base = Path(self.temp.name)
        self.project, agent_dir = base / "project", base / "agent"
        self.project.mkdir(); agent_dir.mkdir()
        agent.WORKSPACE = CodingWorkspace(agent_dir, self.project, mode="acceptEdits")
        agent.MEMORY_GUARD = None
        self.sent = []
        self.stdout = redirect_stdout(io.StringIO()); self.stdout.__enter__()

    def tearDown(self):
        agent.WORKSPACE = None
        self.stdout.__exit__(None, None, None)
        self.temp.cleanup()

    def script(self, replies):
        iterator = iter(replies)
        def fake(messages):
            self.sent.append(json.loads(json.dumps(messages)))
            return next(iterator)
        agent.chat_request = fake

    def test_malformed_tool_json_is_feedback_not_a_crash(self):
        self.script([call("read_file", '{"path": "a.txt'), call("read_file", "[1, 2]"), say("recovered")])
        result = agent.agent_turn("go", interactive=False)
        self.assertEqual(result["answer"], "recovered")
        tool_messages = [m for m in self.sent[-1] if m["role"] == "tool"]
        self.assertEqual(len(tool_messages), 2)
        for message in tool_messages:
            self.assertFalse(json.loads(message["content"])["ok"])
            self.assertIn("no tool was executed", json.loads(message["content"])["error"])

    def test_missing_function_name_does_not_crash(self):
        self.script([{"role": "assistant", "content": "", "tool_calls": [{}]}, say("ok")])
        self.assertEqual(agent.agent_turn("go", interactive=False)["answer"], "ok")

    def test_identical_call_loop_stops_early_without_repeating_the_work(self):
        (self.project / "a.txt").write_text("hello")
        executed = []
        workspace = agent.coding_workspace()
        original = workspace.read_file
        workspace.read_file = lambda **kw: executed.append(kw) or original(**kw)
        self.script(call("read_file", {"path": "a.txt"}) for _ in range(16))
        with self.assertRaises(RuntimeError) as caught:
            agent.agent_turn("go", interactive=False)
        self.assertIn("without progress", str(caught.exception))
        self.assertEqual(len(executed), 2)
        self.assertEqual(len(self.sent), 2 + agent.MAX_BLOCKED_CALLS, "stopped well before the 16-step cap")
        self.assertEqual(workspace.session["history"][-1]["status"], "interrupted", "turn state saved")

    def test_two_identical_edits_in_one_message_apply_once(self):
        (self.project / "a.py").write_text("x = 1\n")
        edit = {"path": "a.py", "old_text": "x = 1", "new_text": "x = 1\ny = 2"}
        message = {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "edit_file", "arguments": json.dumps(edit)}},
                                                  {"function": {"name": "edit_file", "arguments": edit}}]}
        self.script([message, say("done")])
        agent.agent_turn("go", interactive=False)
        self.assertEqual((self.project / "a.py").read_text(), "x = 1\ny = 2\n")

    def test_parse_tool_arguments(self):
        self.assertEqual(agent.parse_tool_arguments(""), ({}, None))
        self.assertEqual(agent.parse_tool_arguments('{"a": 1}'), ({"a": 1}, None))
        self.assertIsNotNone(agent.parse_tool_arguments("{")[1])
        self.assertIsNotNone(agent.parse_tool_arguments(None)[1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
