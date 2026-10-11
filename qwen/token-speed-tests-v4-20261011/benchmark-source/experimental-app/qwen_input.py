"""Local console editor. Completion only reads metadata and never runs commands."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "vendor"))

from prompt_toolkit import PromptSession
from prompt_toolkit.application import create_app_session
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import Completer, Completion, ThreadedCompleter
from prompt_toolkit.history import FileHistory
from prompt_toolkit.patch_stdout import patch_stdout
from qwen_terminal import visual, HebrewProcessor


COMMANDS = {
    "/help": "עזרה", "/cd": "בחירת תיקיית פרויקט", "/project": "תיקיית פרויקט",
    "/mode": "מצב עבודה", "/permissions": "הרשאות", "/plan": "תכנון בקשה",
    "/tasks": "משימות", "/diff": "הצגת שינויים", "/undo": "ביטול עריכה",
    "/rewind": "ביטול עריכה", "/checkpoints": "גיבויי עריכות",
    "/compact": "סיכום הקשר", "/context": "מצב ההקשר", "/remember": "שמירת הערה",
    "/memory": "הערות פרויקט", "/init": "יצירת AGENTS.md", "/run": "פקודת PowerShell",
    "/test": "הרצת בדיקות", "/git": "מצב Git", "/sessions": "שיחות שמורות",
    "/resume": "המשך שיחה", "/new": "שיחה חדשה", "/clear": "שיחה חדשה", "/exit": "יציאה",
}
ARGUMENT_COMMANDS = {
    "/cd", "/project", "/mode", "/permissions", "/plan", "/undo", "/rewind",
    "/remember", "/run", "/test", "/git", "/resume",
}


class AgentCompleter(Completer):
    def __init__(self, workspace):
        self.workspace = workspace

    def directories(self, argument):
        entered = argument.lstrip()
        entered = entered.replace('"', '')
        if entered == "~":
            yield '~\\', "תיקיית המשתמש"
            return
        # Resolve relative suggestions against the current project, not the launcher cwd.
        separator = max(entered.rfind("\\"), entered.rfind("/"))
        head, prefix = entered[:separator + 1], entered[separator + 1:]
        if len(entered) == 2 and entered[1] == ":":
            head, prefix = entered + "\\", ""
        lookup = Path(os.path.expandvars(os.path.expanduser(head))) if head else self.workspace.project
        if not lookup.is_absolute():
            lookup = self.workspace.project / lookup
        try:
            with os.scandir(lookup) as entries:
                names = sorted(entry.name for entry in entries
                               if entry.name.casefold().startswith(prefix.casefold()) and entry.is_dir())
        except (OSError, ValueError):
            return
        for name in names[:200]:
            value = str(lookup / name) + "\\"
            if argument.lstrip().startswith('"') or any(char.isspace() for char in value):
                value = '"' + value + '"'
            yield value, "תיקייה"

    def get_completions(self, document, complete_event):
        if not document.is_cursor_at_the_end:
            return
        text = document.text_before_cursor
        if not text.startswith("/"):
            return
        command, separator, argument = text.partition(" ")
        if not separator:
            for name, description in COMMANDS.items():
                if name.casefold().startswith(command.casefold()):
                    yield Completion(name + (" " if name in ARGUMENT_COMMANDS else ""),
                                     start_position=-len(text), display=name, display_meta=visual(description))
            return
        if command in ("/cd", "/project"):
            for value, description in self.directories(argument):
                yield Completion(value, start_position=-len(argument), display=visual(value), display_meta=visual(description))
            return
        choices = []
        if command in ("/mode", "/permissions"):
            choices = [(value, "מצב עבודה") for value in ("normal", "acceptEdits", "plan")]
        elif command == "/git":
            choices = [(value, "Git") for value in ("status", "diff", "staged", "log", "branch")]
        elif command == "/resume":
            choices = [("latest", "שיחה אחרונה בפרויקט")]
            choices += [(entry["id"], entry["title"]) for entry in self.workspace.sessions()[:50]
                        if Path(entry["project"]) == self.workspace.project]
        elif command in ("/undo", "/rewind"):
            choices = [(entry["id"], entry["path"]) for entry in reversed(self.workspace.session["checkpoints"])
                       if entry["status"] == "applied"]
        for value, description in choices:
            if value.casefold().startswith(argument.casefold()):
                yield Completion(value, start_position=-len(argument), display_meta=visual(description))


class ConsoleInput:
    def __init__(self, workspace, *, input=None, output=None):
        self.interactive = input is not None or (sys.stdin.isatty() and sys.stdout.isatty())
        self.session = None
        if self.interactive:
            history_path = workspace.root / "state" / "input-history.txt"
            history_path.parent.mkdir(parents=True, exist_ok=True)
            self.session = PromptSession(
                completer=ThreadedCompleter(AgentCompleter(workspace)),
                history=FileHistory(str(history_path)),
                auto_suggest=AutoSuggestFromHistory(),
                complete_while_typing=True, complete_in_thread=True,
                input_processors=[HebrewProcessor()], wrap_lines=False,
                input=input, output=output,
            )

    def read(self):
        if self.session is None:
            return input("אתה: ")
        # Idle memory-cleanup messages redraw the prompt without eating typed input.
        with create_app_session(input=self.session.app.input, output=self.session.app.output), patch_stdout():
            return self.session.prompt(visual("אתה: "))
