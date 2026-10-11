"""Phase-1 low-risk patches, applied idempotently to the WORK COPY only.

Usage: python work\\apply_phase1_patches.py [root]   (root defaults to the parent of work\\)
Each patch is an exact-anchor replacement on LF-normalised text; original line endings are
restored when writing. A patch whose marker is already present is skipped, so re-running is safe.
"""
import sys
from pathlib import Path

ROOT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
applied = []


def patch(filename, marker, edits):
    path = ROOT / filename
    raw = path.read_bytes()
    crlf = b"\r\n" in raw
    bom = raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig").replace("\r\n", "\n")
    if marker in text:
        print(f"skip   {filename}: {marker!r} already present")
        return
    for old, new in edits:
        if text.count(old) != 1:
            raise SystemExit(f"{filename}: anchor not unique/found ({text.count(old)}x): {old[:70]!r}")
        text = text.replace(old, new, 1)
    if crlf:
        text = text.replace("\n", "\r\n")
    data = text.encode("utf-8")
    path.write_bytes((b"\xef\xbb\xbf" if bom else b"") + data)
    applied.append(filename)
    print(f"patched {filename}")


# ---------------------------------------------------------------- qwen_memory_guard.py
patch("qwen_memory_guard.py", "memory_model_trim_cooldown_seconds", [
    ('''        self.last_request_finished = time.monotonic()
        self.idle_paged = False
        self.prepare_request_enabled''',
     '''        self.last_request_finished = time.monotonic()
        self.idle_paged = False
        # Phase-1 scaffolding. Both knobs default to 0 = off, i.e. unchanged behaviour.
        self.prepare_min_percent = max(0, min(95, int(settings.get("memory_prepare_min_percent", 0))))
        self.model_trim_cooldown = max(0, int(settings.get("memory_model_trim_cooldown_seconds", 0)))
        self.last_model_trim = float("-inf")
        self.skip_reason = None
        self.prepare_request_enabled'''),
    ('''"llama_cleanup": self.clean_llama, "llama_idle_seconds": self.llama_idle_seconds})''',
     '''"llama_cleanup": self.clean_llama, "llama_idle_seconds": self.llama_idle_seconds,
                     "prepare_min_percent": self.prepare_min_percent,
                     "model_trim_cooldown_seconds": self.model_trim_cooldown})'''),
    ('''            if not force and (not self.idle_trim_enabled or self.idle_paged or self.turn_active):
                return None
''',
     '''            if not force and (not self.idle_trim_enabled or self.idle_paged or self.turn_active):
                return None
            if force and self.idle_paged:
                # Duplicate-cleanup guard: the model was already trimmed (idle or earlier prepare) and no
                # request has run since, so a second EmptyWorkingSet would only cost the settle wait.
                self.skip_reason = "already_paged_since_last_request"
                return None
'''),
    ('''            if not force and before["used_percent"] <= self.target:
                return None
            pid = self.owned_model_pid
''',
     '''            if not force and before["used_percent"] <= self.target:
                return None
            if self.model_trim_cooldown and time.monotonic() - self.last_model_trim < self.model_trim_cooldown:
                self.skip_reason = "model_trim_cooldown"
                return None
            if force and self.prepare_min_percent and before["used_percent"] < self.prepare_min_percent:
                self.skip_reason = "ram_below_prepare_min_percent"
                return None
            pid = self.owned_model_pid
'''),
    ('''                self.idle_paged = ok
                if ok:
                    self.last_active_cleanup = time.monotonic()
''',
     '''                self.idle_paged = ok
                if ok:
                    self.last_active_cleanup = time.monotonic()
                    self.last_model_trim = time.monotonic()
'''),
    ('''            try:
                result = self.clean_owned_idle_model(force=True) if self.prepare_request_enabled else None
                snapshot = self.api.snapshot()
                self.record({"time": time.time(), "event": "turn_started", "snapshot": snapshot,
                             "model_paged": bool(result and result["ok"]), "disk_backing": "mapped_model_and_windows_pagefile"})''',
     '''            try:
                self.skip_reason = None
                result = self.clean_owned_idle_model(force=True) if self.prepare_request_enabled else None
                snapshot = self.api.snapshot()
                self.record({"time": time.time(), "event": "turn_started", "snapshot": snapshot,
                             "model_paged": bool(result and result["ok"]), "prepare_skip_reason": self.skip_reason,
                             "disk_backing": "mapped_model_and_windows_pagefile"})'''),
])

