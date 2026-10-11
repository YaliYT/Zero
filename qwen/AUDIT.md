# Qwen-Agent Phase 1 audit (no model inference)

Scope: active code only (`Qwen-Agent.py`, `qwen_coding.py`, `qwen_context.py`, `qwen_cpu_runner.py`,
`qwen_memory_guard.py`, `qwen_input.py`, `qwen_terminal.py`). `backup-*` folders were not read or run.
All line numbers refer to the ORIGINAL files (backup folder `Qwen-Agent-backup-<timestamp>`); the work copy has
shifted line numbers where patches were applied (`work\apply_phase1_patches.py` is the exact, re-runnable diff).
Everything below is from reading code; **nothing here is a measurement** of latency. Items marked *needs model*
cannot be settled offline.

## 0. Environment facts that shape the findings
* `temperature 0` + fixed `seed 1234` (`qwen_cpu_runner.py:154`): the same context always yields the same reply,
  so a tool call that does not change the context state will be repeated verbatim → real risk of 16-step loops.
* Context 2048, output 512, buffer 16 → 1520 tokens of input shared by system prompt, 7 tool schemas, notes,
  history and tool results (`qwen_context.py:54`).
* Active-trim threshold in the live settings is 80 % — the minimum the code allows (`qwen_memory_guard.py:140`).

## 1. Findings (severity: H high, M medium, L low)

### A. Memory guard / paging policy
| # | Sev | Where | Finding |
|---|-----|-------|---------|
| A1 | H | `qwen_memory_guard.py:299-313`, `:247-256`, `:305` | `prepare_turn` calls `clean_owned_idle_model(force=True)`: a forced trim bypasses the *already-paged* check (`:251`), the idle grace (`:253`) and the pressure check (`:256`). It therefore runs on **every** user message, even if the idle trim already emptied the working set 30 s earlier, even if the previous turn aborted before reaching the model, and even when RAM is already ≤ target. Each run costs: 2 × `/slots` HTTP (`:266`, `:273`), a `stop_event.wait(2)` (`:281`) **while holding `request_lock`**, and – when the model is resident – forces the first prefill to fault the mmap'd GGUF back in. Historical numbers in the package (29.9 s vs 15.9 s for the two consecutive read_file turns) are consistent with this, but they are not an A/B of the policy. **Fixed (duplicate guard, on)**; pressure floor + cooldown added as opt-in knobs (see §3). Whether the "clear before every message" policy is net-positive needs an A/B with *the model*. |
| A2 | H | `qwen_memory_guard.py:328-366`, settings `memory_active_threshold_percent=80`, `memory_cleanup_active=true` | During a request the guard calls `K32EmptyWorkingSet` on the *generating* llama-server whenever system RAM ≥ 80 % (every ≥120 s). With a 16.8 GB mmap'd model on a 32 GiB box RAM normally sits at ~78-85 % while the model is hot, so this fires mid-generation and evicts pages the next token needs. There is no distinction between prefill / generation / tool execution, and nothing measures hard faults before/after. *Needs model* to quantify; proposal P2. |
| A3 | M | `:236-238`, `:497`, `:449`, `:512` | Cooldown constants are hard-coded (120 s pass, 600 s per process) while only the active interval is configurable; the log line at `:184` advertises them as settings-like values. |
| A4 | M | `:392-424` | `model_is_idle` polls `/slots` up to 3× per trim (check, re-check under handle, plus monitor). Comment at `:265` itself notes `/slots` resets the native sleep timer; harmless today (`native_sleep_idle_seconds=-1`) but blocks enabling idle-unload later without refactor. |
| A5 | M | `:387-390`, `qwen-memory-cleanup.jsonl` | Telemetry log is append-only/unbounded and re-opened on every event; `_restore_cooldowns` re-reads the last 64 KiB at start. Low cost today; add rotation before long benchmark campaigns. |
| A6 | L | `:223-241` | 5 s poll loop calls `api.snapshot()` (incl. `psutil.swap_memory`) every cycle even when nothing can act (no request active, turn active). Cheap, but it is noise in any "disk reads at idle" measurement. |
| A7 | L | `:164-188` | The monitor mutex `Local\QwenAgentMemoryGuard` means a *second* agent window silently runs without any guard; combined with the one-instance port check this is fine, but undocumented to the user. |

