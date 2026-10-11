import asyncio
import io
import json
from pathlib import Path
import re
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

APP = Path(sys.argv.pop(1)).resolve() if len(sys.argv) > 1 and not sys.argv[1].startswith('-') else Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
from qwen_terminal import visual, visual_order, HebrewProcessor, DisplayStream, terminal_print
from qwen_input import AgentCompleter
from qwen_cpu_runner import native_chat
from prompt_toolkit.document import Document
from prompt_toolkit.completion import CompleteEvent


class Terminal(io.StringIO):
    def isatty(self):
        return True


class HebrewTests(unittest.TestCase):
    def test_hebrew_words_and_mixed_english(self):
        self.assertEqual(visual('שלום עולם'), 'םלוע םולש')
        self.assertEqual(visual('/help'), '/help')
        value = visual('מצב: normal | RAM: 80% | C:\\Users\\nagor\\Downloads')
        for fragment in ('normal', 'RAM: 80%', 'C:\\Users\\nagor\\Downloads', 'בצמ'):
            self.assertIn(fragment, value)
        self.assertEqual(visual('שלום\nעולם'), 'םולש\nםלוע')

    def test_completion_display_does_not_change_actual_command(self):
        workspace = SimpleNamespace()
        completion = list(AgentCompleter(workspace).get_completions(Document('/he'), CompleteEvent()))[0]
        self.assertEqual(completion.text, '/help')
        self.assertEqual(completion.display_meta_text, 'הרזע')

    def test_processor_cursor_styles_and_logical_text(self):
        source = 'שלום'
        ti = SimpleNamespace(fragments=[('class:typed', source)])
        result = HebrewProcessor().apply_transformation(ti)
        self.assertEqual(''.join(item[1] for item in result.fragments), 'םולש')
        self.assertEqual([result.source_to_display(i) for i in range(5)], [4, 3, 2, 1, 0])
        self.assertEqual([result.display_to_source(i) for i in range(4)], [3, 2, 1, 0])
        self.assertTrue(all(item[0] == 'class:typed' for item in result.fragments))
        self.assertEqual(source, 'שלום')

    def test_stream_redraw_combines_tokens_not_reversed_fragments(self):
        terminal = Terminal()
        with DisplayStream(output=terminal) as stream:
            for text in ('של', 'ום', ' עו', 'לם'):
                stream.feed(text)
        frames = terminal.getvalue().split('\r\x1b[2K')
        self.assertEqual(frames[-1], 'Qwen: םלוע םולש\n')
        with patch('qwen_terminal._width', return_value=20):
            terminal = Terminal()
            with DisplayStream(output=terminal) as stream:
                stream.feed('שלום עולם ' * 8)
            self.assertTrue(all(len(frame) <= 22 for frame in terminal.getvalue().split('\r\x1b[2K')))

    def test_redirected_stream_and_print_stay_logical(self):
        output = io.StringIO()
        with DisplayStream(output=output) as stream:
            stream.feed('שלום עולם')
        self.assertEqual(output.getvalue(), 'Qwen: שלום עולם\n')
        terminal_print('שלום', file=output)
        self.assertTrue(output.getvalue().endswith('שלום\n'))
        terminal = Terminal()
        terminal_print('שלום עולם', file=terminal)
        self.assertEqual(terminal.getvalue(), 'םלוע םולש\n')

    def test_background_print_does_not_erase_streamed_answer(self):
        output = Terminal()
        with patch('sys.stdout', output):
            with DisplayStream() as stream:
                stream.feed('שלום')
                terminal_print('ניקוי RAM: 40%', flush=True)
                stream.feed(' עולם')
        frames = output.getvalue().split('\r\x1b[2K')
        self.assertIn('RAM: 40%', output.getvalue())
        self.assertEqual(frames[-1], 'Qwen: םלוע םולש\n')

    def test_native_response_preserves_logical_answer(self):
        chunks = [{'choices': [{'delta': {'content': value}, 'finish_reason': None}]}
                  for value in ('של', 'ום', ' עולם')]
        chunks.append({'choices': [{'delta': {}, 'finish_reason': 'stop'}]})
        wire = b''.join(b'data: ' + json.dumps(chunk, ensure_ascii=False).encode('utf-8') + b'\n\n'
                        for chunk in chunks) + b'data: [DONE]\n\n'
        output = Terminal()
        with patch('sys.stdout', output), patch('qwen_cpu_runner.urllib.request.urlopen', return_value=io.BytesIO(wire)):
            result = native_chat([{'role': 'user', 'content': 'שלום'}], [], 57206)
        self.assertEqual(result['content'], 'שלום עולם')
        self.assertEqual(output.getvalue().split('\r\x1b[2K')[-1], 'Qwen: םלוע םולש\n')


if __name__ == '__main__':
    unittest.main(verbosity=2)

