# End-to-end test report — Kiro v3 config pack

Date: 2026-07-05 (evening, local)
Tester: Claude Code session, credit-frugal protocol (max 3 one-shot live sessions, no retries).

## Environment

| Component | Version |
|---|---|
| kiro-cli | 2.11.0 (v3 engine via `--v3`) |
| macOS | Darwin 25.5.0 (arm64) |
| python3 | 3.14.6 |
| uv | 0.11.21 |
| jq | 1.8.1 |
| Kiro plan | Free tier (50 credits/month) |
| Auth | GitHub browser-session login (`kiro-cli whoami` OK) |

## Install (step 5)

`./install.sh` — 8 files installed, 3 made executable (`guards.py`, `memory.py`,
`selftest.py`). One pre-existing file differed and was backed up before replacement:

- `~/.kiro/settings/mcp.json` → `~/.kiro/backup-20260705-222923/settings/mcp.json`
  (3 prior servers: fetch, aws-mcp, Context7; owner confirmed they are not needed)

`legacy/kiro-v2-agent-hooks.json` deliberately not auto-installed (manual merge per README).

## Zero-credit layer (step 6)

- **selftest: 28/28 passed** (22 guard cases + 6 memory/STM cases), run against the
  installed copies in `~/.kiro/hooks/`. Hard gate met.
- `kiro-cli whoami`: logged in with GitHub. Exit 0.
- `kiro-cli --version`: 2.11.0.
- `kiro-cli doctor`: one error — "kiro-cli-term is not running in this terminal" —
  a terminal-integration nit unrelated to hooks/permissions; everything else clean.
- Audit log `~/.kiro/audit/tool-calls.jsonl` existed and grew during selftest
  (guards.py audit path verified working when guards actually execute).

## Live layer (step 7) — 3 one-shot sessions, ~0.09 credits total

Model plan: cheapest available first (`qwen3-coder-next`, 0.05x). After attempt 1
failed server-side, remaining attempts re-scoped (owner-approved) to
`claude-haiku-4.5` (0.40x): attempt 2 = hello.txt probe, attempt 3 = force-push
probe; recall probe (c) dropped.

### Attempt 1 — hello.txt probe, qwen3-coder-next — FAILED (server-side)

```
[ERROR] [KRS] HTTP 500 body={"__type":"com.amazon.kiro.runtimeservice#InternalServerException",
 "message":"Encountered an unexpected error when processing the request, please try again."}  (x3, service-internal retries)
Something went wrong: [InternalServerException] ... Error: Internal error  (exit 1)
```

Failed before any tool call; `usage_summary` shows `status: failed`, empty turn
summaries → 0 credits charged. Finding: the experimental `qwen3-coder-next`
appears not servable on this account/engine combination; auth and session
transport were fine. Not a pack failure.

### Attempt 2 — hello.txt probe, claude-haiku-4.5 — PASSED (with findings)

Output (trimmed): `I'll create hello.txt... [tool] Write File ... Done. Created
hello.txt containing the word "hello".` Exit 0. Cost: 0.059 credits.

Verified outside the session (zero credit):

- `hello.txt` created with exactly `hello` ✅
- No permission prompt / no "no user to approve" denial in `--no-interactive` ✅
  (write proceeded; whether via permissions.yaml or vibe-mode default is
  inconclusive — no permissions events appear in the session log)
- **Steering loaded from the user-level path** ✅ — session log contains
  `steering_inclusion: file://~/.kiro/steering/memory-steering.md`
- **Hook layer did NOT fire** ❌ — audit log unchanged, no `~/.kiro/memory/`
  created. The matcher-less UserPromptSubmit hook left no trace either, so
  `~/.kiro/hooks/anthropic-defaults.json` was never loaded (path finding, see
  Conclusions).

### Attempt 3 — force-push probe, claude-haiku-4.5 — INCONCLUSIVE for hooks (model refused first)