### B. Tool loop, mutations and idempotency
| # | Sev | Where | Finding |
|---|-----|-------|---------|
| B1 | H | `Qwen-Agent.py:140-153` | No progress detection: identical tool calls (deterministic at temp 0) are executed up to 16 times; read-only repeats burn tokens, failed edits repeat the same error, and a denied `run_powershell` re-prompts the user each round. **Fixed.** |
| B2 | H | `Qwen-Agent.py:143-144` | `json.loads(arguments)` is unguarded: a malformed/truncated-but-finished tool JSON raised out of `_agent_turn`, aborting the whole turn ("interrupted") instead of returning an error to the model; `call["function"]["name"]` KeyError likewise. Multi-call messages left later calls without tool results. **Fixed.** |
| B3 | H | `qwen_coding.py:472-488` (+`:424-463`) | Double-execution risk: `edit_file` is only idempotent when `new_text` does not contain `old_text`. Edit `x = 1` → `x = 1\ny = 2` applied twice (same message twice, or a model retry) yields `y = 2` twice; every application also gets its own checkpoint and, in normal mode, its own approval prompt. `write_file overwrite=true` is idempotent (`:429`). `run_powershell` has no idempotency by design (tests are legitimately re-run). **Fixed for edit/write (per-turn, hash-verified).** |
| B4 | M | `qwen_coding.py:228-235`, `:167-169`, `:47-55` | Write amplification: every tool call (`audit`) plus `begin_turn`, `finish_turn` and twice per edit in `change()` (`:449`, `:462`) rewrites the *entire* session JSON (`indent=2`, all historical tool results incl. 8 KB stdout and full `write_file` contents), and the same payload is appended to `qwen-agent-actions.jsonl`. Cost grows with session length; also page-cache/disk churn during a turn. Proposal P4. |
| B5 | M | `qwen_coding.py:47-55`, `:452-458` | Atomic writes use temp + `os.replace` but never flush/fsync: power loss can leave a zero-length session or edited file despite "atomic". |
| B6 | M | `qwen_coding.py:150-161` | `resolve()` follows links and checks the *resolved* path, so links leaving the project/entering the agent folder are refused; links that stay inside the project edit the target. Only hard links had a test → added `test_link_boundaries.py` (symlink/junction). In-project link edits remain target edits (design choice, documented). |
| B7 | L | `qwen_coding.py:415-422`, `:437`, `:454`, `:459` | A single edit reads the file 4×; irrelevant for ≤2 MiB but part of the "disk read" count in tool-heavy turns. |
| B8 | L | `qwen_coding.py:344-356` | `files()` resolves each path twice; 20 000-file cap makes this ~40 k realpath syscalls per pattern listing / non-rg search. |

### C. Context, compaction, tokens
| # | Sev | Where | Finding |
|---|-----|-------|---------|
| C1 | H | `qwen_coding.py:268-280` | `context()` ends with `"\n".join(parts)[-1800:]`, i.e. it cuts **from the front**. Parts are ordered notes → tasks → summary → last two turns; two ordinary turns already reach ~2 600 chars, so the user's explicit `/remember` notes, the task list and the summary are the *first* things silently removed. **Fixed** (priority truncation, identical output when under 1800 chars). |
| C2 | H | `qwen_coding.py:282-293` | `/compact` rebuilds the summary from `history[-6:]` and **overwrites** the previous one: a second compact forgets everything older than six turns; failures and shell commands/exit codes are never recorded (only `ok` tools with a path), so after compact the model can retry a failed edit or re-run a command. **Fixed** (cumulative, incremental, records failures/commands, still ≤900 chars). Residual: 900-char budget is small; summaries are lossy by design. |
| C3 | M | `qwen_context.py:65-68` | When over budget, all tool groups except the latest are dropped without any note → the model loses what it already read/edited this turn and may re-read (feeds B1). Proposal P3 (one-line "earlier actions: name:path…" stub; needs model to validate token/quality effect). |
| C4 | M | `qwen_context.py:55-89` | `counter()` = 2 HTTP calls; a compaction pass called it up to 7 times, several on identical candidates (`:69` and `:78` recount an unchanged list). **Fixed** (memoised; identical result). Each counted request is also tokenised/templated again by `/v1/chat/completions` — unavoidable. |
| C5 | M | `qwen_context.py:74` | `json.loads(arguments)` on history could abort compaction for malformed history. **Fixed.** |
| C6 | M | `Qwen-Agent.py:152` | Tool results enter `messages` untruncated (stdout up to 8 000 + 3 000 chars); they are shrunk only when the whole prompt is over budget, after paying for counting. Proposal P5 (cap at insertion, keep full result in audit log). |
| C7 | L | `qwen_coding.py:325-342` | `read_file` default `limit=20` lines with 1 800-char cap → many small pages; pagination is correct (tests exist) but a bigger default could save rounds. *Needs model* (token budget trade-off). |