# ---------------------------------------------------------------- qwen_context.py
patch("qwen_context.py", "_memoized", [
    ('''def fit_messages(messages, tools, port, context=2048, output=512, counter=None):
    counter = counter or (lambda value: count_tokens(value, tools, port))
''',
     '''def _memoized(counter):
    """Each count is two HTTP calls; identical candidates (common between compaction stages) reuse one."""
    seen = {}

    def count(value):
        key = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        if key not in seen:
            seen[key] = counter(value)
        return seen[key]
    return count


def fit_messages(messages, tools, port, context=2048, output=512, counter=None):
    counter = _memoized(counter or (lambda value: count_tokens(value, tools, port)))
'''),
    ('''                if isinstance(arguments, str):
                    arguments = json.loads(arguments)
                # These arguments were already executed''',
     '''                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments)
                    except ValueError:
                        arguments = {"raw": arguments}  # malformed history must not abort compaction
                # These arguments were already executed'''),
])

# ---------------------------------------------------------------- qwen_coding.py
patch("qwen_coding.py", "REPEAT_LIMIT", [
    ('''READ_ONLY = {"read_file", "list_directory", "search_files", "update_tasks"}
''',
     '''READ_ONLY = {"read_file", "list_directory", "search_files", "update_tasks"}
MUTATING = {"edit_file", "write_file"}
REPEAT_LIMIT = 2  # an identical call with an identical outcome and no change in between is refused the third time
CONTEXT_LIMIT = 1800
'''),
    ('''def digest(data):
    return hashlib.sha256(data).hexdigest()
''',
     '''def digest(data):
    return hashlib.sha256(data).hexdigest()


def call_key(name, arguments):
    try:
        return name + "\\0" + json.dumps(arguments, sort_keys=True, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return None
'''),
    ('''        self.session = None
        self.current_turn = None
        self.last_context_tokens = None
        if resume:''',
     '''        self.session = None
        self.current_turn = None
        self.last_context_tokens = None
        self.reset_turn_guards()
        self._session_cache = {}
        if resume:'''),
    ('''    def sessions(self):
        values = []
        for path in (self.state/"sessions").glob("*.json"):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                values.append({"id": value["id"], "project": value["project"], "updated": value["updated"],
                               "title": value["history"][0]["prompt"][:60] if value["history"] else "שיחה חדשה"})
            except (OSError, KeyError, ValueError):
                continue
        return sorted(values, key=lambda value: value["updated"], reverse=True)
''',
     '''    def sessions(self):
        # Tab completion lists sessions on every keystroke; re-parse only files whose stat changed.
        values, seen = [], set()
        for path in (self.state/"sessions").glob("*.json"):
            try:
                info = path.stat()
                signature = (info.st_mtime_ns, info.st_size)
                cached = self._session_cache.get(path)
                if cached is None or cached[0] != signature:
                    value = json.loads(path.read_text(encoding="utf-8"))
                    cached = (signature, {"id": value["id"], "project": value["project"], "updated": value["updated"],
                                          "title": value["history"][0]["prompt"][:60] if value["history"] else "שיחה חדשה"})
                    self._session_cache[path] = cached
                seen.add(path)
                values.append(dict(cached[1]))
            except (OSError, KeyError, ValueError):
                self._session_cache.pop(path, None)
                continue
        for path in [item for item in self._session_cache if item not in seen]:
            del self._session_cache[path]
        return sorted(values, key=lambda value: value["updated"], reverse=True)
'''),
    ('''    def begin_turn(self, prompt):
        self.current_turn = uuid.uuid4().hex[:12]''',
     '''    def reset_turn_guards(self):
        self.turn_calls = {}       # call key -> repeat bookkeeping for the current user turn
        self.applied_edits = {}    # resolved path -> last applied edit key and resulting hash
        self.mutation_epoch = 0

    def begin_turn(self, prompt):
        self.reset_turn_guards()
        self.current_turn = uuid.uuid4().hex[:12]'''),
    ('''        parts = ["User project notes: " + "; ".join(notes["notes"])[-450:]] if notes["notes"] else []
        if self.session["tasks"]:
            parts.append("Tasks: " + "; ".join(self.session["tasks"])[:500])
        if self.session.get("summary"):
            parts.append("Earlier work (context): " + self.session["summary"])
        for turn in self.session["history"][self.session.get("context_after", 0):][-2:]:
            actions = "; ".join(item["tool"] + ":" + str(item["result"].get("path", item["result"].get("ok")))
                                for item in turn.get("tools", []))
            parts.append("User: " + turn["prompt"][-400:] + "\\nAssistant: " + turn["answer"][-500:] +
                         "\\nExecuted tools: " + actions[-400:])
        return "\\n".join(parts)[-1800:]
''',
     '''        head = ["User project notes: " + "; ".join(notes["notes"])[-450:]] if notes["notes"] else []
        if self.session["tasks"]:
            head.append("Tasks: " + "; ".join(self.session["tasks"])[:500])
        summary = ("Earlier work (context): " + self.session["summary"]) if self.session.get("summary") else ""
        recent = []
        for turn in self.session["history"][self.session.get("context_after", 0):][-2:]:
            actions = "; ".join(item["tool"] + ":" + str(item["result"].get("path", item["result"].get("ok")))
                                for item in turn.get("tools", []))
            recent.append("User: " + turn["prompt"][-400:] + "\\nAssistant: " + turn["answer"][-500:] +
                          "\\nExecuted tools: " + actions[-400:])
        text = "\\n".join(head + ([summary] if summary else []) + recent)
        if len(text) <= CONTEXT_LIMIT:
            return text
        # Over budget: cut the oldest recent-turn text first. The old tail slice dropped the user's
        # explicit notes and tasks before anything else.
        fixed = len("\\n".join(head)) + (1 if head else 0)
        summary = summary[-max(0, CONTEXT_LIMIT - fixed - 500):] if summary else ""
        prefix = "\\n".join(head + ([summary] if summary else []))
        room = max(0, CONTEXT_LIMIT - len(prefix) - 1)
        tail = "\\n".join(recent)[-room:] if room else ""
        return (prefix + ("\\n" + tail if tail else ""))[-CONTEXT_LIMIT:]
'''),
    ('''        history = self.session["history"]
        parts = []
        for turn in history[-6:]:
            parts.append(turn["prompt"][-100:] + " => " + turn["answer"][-120:])
            for entry in turn.get("tools", []):
                if entry["result"].get("ok"):
                    parts.append(entry["tool"] + " " + str(entry["result"].get("path", ""))[-120:])
        self.session["summary"] = "\\n".join(parts)[-900:]
        self.session["context_after"] = len(history)''',
     '''        history = self.session["history"]
        start = min(self.session.get("context_after", 0), len(history))
        if start == len(history) and self.session.get("summary"):
            return self.session["summary"]  # nothing new to summarise
        # Keep the previous summary: replacing it dropped everything older than six turns on each /compact.
        parts = [self.session["summary"]] if self.session.get("summary") else []
        for turn in history[start:][-6:]:
            parts.append(turn["prompt"][-100:] + " => " + turn["answer"][-120:])
            for entry in turn.get("tools", []):
                result = entry["result"]
                if not result.get("ok"):
                    parts.append("failed " + entry["tool"] + ": " + str(result.get("error", result.get("stderr", "")))[:80])
                elif entry["tool"] == "run_powershell":
                    parts.append("run " + str(entry["arguments"].get("command", ""))[:80] + " exit=" + str(result.get("exit_code")))
                else:
                    parts.append(entry["tool"] + " " + str(result.get("path", ""))[-120:])
        self.session["summary"] = "\\n".join(parts)[-900:]
        self.session["context_after"] = len(history)'''),
    ('''    def execute(self, name, arguments, interactive=True, approve=None):
        try:
            if name not in {tool["function"]["name"] for tool in TOOLS}:
                raise ValueError("Unknown tool: " + name)
            if self.mode == "plan" and name not in READ_ONLY:
                raise PermissionError("Plan mode blocks file edits and shell execution.")
            if name == "read_file":
                result = self.read_file(**arguments)''',
     '''    def guard_call(self, name, arguments, key):
        """Refuse calls that cannot make progress. Never executes anything and never widens permissions."""
        if name in MUTATING and isinstance(arguments, dict) and key:
            try:
                path = self.resolve(arguments["path"])
                record = self.applied_edits.get(str(path))
                if record and record["key"] == key and path.is_file() and digest(path.read_bytes()) == record["after_hash"]:
                    return {"ok": True, "guard": "duplicate", "path": str(path), "changed": False, "verified": True,
                            "note": "This identical change was already applied in this turn and the file is unchanged since; not applied again."}
            except (OSError, KeyError, ValueError, PermissionError):
                pass
        entry = self.turn_calls.get(key) if key else None
        if entry and entry["count"] >= REPEAT_LIMIT and entry["epoch"] == self.mutation_epoch:
            return {"ok": False, "guard": "repeat",
                    "error": f"Identical {name} call already returned the same result {entry['count']} times with no change in between; "
                             "not executed. Use that result, try a different approach, or answer the user."}
        return None

    def note_outcome(self, name, arguments, key, result):
        if result.get("guard"):
            return
        epoch = self.mutation_epoch
        if name in MUTATING and result.get("ok") and result.get("checkpoint") and isinstance(arguments, dict):
            for checkpoint in reversed(self.session["checkpoints"]):
                if checkpoint["id"] == result["checkpoint"]:
                    self.applied_edits[checkpoint["path"]] = {"key": key, "after_hash": checkpoint["after_hash"]}
                    break
        if key:
            outcome = digest(json.dumps(result, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8"))
            entry = self.turn_calls.get(key)
            if entry and entry["outcome"] == outcome and entry["epoch"] == epoch:
                entry["count"] += 1
            else:
                self.turn_calls[key] = {"count": 1, "outcome": outcome, "epoch": epoch}
        # Anything that may have changed the project invalidates earlier "same result" evidence.
        if name == "run_powershell" and "not approved" not in str(result.get("error", "")):
            self.mutation_epoch += 1
        elif name in MUTATING and result.get("ok") and result.get("changed") is not False:
            self.mutation_epoch += 1

    def execute(self, name, arguments, interactive=True, approve=None):
        key = call_key(name, arguments)
        try:
            if name not in {tool["function"]["name"] for tool in TOOLS}:
                raise ValueError("Unknown tool: " + name)
            if self.mode == "plan" and name not in READ_ONLY:
                raise PermissionError("Plan mode blocks file edits and shell execution.")
            result = self.guard_call(name, arguments, key)
            if result is not None:
                pass
            elif name == "read_file":
                result = self.read_file(**arguments)'''),
    ('''        except Exception as error:
            result = {"ok": False, "error": str(error)}
        self.audit(name, arguments, result)
        return result
''',
     '''        except Exception as error:
            result = {"ok": False, "error": str(error)}
        self.note_outcome(name, arguments, key, result)
        self.audit(name, arguments, result)
        return result
'''),
])

