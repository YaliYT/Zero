"""Count the native model's actual rendered prompt and fit its tested context."""
import copy
import json
import urllib.request
from qwen_cpu_runner import convert_messages


def post(port, endpoint, body):
    request = urllib.request.Request(f"http://127.0.0.1:{port}/{endpoint}",
                                     json.dumps(body, ensure_ascii=False).encode("utf-8"),
                                     {"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)


def count_tokens(messages, tools, port):
    rendered = post(port, "apply-template", {"messages": convert_messages(messages), "tools": tools,
                                            "add_generation_prompt": True,
                                            "chat_template_kwargs": {"enable_thinking": False}})
    return len(post(port, "tokenize", {"content": rendered["prompt"], "add_special": True})["tokens"])


def shorten(value, limit):
    if isinstance(value, str):
        return value if len(value) <= limit else value[:limit] + "\n[context excerpt; full output saved in session]"
    if isinstance(value, list):
        return [shorten(item, limit) for item in value[:3]]
    if isinstance(value, dict):
        return {key: shorten(item, limit) for key, item in value.items()}
    return value


def shorten_result(value, limit):
    result = shorten(value, limit)
    if result != value:
        result["context_excerpt"] = True
    if "start_line" in value and isinstance(value.get("content"), str) and len(value["content"]) > limit:
        prefix = value["content"][:limit]
        # Preserve pagination when some of the already-read lines don't fit.
        full_lines = prefix.count("\n")
        if full_lines:
            prefix = prefix[:prefix.rfind("\n")]
            result["next_line"] = value["start_line"] + full_lines
        else:
            result["next_line"] = value["start_line"]
        result["content"] = prefix
        result["truncated"] = True
    return result


def _memoized(counter):
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
    candidate = copy.deepcopy(messages)
    budget = context-output-16
    original = counter(candidate)
    count = original
    if count <= budget:
        return candidate, count, False
    # Disk transcripts remain complete; only the inference copy is compacted.
    if len(candidate)>2 and candidate[1].get("context_only"):
        candidate.pop(1)
        count = counter(candidate)
    if count > budget:
        # Keep the latest completed tool group and its original user request.
        groups = [index for index, item in enumerate(candidate) if item.get("tool_calls")]
        if len(groups) > 1:
            start = groups[-1]
            candidate = candidate[:2] + candidate[start:]
    if counter(candidate) > budget:
        for message in candidate:
            for call in message.get("tool_calls", []):
                arguments = call["function"].get("arguments", {})
                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments)
                    except ValueError:
                        arguments = {"raw": arguments}  # malformed history must not abort compaction
                # These arguments were already executed, not a new tool call.
                call["function"]["arguments"] = shorten(arguments, 100)
    for limit in (900, 500, 250, 100):
        count = counter(candidate)
        if count <= budget:
            return candidate, count, True
        for message in candidate:
            if message["role"] == "tool":
                message["content"] = json.dumps(shorten_result(json.loads(message["content"]), limit),
                                                ensure_ascii=False)
    count = counter(candidate)
    if count > budget and "\nProject guidelines," in candidate[0]["content"]:
        base, guidelines = candidate[0]["content"].split("\nProject guidelines,", 1)
        candidate[0]["content"] = base + "\nProject guidelines (excerpt):" + guidelines[:350]
        count = counter(candidate)
    if count > budget:
        raise ValueError(f"Input needs {count} tokens; available {budget} in the tested 2048 context. "
                         "Use a shorter request, /compact, or smaller file excerpts.")
    return candidate, count, True
