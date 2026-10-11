# Qwen live memory and performance experiments

Same Qwen3.8 weights, GPU 8 layers, generation 4 P cores, batch 12 threads, context 2048. Existing pagefile: 16,384 MiB; live Windows reading before this experiment: 983 MiB used. No model or quantization changes.

## Measured results

| Configuration | Ordinary generation (tokens/s) | One trim during generation (tokens/s) | RAM observations |
|---|---:|---:|---|
| Current configuration, load mode none, draft 4 | 3.29, 3.13 | 2.94 | Approximately 82-84% |
| mmap, no-host, draft 4 | 3.51, 3.60 | 2.16 | Initial load/first run about 99%; settled run about 72% |
| mmap, no-host, draft 8 | 2.21, 2.14 | 1.82 | Initial load/first run about 98%; settled run about 70-71% |

Each response generated 48 tokens from the identical deterministic prompt. These are short text-generation tests, not end-to-end agent latency or a broad quality evaluation. A separate emergency trim was applied between runs in the mmap/draft4 experiment; it is recorded in qwen-mmap-startup-trim.json. The mmap run after trimming is warm, and cannot establish safe cold startup behavior.

The draft4 mapped model also allocated a CPU_REPACK buffer of approximately 10,018 MiB in addition to a CPU_Mapped buffer of approximately 13,351 MiB. Its extra startup memory makes it unsuitable as a default on this machine without further verification. Increasing speculative draft length to 8 reduced throughput.

The +300% throughput target means about 12.84 tokens/s from the measured baseline average of about 3.21. It was not achieved. The warm mmap/draft4 ordinary generation average was about 3.55 tokens/s (about 11% faster), with a large startup-memory disadvantage.

Working-set trimming does not delete model parameters or improve reasoning. Windows resolves references to trimmed pages from cached RAM or disk backing as necessary. The benchmark records actual overall physical RAM, not only the process working-set number. Page fault counts include both soft and hard faults; they do not prove that every fault accessed disk.

## Matched limited comparison

The approved reduced tests capped every response at 16 tokens and stopped the owned experimental server at 88% physical RAM. With CPU repacking disabled, startup stayed around 81% RAM. Ordinary generation measured 2.89 and 2.29 tokens/s, versus 2.70 and 2.68 for the original configuration in the same 16-token test. The mapped configuration's average was about 4% lower; this small sample does not establish a throughput improvement. During an active trim it measured 2.23 tokens/s, temporarily reached 48.14% RAM and ended that response at 72.42%. The next ordinary response stayed near 72-73% RAM.

The pagefile usage counter increased from about 1,890 MiB to 1,957 MiB in that test. Read-only mapped model pages are backed by the original GGUF file; they need not be copied into pagefile.sys. Windows decides which pages actually use the paging file.

## Review boundary

Automatic approval review initially rejected the next experiment, including the reduced version with a monitor terminating its owned server at 88% RAM. The user explicitly authorized the reduced experiment, which was then run successfully. The original high-memory CPU_REPACK variant was not installed.

## Prepared code

Installed: mmap, no-host, no-repack, the same model/GPU/CPU/context settings, and active cleanup of only the agent's owned native process above 80% physical RAM. At least 120 seconds separate active trims. Background app exclusions remain in place. The previous profile unloaded the model after 30 seconds; the new per-message profile below retains the model and trims pageable RAM instead. The previous settings are saved as qwen-settings-before-active-paging.json in the installed agent folder, and the immediately preceding complete configuration is preserved in backup-request-paging-20261010-084635.

This is a memory-management profile, not a +300% speed improvement. Full weights and context are unchanged. No increase in answer quality was established.

The optional 16-token functional check could not complete a real tool-call JSON object. It executed no tool. The normal agent retains its original 512-token output maximum, and truncated tool calls now produce a clear error before any tool is executed. The normal agent functional verification is recorded separately in qwen-active-agent-verification.json.

## Verified installed agent

The normal functional check used the installed agent's unchanged system instructions, real file tools and ordinary 512-token maximum. It requested only the three-character content of a temporary file and monitored an 88% RAM ceiling. The agent called read_file and returned 391 correctly. The request completed in 21.906 seconds excluding initial model loading; this was one cold prompt/tool loop, not a paired speed comparison. No safety abort occurred.

During that actual agent request, cleanup reduced physical RAM from 82.35% to 40.92% after one second, making about 13,450 MiB more available. RAM subsequently returned to about 72.7% as pages were referenced. After 30 seconds idle the model unloaded and RAM reached about 28.1%. Neither cleanup nor disk-backed storage adds learned knowledge or establishes better answer quality.

## Per-message paging profile, installed and verified

The user explicitly retained Qwen3.8 rather than testing the smaller model. The new profile retains the same weights, GPU layers, context and tool instructions. Before each user message it trims the owned idle model's pageable working set once, skipping a working set already below 512 MiB. The tool loop does not repeat this trim between its internal model calls. A successful preparation also starts the 120-second active-trim cooldown. After a completed turn, another trim can run after 30 seconds of inactivity when physical RAM remains above the 40% target. Full idle unloading is disabled, retaining the GPU allocations and model engine. Closing the agent still terminates its owned model process.

Windows controls reuse and eviction. Read-only model pages retain their GGUF file as backing; private pages can use the existing Windows pagefile. Pages are brought back on demand from cached RAM or their disk backing. No code deletes the pagefile, preloads all evicted pages, or imposes a 40% ceiling while generating. This mechanism does not create more than 32 GiB physical RAM or guarantee 40% overall usage when other programs need memory. The console and JSONL log report actual global physical RAM and global pagefile usage, separately.

In the installed full agent verification, the first preparation reduced actual physical RAM from 85.32% to 35.22%, with a small concurrent background-app trim. The real read_file tool returned the requested text, 391. RAM subsequently reached 78.94% as pages were touched. After the idle trim RAM measured 40.14% at the observation point (40.46% at the trim log point). The same live model process handled the second real file-reading turn and returned 391 again; no model unload occurred. Responses took 29.906 and 15.907 seconds, including the preparation in the first turn, and excluding initial server startup. These are functional observations with different cache states, not a paired throughput comparison. The 88% safety limit was not reached; the monitor's highest sampled value was 85.24%. The pagefile remained 16,384 MiB total, with about 1,431-1,438 MiB used across the entire computer.

Evidence: qwen-request-paging-verification.json; tests verify ownership, idle/busy checks, once-per-turn preparation across tool calls, cleanup on failure, idle grace and active cooldown. The previous model exclusions, background exclusions and native stream tests also pass.

## Idle response comparison

Two repetitions per variant used the same short prompt and 16 output tokens, after 33 seconds idle, with the owned test server stopped if physical RAM reached 88%. Full unload/reload measured mean first-token latency 20.000 seconds and response duration 24.047 seconds, at about 30.2% idle RAM. Retaining the engine and trimming pageable memory measured first-token latency 3.266 seconds and response duration 8.445 seconds, at about 35.6-35.8% idle RAM. The page-only measurements excluded the one-time idle trim and its three-second settling wait; each response was timed only after that preparation. This supports replacing full unload for this user's frequent requests: about 6.1 times faster first token and 2.85 times faster short response after idle in this small test. It does not establish 4 times higher token-generation throughput: generation was 2.64 and 3.21 tokens/s with paging versus 3.60 and 3.83 with full reload. The +300% throughput target remains unachieved. Evidence: qwen-idle-residency-benchmark.json.

## Sources

- https://learn.microsoft.com/en-us/windows/win32/memory/working-set
- https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md
