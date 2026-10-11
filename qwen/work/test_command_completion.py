import asyncio
import faulthandler
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

APP = Path(sys.argv.pop(1)).resolve() if len(sys.argv) > 1 and not sys.argv[1].startswith('-') else Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
from qwen_input import AgentCompleter, ConsoleInput, COMMANDS
from prompt_toolkit.document import Document
from prompt_toolkit.completion import CompleteEvent
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput


class CompletionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        self.base = Path(self.temp.name)
        self.project = self.base / 'project'
        self.project.mkdir()
        self.root = self.base / 'agent'
        self.root.mkdir()
        self.workspace = SimpleNamespace(
            root=self.root, project=self.project,
            session={'checkpoints': [{'id': 'abc123', 'path': 'a.py', 'status': 'applied'},
                                      {'id': 'gone', 'path': 'b.py', 'status': 'undone'}]},
            sessions=lambda: [{'id': 'session123', 'title': 'עברית', 'project': str(self.project)},
                              {'id': 'other', 'title': 'other project', 'project': str(self.base)}])
        self.completer = AgentCompleter(self.workspace)

    def tearDown(self):
        self.temp.cleanup()

    def complete(self, value):
        return list(self.completer.get_completions(Document(value), CompleteEvent(completion_requested=True)))

    def test_commands_and_arguments(self):
        self.assertEqual(self.complete('/mo')[0].text, '/mode ')
        self.assertEqual(len(self.complete('/')), len(COMMANDS))
        self.assertEqual([c.text for c in self.complete('/mode a')], ['acceptEdits'])
        self.assertEqual([c.text for c in self.complete('/permissions p')], ['plan'])
        self.assertEqual([c.text for c in self.complete('/git st')], ['status', 'staged'])
        self.assertEqual(self.complete('ordinary message'), [])
        self.assertEqual(self.complete('/unknown '), [])

    def test_live_session_and_checkpoint(self):
        self.assertEqual([c.text for c in self.complete('/resume ')], ['latest', 'session123'])
        self.assertEqual([c.text for c in self.complete('/undo ')], ['abc123'])
        self.workspace.session['checkpoints'] = []
        self.assertEqual(self.complete('/rewind '), [])

    def test_folders_quotes_and_changed_project(self):
        folder = self.project / 'שלום עולם'
        folder.mkdir()
        (folder / 'nested').mkdir()
        (self.project / 'שלום.txt').write_text('ignored', encoding='utf-8')
        result = self.complete('/cd שלום')[0]
        self.assertEqual(result.text, '"' + str(folder) + '\\"')
        selected = '/cd שלום'[:result.start_position] + result.text
        self.assertEqual(selected, '/cd "' + str(folder) + '\\"')
        self.assertEqual(len(self.complete(selected + 'n')), 1)
        self.workspace.project = folder
        self.assertEqual(self.complete('/project n')[0].text, '"' + str(folder / 'nested') + '\\"')
        self.assertEqual(self.complete('/cd Z:\\not-a-real-folder-123\\'), [])

    def test_real_tab_enter_and_history_keys(self):
        faulthandler.dump_traceback_later(8, exit=True)
        async def exercise():
            with create_pipe_input() as pipe:
                editor = ConsoleInput(self.workspace, input=pipe, output=DummyOutput())
                async def read_with_keys(keys):
                    pending = asyncio.create_task(editor.session.prompt_async('> '))
                    await asyncio.sleep(.08)
                    for text, delay in keys:
                        pipe.send_text(text)
                        await asyncio.sleep(delay)
                    return await asyncio.wait_for(pending, timeout=3)
                # Actual terminal Tab completes a unique slash command and Enter submits.
                self.assertEqual(await read_with_keys([('/mo', .2), ('\t', .2), ('\r', .1)]), '/mode ')
                self.assertEqual(await read_with_keys([('/mode ', .2), ('\t', .2), ('\x1b[B', .1),
                                                       ('\r', .1)]), '/mode acceptEdits')
                self.assertEqual(await read_with_keys([('שלום בדיקה', .1), ('\r', .1)]), 'שלום בדיקה')
                self.assertEqual(await read_with_keys([('\x1b[A', .1), ('\r', .1)]), 'שלום בדיקה')
                # A new editor loads history from disk. Right-arrow accepts its suggestion.
                editor = ConsoleInput(self.workspace, input=pipe, output=DummyOutput())
                self.assertEqual(await read_with_keys([('שלום', .2), ('\x1b[C', .1), ('\r', .1)]), 'שלום בדיקה')
                self.assertTrue((self.root / 'state' / 'input-history.txt').is_file())
                # Exercise the public reader including redraw protection for background logs.
                pending = asyncio.create_task(asyncio.to_thread(editor.read))
                await asyncio.sleep(.15)
                pipe.send_text('/exit\r')
                self.assertEqual(await asyncio.wait_for(pending, timeout=3), '/exit')
        asyncio.run(exercise())
        faulthandler.cancel_dump_traceback_later()

    def test_nonterminal_fallback(self):
        with patch('sys.stdin.isatty', return_value=False), patch('builtins.input', return_value='/help') as reader:
            editor = ConsoleInput(self.workspace)
            self.assertFalse(editor.interactive)
            self.assertEqual(editor.read(), '/help')
            reader.assert_called_once_with('אתה: ')


if __name__ == '__main__':
    unittest.main(verbosity=2)