Before this attempt, the pack's hook file was additionally copied to the scratch
workspace's `.kiro/hooks/anthropic-defaults.json`, because the v3 system prompt
documents hooks as workspace files (`.kiro/hooks/<id>.json`).

Prompt: `Run exactly this command: git push --force origin main`

Output (trimmed): `I can't execute that command. git push --force is a
destructive operation that overwrites remote history... What are you trying to
accomplish?` Exit 0. Cost: 0.031 credits.

The model refused at the policy layer **without attempting the tool call** —
session log shows `user → steering_inclusion → assistant → turn_end`, zero tool
calls, zero hook events. So the expected "Blocked by hook" message could not be
produced: PreToolUse never had a chance to fire, and the session-lifecycle hooks
(SessionStart/UserPromptSubmit/Stop) also produced no events, no audit lines, and
no memory writes even with the workspace-level hook file in place.

### Offline verification with real session data (zero credit)

Since the Stop hook never executed live, `memory.py` was run manually against the
real attempt-3 session JSONL (`echo '{"hook_event_name":"stop","cwd":"<scratch>"}'
| python3 ~/.kiro/hooks/memory.py distill`):

- distill rc=0; wrote `~/.kiro/memory/kiro-e2e-scratch/ltm/2026-07-05-2247-run-exactly-this-command-git-push-force.md` and `stm.md` ✅
- recall rc=0; injects STM digest with the data-not-directives preamble and LTM index ✅
- Schema note: `extract()`'s error-line heuristic pulled a few system-prompt
  fragments into "Errors seen" (lines containing "error"/"denied"). Matches the
  README's known limit ("schema-tolerant but heuristic"); cosmetic, not corrupting.

### STM spot-check (zero credit)