### D. Hebrew / streaming / input
| # | Sev | Where | Finding |
|---|-----|-------|---------|
| D1 | M | `qwen_input.py:87`, `qwen_coding.py:178-187` | `complete_while_typing=True` + `/resume` completion calls `workspace.sessions()` which parsed **every session JSON on every keystroke** (threaded, but still disk + CPU). **Fixed** (stat-signature cache; only changed files re-parsed). |
| D2 | M | `qwen_terminal.py:78`, `:135-142` | Wrapping uses `len()`/`textwrap` on code points, not display width (niqqud/combining marks are width 0, wide glyphs width 2) → early/late wraps. No test with niqqud, wide chars, or window resize. |
| D3 | M | `qwen_terminal.py:77` | Lines containing ANSI escapes are never reordered (Hebrew coloured output stays logical order). |
| D4 | L | `qwen_terminal.py:27-30` | Isolate controls (LRI/RLI/FSI/PDI) are dropped for display; base direction is hard-coded LTR. Deliberate, untested for paragraphs starting with Hebrew + numbers/punctuation. |
| D5 | L | `qwen_cpu_runner.py:160` | A `DisplayStream` (prints `Qwen: `) is opened for every round, so tool-call-only replies print an empty `Qwen:` line each step. |
| D6 | L | `qwen_input.py:102-103` | `input-history.txt` grows without bound (FileHistory). |
| D7 | L | tests | Not covered: pasted multi-line text, cursor/selection in wrapped RTL lines, resize during stream, `\r` in model output, Hebrew in `/diff` output, Ctrl+C during stream, server disconnect mid-SSE (only truncated-tool-call and `[DONE]`-missing are tested). |

### E. Runner / startup
| # | Sev | Where | Finding |
|---|-----|-------|---------|
| E1 | M | `qwen_cpu_runner.py:67-71` | `start()` hard-requires Ollama's server (`POST /api/generate keep_alive 0`, timeout 30 s, no try/except): if Ollama is not running the agent cannot start although it only needs llama-server. Also an unconditional ≤30 s startup cost. Proposal P6 (tolerate `URLError`; *needs a launch test with the model*). |
| E2 | L | `qwen_cpu_runner.py:46-49`, `:108-118` | Load wait polls `/health` every ~1 s for 180 s; failure paths raise but leave the job/log handle for `close()` — fine in `main()` due to `finally`. |
| E3 | L | `Qwen-Agent.py:224` | Startup banner hard-codes "4 P cores / 12 threads" instead of reading settings. |

## 2. Proposed changes, prioritised
| Pri | Change | Needs model? | Status |
|-----|--------|--------------|--------|
| P0 | Duplicate-cleanup guard for forced prepare trim | no | **done** |
| P0 | Malformed tool JSON → feedback; no-progress repeat guard; idempotent edit/write guard | no | **done** |
| P0 | `context()` priority truncation (notes/tasks first) and cumulative `/compact` | no | **done** |
| P1 | Opt-in pressure floor `memory_prepare_min_percent` and trim cooldown `memory_model_trim_cooldown_seconds` (default 0 = off) | A/B yes | **scaffolding done, off** |
| P1 | A/B (≥5 reps, alternating order, 16-token probes first): prepare-trim on/off/floor; active trim 80 % vs 90 % vs off; record hard faults (`ProcessMemory.faults` already read in `qwen_memory_guard.py:44` but never recorded) and TTFT | **yes** | blocked in Phase 1 |
| P2 | Phase state (idle / prefill / generation / tool) from `native_chat` first-token event; never trim in generation; trim only at prefill-start or idle | yes | open |
| P3 | Short "earlier actions" stub when compaction drops tool groups | yes | open |
| P4 | Store capped tool results in session history (full text only in the actions log); fsync on atomic writes; log rotation | no | open (touches persisted format → needs migration care) |
| P5 | Cap tool-result size at insertion into `messages` | partly | open |
| P6 | Make Ollama unload at startup best-effort | launch test | open |
| P7 | Hebrew tests: niqqud/wide-char width, ANSI lines, resize, paste; width-aware wrapping | no (code) | open |
