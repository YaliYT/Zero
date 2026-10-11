"""Qwen Code: local coding tools, sessions and bounded native-model context."""
import argparse
import json
import sys
import urllib.request
from pathlib import Path
from qwen_memory_guard import MemoryGuard
from qwen_cpu_runner import NativeRunner, native_chat
from qwen_coding import CodingWorkspace
from qwen_context import fit_messages
from qwen_terminal import terminal_print as print, visual, DisplayStream

MODEL = "qwen3.8:latest"
ROOT = Path(__file__).resolve().parent
SETTINGS = ROOT / "qwen-agent-settings.json"
MEMORY_GUARD = None
WORKSPACE = None
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


def approve(text, interactive):
    if not interactive:
        return False
    print(text, flush=True)
    return input(visual("לאשר? [y/N]: ")).strip().lower() in ("y", "yes", "כן")


def parse_tool_arguments(raw):
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


def execute_tool(name, arguments, interactive=True):
    return coding_workspace().execute(name, arguments, interactive, approve)


def coding_workspace():
    global WORKSPACE
    if WORKSPACE is None:
        WORKSPACE = CodingWorkspace(ROOT)
    return WORKSPACE


def runtime_options():
    settings = json.loads(SETTINGS.read_text(encoding="utf-8-sig"))
    layers = int(settings["num_gpu"])
    context = int(settings["num_ctx"])
    if not 0 <= layers <= 65 or context != 2048:
        raise ValueError("Invalid tested runtime settings: expected 0-65 GPU layers and context 2048.")
    options = {"num_gpu": layers, "num_ctx": context, "num_predict": 512, "temperature": 0}
    limits = {"num_thread": (1, 16), "num_batch": (32, 512), "draft_num_predict": (0, 8)}
    for name, (minimum, maximum) in limits.items():
        if name in settings:
            value = int(settings[name])
            if not minimum <= value <= maximum:
                raise ValueError(f"Invalid {name}: expected {minimum}-{maximum}.")
            options[name] = value
    return options


def chat_request(messages):
    if MEMORY_GUARD:
        MEMORY_GUARD.mark_request_active()
    try:
        return _stream_chat_request(messages)
    finally:
        if MEMORY_GUARD:
            MEMORY_GUARD.mark_request_finished()


def _stream_chat_request(messages):
    settings = json.loads(SETTINGS.read_text(encoding="utf-8-sig"))
    workspace = coding_workspace()
    tools = workspace.tools()
    if settings.get("native_runner_enabled"):
        port = int(settings.get("native_runner_port", 57206))
        fitted, tokens, compacted = fit_messages(messages, tools, port, context=int(settings["num_ctx"]))
        workspace.last_context_tokens = tokens
        if compacted:
            print("[הקשר צומצם לבקשה; ההיסטוריה המלאה נשמרת בדיסק]", flush=True)
        if settings.get('native_greedy_sampling', False):
            return native_chat(fitted, tools, port, greedy_only=True)
        return native_chat(fitted, tools, port)
    body = {"model": MODEL, "messages": messages, "tools": tools, "stream": True,
            "think": False, "keep_alive": "30m", "options": runtime_options()}
    request = urllib.request.Request("http://127.0.0.1:11434/api/chat", json.dumps(body).encode("utf-8"),
                                     {"Content-Type": "application/json"}, method="POST")
    content, calls, done = [], [], False
    with DisplayStream() as display, urllib.request.urlopen(request, timeout=300) as response:
        for line in response:
            if not line.strip():
                continue
            chunk = json.loads(line)
            if chunk.get("error"):
                raise RuntimeError(chunk["error"])
            message = chunk.get("message", {})
            if message.get("content"):
                content.append(message["content"])
                display.feed(message["content"])
            calls.extend(message.get("tool_calls", []))
            if chunk.get("done"):
                done = True
                break
    if not done:
        raise RuntimeError("Ollama disconnected before finishing the response.")
    message = {"role": "assistant", "content": "".join(content)}
    if calls:
        message["tool_calls"] = calls
    return message


def agent_turn(prompt, previous="", interactive=True):
    workspace = coding_workspace()
    workspace.begin_turn(prompt)
    guard = MEMORY_GUARD
    if guard:
        guard.prepare_turn()
    try:
        result = _agent_turn(prompt, previous, interactive)
        workspace.finish_turn(result=result)
        return result
    except BaseException as error:
        workspace.finish_turn(error=str(error) or type(error).__name__)
        raise
    finally:
        if guard:
            guard.finish_turn()