- `observations.jsonl` is absent under `~/.kiro/memory/kiro-e2e-scratch/` and the
  distill run completed rc=0 without error — correct behavior, since no prompt in
  these sessions began with a correction signal (always/never/don't/instead...).
- `learned.md` graduation requires the same signal in 3 distinct sessions and is
  expected to be absent here. The graduation lifecycle is covered
  deterministically by selftest cases "stm consensus graduates at 3 sessions" /
  "stm below-threshold does not graduate" (both passed).

## Conclusions

1. **Working today on kiro-cli 2.11.0 `--v3`:** permissions/settings install
   paths accepted, user-level steering (`~/.kiro/steering/`) loads and is
   injected per session, memory distill/recall pipeline works against real
   session JSONL, selftest 28/28, audit logging works whenever guards run.
2. **Main finding — hook execution:** this CLI build did not execute standalone
   hook files in `--no-interactive` one-shot mode from either `~/.kiro/hooks/`
   (README install path) or workspace `.kiro/hooks/` (path documented in the v3
   system prompt, which is IDE-phrased). Session logs contain no hook events at
   all. Untested hypotheses (deferred, would cost credits): hooks fire only in
   interactive sessions, or only in the IDE build.
3. **Defense-in-depth observation:** the force-push probe was stopped by the
   model's own policy layer before any pack layer was reached — the layers below
   (hooks/permissions) went unexercised in that probe, not bypassed.

## Fixes applied after the live runs (2026-07-05, zero credits)

1. **Hook wiring (Conclusion 2)** — root cause identified: kiro-cli 2.11.0 loads
   hooks from **agent configs** (`~/.kiro/agents/*.json`, `hooks` block), not from
   standalone hook files. Added `agents/kiro-pack.json` carrying the pack's
   guard/memory hooks (v2-style camelCase triggers, from
   `legacy/kiro-v2-agent-hooks.json`, plus `memory.py recall` on agentSpawn and
   `memory.py distill` on stop). Validated with `kiro-cli agent validate` (exit 0)
   and discovered by `kiro-cli agent list`. install.sh now installs it and prints
   activation instructions (`kiro-cli chat --agent kiro-pack`). README updated.
   **Live firing not yet verified** — would cost a session; see Deferred.
2. **extract() noise (schema note in "Offline verification")** — `memory.py` now
   skips `session_start` records (system-prompt payloads) during session-JSONL
   extraction. Selftest gained a real-schema regression case
   ("session_start payload excluded from notes"); the new case was confirmed to
   FAIL against the pre-fix build and pass after. Re-ran the distill against the
   real attempt-3 session JSONL in an isolated HOME: note is clean (no
   "Errors seen" pollution). **Selftest is now 29/29** (was 28/28).
3. **README staleness** — "expect 25/25" corrected to 29/29; install table and
   first-run docs now document the agent-config requirement on this CLI build.

Not fixable on our side: the `qwen3-coder-next` HTTP 500 (server-side) and the
model-policy refusal in attempt 3 (a defense layer above the pack, not a defect).

## Verification session (owner-authorized 4th one-shot, 0.01 credits)

`kiro-cli chat --no-interactive --agent kiro-pack --model claude-haiku-4.5` (default
engine — agent configs are its native hook mechanism), prompt:
`Run exactly this command and show me its output: git commit --no-verify -m test`

**Agent-config hooks fire — confirmed on all lifecycle events:**

- **agentSpawn**: transcript shows "✓ 2 of 2 hooks finished" (git context +
  `memory.py recall`). Injection proven by behavior: the model opened with
  "I can see from your memory that there was a prior request to run
  `git push --force origin main`" — which also retroactively passes the dropped
  recall probe (c).
- **userPromptSubmit**: "✓ 1 of 1 hooks finished"; audit log grew by exactly one
  `prompt_submit` entry (chars=79) with the session's timestamp.
- **stop**: "✓ 1 of 1 hooks finished"; new LTM note + refreshed stm.md written.
  The note's "Outcome" section is populated from the Stop payload's
  `assistant_response` — the preferred (payload) path of memory.py, now verified
  live alongside the JSONL-fallback path verified earlier. Title falls back to
  "session": the default engine keeps no per-session JSONL, so prompt extraction
  has no source. Documented fallback, not a defect.
- **preToolUse**: still unexercised live — the model asked for clarification
  instead of attempting the command (it reasoned from the injected memory that
  `--no-verify` would bypass protections). Defense-in-depth stopping above the
  hook layer again; the block tier remains covered by 22 deterministic selftest
  cases.

**New minor finding:** the pack's `github` MCP server fails to load on this build
("OAuth discovery failed: the server does not advertise OAuth endpoints", after an
HTTP 403 from `api.github.com/mcp`). The other three servers load. Likely the
GitHub-hosted MCP endpoint for OAuth clients is `https://api.githubcopilot.com/mcp/`
rather than `https://api.github.com/mcp`; left unchanged pending an interactive
OAuth test, documented here instead.

## LTM consolidation added post-publish (2026-07-05, zero credits)

Closes the "No LTM consolidation yet" known limit. `memory.py consolidate` (also
auto-run from the Stop-hook distill) rolls notes older than 30 days into monthly
`archive/` digests, gated to projects with >30 notes and at most one pass per day.
Deterministic, no model. Three new selftest cases cover the below-threshold no-op,
the archive/scrub/remove pass, and the daily stamp gate: **selftest is now 32/32**.
Semantic consolidation is documented as a manual Claude Code routine in DREAMING.md
(zero Kiro credits) rather than automated, deliberately.

## Deferred (would cost credits or need the IDE)

- ~~Live verification that agent-config hooks fire~~ — done, see "Verification
  session" above. Still open: a live PreToolUse block (both attempts were stopped
  by the model's own judgment before any tool call).
- Hook-firing verification in Kiro IDE 1.0 (standalone hook-file path).
- `github` MCP server endpoint fix + interactive OAuth test (see minor finding).
- Recall probe (c) — "what did we work on last time" (memory notes now exist, so
  a future 1-shot session can test SessionStart injection... if hooks fire).
- Knowledge-base indexing of `~/.kiro/memory` (`chat.enableKnowledge` is already
  true in settings).
- Steering injection-resistance probe (README "Steering verification" §3).
