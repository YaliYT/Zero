"""Visual BiDi rendering for an LTR Windows console; stored text stays logical."""
import builtins
import shutil
import sys
import textwrap
import threading
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / 'vendor'))
from bidi.algorithm import (get_empty_storage, get_embedding_levels,
                            explicit_embed_and_overrides, resolve_weak_types,
                            resolve_neutral_types, resolve_implicit_levels,
                            reorder_resolved_levels, apply_mirroring)
from prompt_toolkit.layout.processors import Processor, Transformation
from prompt_toolkit.layout.utils import explode_text_fragments

_lock = threading.RLock()
_active_stream = None


def visual_order(text):
    """Return visual characters with original indexes and resolved directions."""
    if not any(unicodedata.bidirectional(c) in ('R', 'AL') for c in text):
        return [(char, index, 0) for index, char in enumerate(text)]
    # Isolate controls are unsupported by the Python engine; omit only for display.
    source = [(char, index) for index, char in enumerate(text)
              if unicodedata.bidirectional(char) not in ('LRI', 'RLI', 'FSI', 'PDI')]
    storage = get_empty_storage()
    storage['base_level'], storage['base_dir'] = 0, 'L'
    get_embedding_levels(''.join(char for char, _ in source), storage, False, False)
    for item, (_, index) in zip(storage['chars'], source):
        item['source_index'] = index
    explicit_embed_and_overrides(storage, False)
    resolve_weak_types(storage, False)
    resolve_neutral_types(storage, False)
    resolve_implicit_levels(storage, False)
    reorder_resolved_levels(storage, False)
    apply_mirroring(storage, False)
    return [(item['ch'], item['source_index'], item['level']) for item in storage['chars']]


def visual(text):
    return '\n'.join(''.join(char for char, _, _ in visual_order(line)) for line in str(text).split('\n'))


class HebrewProcessor(Processor):
    def apply_transformation(self, ti):
        chars = explode_text_fragments(ti.fragments)
        text = ''.join(item[1] for item in chars)
        order = visual_order(text)
        positions = {source: (display, level) for display, (_, source, level) in enumerate(order)}

        def source_to_display(index):
            # A cursor is between characters, rather than on their reordered index.
            if index == 0 and 0 in positions:
                display, level = positions[0]
                return display + (level % 2)
            if index - 1 in positions:
                display, level = positions[index - 1]
                return display + (1 - level % 2)
            return min(index, len(order))

        def display_to_source(index):
            return order[index][1] if 0 <= index < len(order) else len(text)

        fragments = [(chars[source][0], char, *chars[source][2:]) for char, source, _ in order]
        return Transformation(fragments, source_to_display, display_to_source)


def _width():
    return max(20, shutil.get_terminal_size((120, 30)).columns - 1)


def _formatted_lines(text):
    for line in text.split('\n'):
        if any(unicodedata.bidirectional(c) in ('R', 'AL') for c in line) and '\x1b' not in line:
            for part in textwrap.wrap(line, width=_width(), replace_whitespace=False,
                                      drop_whitespace=False, break_on_hyphens=False) or ['']:
                yield visual(part)
        else:
            yield line


def terminal_print(*objects, sep=' ', end='\n', file=None, flush=False):
    target = file if file is not None else sys.stdout
    if not getattr(target, 'isatty', lambda: False)():
        return builtins.print(*objects, sep=sep, end=end, file=target, flush=flush)
    text = '\n'.join(_formatted_lines((sep if sep is not None else ' ').join(str(obj) for obj in objects)))
    with _lock:
        active = _active_stream if target is sys.stdout else None
        if active:
            active._clear()
        builtins.print(text, end=end, file=target, flush=flush)
        if active:
            active._redraw()


class DisplayStream:
    """Redraw the current logical line as chunks arrive, keeping words in order."""
    def __init__(self, prefix='Qwen: ', output=None):
        global _active_stream
        self.output = output if output is not None else sys.stdout
        self.enabled = getattr(self.output, 'isatty', lambda: False)()
        self.pending = prefix
        if self.enabled:
            with _lock:
                _active_stream = self
                self._redraw()
        else:
            self.output.write(prefix)
            self.output.flush()

    def _clear(self):
        self.output.write('\r\x1b[2K')

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.finish()

    def _redraw(self):
        self._clear()
        self.output.write(visual(self.pending))
        self.output.flush()

    def feed(self, text):
        if not self.enabled:
            self.output.write(text)
            self.output.flush()
            return
        with _lock:
            self.pending += text
            while '\n' in self.pending or len(self.pending) > _width():
                newline = self.pending.find('\n')
                if 0 <= newline <= _width():
                    part, self.pending = self.pending[:newline], self.pending[newline + 1:]
                else:
                    stop = self.pending.rfind(' ', 0, _width() + 1)
                    stop = stop + 1 if stop >= 0 else _width()
                    part, self.pending = self.pending[:stop], self.pending[stop:]
                self._clear()
                self.output.write(visual(part) + '\n')
            self._redraw()

    def finish(self):
        global _active_stream
        with _lock:
            if self.enabled:
                self._redraw()
                if _active_stream is self:
                    _active_stream = None
            self.output.write('\n')
            self.output.flush()
