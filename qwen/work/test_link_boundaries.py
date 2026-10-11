"""Offline test: edits through symlinks/junctions that leave the project or enter the agent folder are refused.
(Coverage gap found in the Phase-1 audit: only hard links had a test.) Creates links only inside temp folders."""
import io
import os
from contextlib import redirect_stdout
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from qwen_coding import CodingWorkspace


def make_link(link, target, directory):
    try:
        os.symlink(target, link, target_is_directory=directory)
        return "symlink"
    except (OSError, NotImplementedError):
        pass
    if directory and os.name == "nt":
        done = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True)
        if done.returncode == 0:
            return "junction"
    return None


class Links(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        self.base = Path(self.temp.name)
        self.project, self.agent, self.outside = self.base / "project", self.base / "agent", self.base / "outside"
        for folder in (self.project, self.agent, self.outside):
            folder.mkdir()
        (self.outside / "secret.txt").write_text("outside-original")
        self.ws = CodingWorkspace(self.agent, self.project, mode="acceptEdits")
        self.stdout = redirect_stdout(io.StringIO()); self.stdout.__enter__()

    def tearDown(self):
        self.stdout.__exit__(None, None, None)
        for name in ("dirlink",):
            link = self.project / name
            try:
                os.rmdir(link) if link.is_dir() else link.unlink()
            except OSError:
                pass
        self.temp.cleanup()

    def run_tool(self, name, **arguments):
        return self.ws.execute(name, arguments, interactive=False)

    def test_file_symlink_to_outside_is_refused(self):
        if not make_link(self.project / "filelink.txt", self.outside / "secret.txt", False):
            self.skipTest("file symlinks not permitted here")
        self.assertFalse(self.run_tool("edit_file", path="filelink.txt", old_text="outside-original", new_text="x")["ok"])
        self.assertFalse(self.run_tool("write_file", path="filelink.txt", content="x", overwrite=True)["ok"])
        self.assertEqual((self.outside / "secret.txt").read_text(), "outside-original")

    def test_directory_link_to_outside_is_refused_for_every_tool(self):
        if not make_link(self.project / "dirlink", self.outside, True):
            self.skipTest("directory links not permitted here")
        self.assertFalse(self.run_tool("write_file", path="dirlink/new.txt", content="x")["ok"])
        self.assertFalse(self.run_tool("edit_file", path="dirlink/secret.txt", old_text="outside", new_text="x")["ok"])
        self.assertFalse(self.run_tool("read_file", path="dirlink/secret.txt")["ok"])
        self.assertFalse((self.outside / "new.txt").exists())
        self.assertEqual((self.outside / "secret.txt").read_text(), "outside-original")
        self.assertNotIn("dirlink/secret.txt", self.run_tool("list_directory", pattern="**/*.txt")["files"])

    def test_directory_link_into_agent_folder_is_protected(self):
        if not make_link(self.project / "dirlink", self.agent, True):
            self.skipTest("directory links not permitted here")
        self.assertFalse(self.run_tool("read_file", path="dirlink/state/ui.json")["ok"])
        self.assertFalse(self.run_tool("write_file", path="dirlink/state/evil.json", content="{}")["ok"])
        self.assertFalse((self.agent / "state" / "evil.json").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