def _agent_turn(prompt, previous="", interactive=True):
    workspace = coding_workspace()
    messages = [{"role": "system", "content": workspace.system()}]
    context = workspace.context()
    if context or previous:
        messages.append({"role": "user", "content": "Recent work, context only:\n" + context + previous[-700:],
                         "context_only": True})
    messages.append({"role": "user", "content": prompt})
    trace = []
    blocked = 0
    for step in range(16):
        message = chat_request(messages)
        messages.append(message)
        calls = message.get("tool_calls", [])
        if not calls:
            return {"answer": message["content"], "tools": trace, "prompt": prompt}
        for call in calls:
            function = call.get("function") or {}
            name = function.get("name") or ""
            arguments, problem = parse_tool_arguments(function.get("arguments", {}))
            print(f"[שלב {step+1}/16 | כלי: {name}]", flush=True)
            if problem:
                result = {"ok": False, "error": problem}
                coding_workspace().audit(name or "invalid_call", {"raw": str(function.get("arguments"))[:500]}, result)
            else:
                result = execute_tool(name, arguments, interactive)
            blocked = blocked + 1 if result.get("guard") == "repeat" else blocked
            trace.append({"name": name, "arguments": arguments, "result": result})
            if name == "write_file" and result.get("ok"):
                print(f"נוצר ואומת: {result['path']}", flush=True)
            if not result.get("ok"):
                print("שגיאה: " + result.get("error", result.get("stderr", "Tool failed")), flush=True)
            messages.append({"role": "tool", "tool_name": name,
                             "content": json.dumps(workspace.model_result(name, result), ensure_ascii=False, separators=(',', ':'))})
        if blocked >= MAX_BLOCKED_CALLS:
            raise RuntimeError("Stopped: the model kept repeating identical tool calls without progress. "
                               "Completed actions and conversation are saved; rephrase the request or /resume.")
    raise RuntimeError("Stopped after 16 agent steps. Completed actions and conversation are saved; /resume continues the session.")


def parse_arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task")
    parser.add_argument("--report")
    parser.add_argument("--project")
    parser.add_argument("--mode", choices=["normal", "acceptEdits", "plan"], default="normal")
    parser.add_argument("--resume", nargs="?", const="latest")
    parser.add_argument("--continue", dest="resume", action="store_const", const="latest")
    return parser.parse_args()


def run_agent(args):
    workspace = coding_workspace()
    if args.task:
        result = agent_turn(args.task, interactive=False)
        if args.report:
            Path(args.report).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return
    options = runtime_options()
    from qwen_input import ConsoleInput
    editor = ConsoleInput(workspace)
    print(f"Qwen Code | CPU + GPU ({options['num_gpu']} layers) | Context {options['num_ctx']}")
    print(f"פרויקט: {workspace.project}\nשיחה: {workspace.session['id']} | מצב: {workspace.mode}")
    print("עריכה, חיפוש, בדיקות ושיחות שמורות. /help לפקודות; /exit ליציאה.\n")
    if editor.interactive:
        print("השלמה: Tab | בחירה: חצים + Enter | היסטוריה: ↑ ↓ | הצעה מההיסטוריה: →\n")
    settings = json.loads(SETTINGS.read_text(encoding="utf-8-sig"))
    if settings.get("memory_cleanup_enabled", True):
        targets = "תוכנות רקע ו-llama-server בין תשובות" if settings.get("memory_cleanup_llama") else "תוכנות רקע"
        print(f"ניקוי RAM מעל {settings.get('memory_threshold_percent', 80)}%; יעד: {settings.get('memory_target_percent', 78)}%: {targets}.")
        if settings.get('memory_prepare_request_enabled'):
            floor = int(settings.get('memory_prepare_min_percent', 0))
            if floor:
                print(f"שומר את המודל בזיכרון בין הודעות; ניקוי לפני הודעה רק מעל {floor}% RAM. Windows מנהל את ההעברה לדיסק לפי הצורך.")
            else:
                print("ניקוי לפני כל הודעה; Windows מחזיר דפים ל-RAM לפי הצורך ומנהל את הגיבוי בדיסק.")
        if settings.get('memory_idle_trim_enabled'):
            print(f"ניקוי נוסף אחרי {settings.get('memory_idle_trim_seconds', 30)} שניות המתנה; המודל נשאר טעון. יעד 40% בזמן תשובה אינו מובטח.")
        if settings.get('native_sleep_idle_seconds', -1) >= 15:
            print(f"פריקת המודל אחרי {settings['native_sleep_idle_seconds']} שניות ללא בקשות; טעינה מחדש בהודעה הבאה. 40% בזמן תשובה אינו מובטח.\n")
        if settings.get('memory_cleanup_active'):
            print(f"ניקוי המודל גם בזמן תשובה מעל {settings.get('memory_active_threshold_percent', 90)}% RAM; לכל היותר פעם ב-{settings.get('memory_active_interval_seconds', 120)} שניות.\n")
    while True:
        try:
            prompt = editor.read().strip()
            if prompt == "/exit":
                break
            if not prompt:
                continue
            if prompt.startswith("/"):
                prompt = workspace.command(prompt)
                if not prompt:
                    continue
            agent_turn(prompt)
        except KeyboardInterrupt:
            print("\nהבקשה הופסקה. פעולות שכבר בוצעו נשמרו.\n")
        except EOFError:
            break
        except Exception as error:
            print(f"שגיאה: {error}\n", flush=True)


def main():
    global MEMORY_GUARD, WORKSPACE
    args = parse_arguments()
    WORKSPACE = CodingWorkspace(ROOT, project=args.project, mode=args.mode, resume=args.resume)
    settings = json.loads(SETTINGS.read_text(encoding="utf-8-sig"))
    guard = MemoryGuard(ROOT, settings)
    MEMORY_GUARD = guard
    runner = NativeRunner(ROOT, settings) if settings.get("native_runner_enabled") else None
    try:
        guard.start()
        if runner:
            print(f"טוען Qwen | תשובה: {settings['num_thread']} Threads | עיבוד קלט: {settings['num_thread_batch']} Threads...", flush=True)
            runner.start()
            guard.bind_model(runner.process.pid)
        run_agent(args)
    finally:
        guard.close()
        if runner:
            runner.close()
        MEMORY_GUARD = None


if __name__ == "__main__":
    main()