# ---------------------------------------------------------------- Qwen-Agent.py
patch("Qwen-Agent.py", "parse_tool_arguments", [
    ('''def execute_tool(name, arguments, interactive=True):''',
     '''def parse_tool_arguments(raw):
    """Return (arguments, problem). Malformed model output becomes tool feedback instead of aborting the turn."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw) if raw.strip() else {}
        except ValueError as error:
            return {}, f"Tool arguments were not valid JSON ({error}); no tool was executed. Send one complete call."
    if not isinstance(raw, dict):
        return {}, "Tool arguments must be a JSON object; no tool was executed."
    return raw, None


MAX_BLOCKED_CALLS = 3


def execute_tool(name, arguments, interactive=True):'''),
    ('''    trace = []
    for step in range(16):''',
     '''    trace = []
    blocked = 0
    for step in range(16):'''),
    ('''            function = call["function"]
            name, arguments = function["name"], function.get("arguments", {})
            if isinstance(arguments, str):
                arguments = json.loads(arguments)
            print(f"[שלב {step+1}/16 | כלי: {name}]", flush=True)
            result = execute_tool(name, arguments, interactive)
            trace.append''',
     '''            function = call.get("function") or {}
            name = function.get("name") or ""
            arguments, problem = parse_tool_arguments(function.get("arguments", {}))
            print(f"[שלב {step+1}/16 | כלי: {name}]", flush=True)
            if problem:
                result = {"ok": False, "error": problem}
                coding_workspace().audit(name or "invalid_call", {"raw": str(function.get("arguments"))[:500]}, result)
            else:
                result = execute_tool(name, arguments, interactive)
            blocked = blocked + 1 if result.get("guard") == "repeat" else blocked
            trace.append'''),
    ('''            messages.append({"role": "tool", "tool_name": name, "content": json.dumps(result, ensure_ascii=False)})
    raise RuntimeError("Stopped after 16''',
     '''            messages.append({"role": "tool", "tool_name": name, "content": json.dumps(result, ensure_ascii=False)})
        if blocked >= MAX_BLOCKED_CALLS:
            raise RuntimeError("Stopped: the model kept repeating identical tool calls without progress. "
                               "Completed actions and conversation are saved; rephrase the request or /resume.")
    raise RuntimeError("Stopped after 16'''),
])

print("applied:", applied or "nothing (already patched)")
