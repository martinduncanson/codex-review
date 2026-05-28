---
name: codex-review
description: Use whenever code is written, refactored, or fixed in any repository — at logical checkpoints (feature/fix complete, ~300 LOC since last review, end of working session, before opening or merging a PR). Commits the work, pushes, opens or updates a PR, posts a structured review request tagging @codex (the GitHub-integrated Codex bot), polls for the reply, and iterates with the agent on findings until the review is clean. Trigger on phrases like "I've finished implementing X", "let's commit this", "ready for review", "before I merge", or after writing/editing source files (.py/.ts/.js/.go/.rs/.rb/.java/.php/.cs etc). Skip for pure docs (.md only), throwaway scratch, or repos without the Codex GitHub app installed.
---

# Codex Review

## Overview

Every code-bearing change passes through Codex via GitHub before merge. The skill bundles the mechanics so the agent never has to improvise, and so the review request always carries enough context for Codex to be useful. The discipline is the point — undisciplined check-ins ("eh, looks fine") accumulate into the kind of drift that takes a week to unpick later.

**The non-obvious part most agents get wrong:** Codex's review quality scales with the *briefing*, not with the diff. A 200-line diff with three sentences of context produces a generic review. The same diff with a clear `Goal / Approach / Concerns / Out-of-scope` brief produces a substantive review that catches real bugs.

## When to invoke

Invoke at any of these checkpoints — whichever comes first:

- A logical unit of work is complete (feature implemented, bug fixed, refactor finished)
- ~300 lines of code changed since the last review
- End of a working session, before stopping
- Before opening a PR for human merge
- After Codex's previous review came back clean and a new round of changes is ready

**Do not invoke for:**

- Pure docs (`.md`, `.rst`, `.txt`) or pure config (`.yml`, `.toml`, `.json`) with no code change
- Throwaway scratch work the user has explicitly marked as experimental
- Repositories where the Codex GitHub app is not installed (the tag is a no-op)

## Prerequisites

Before invoking the skill the first time in a new repo, confirm:

1. `gh auth status` reports authenticated and has access to the repo
2. The Codex GitHub app is installed on the repo (visible at `https://github.com/<owner>/<repo>/settings/installations`)
3. There is a remote (`git remote -v` returns at least one)

If any of these fail, tell the user what's missing and stop — don't fake a review.

## Workflow

```
 1. STAGE              Inspect the working tree. Decide what belongs in this review unit.
 2. COMMIT             Conventional-commit message stating WHAT changed and WHY.
 3. PRE-REVIEW         Spawn a reviewer subagent on the diff with no other context;
                       triage findings; fix locally. Skip only for tiny mechanical
                       or pure-docs changes — see §3 for the precise rule.
 4. PUSH               Feature branch (never main/master directly).
 5. PR                 Open new, or update existing for the branch.
 6. BRIEF              Post a structured @codex comment (see template — 3-5 Concerns required).
 7. WAIT               Background `scripts/wait-for-codex.py`; agent notified on exit.
 8. TRIAGE             Parse findings. Decide accept / refactor / push back per item.
 9. ITERATE            Apply changes -> commit -> push -> re-tag @codex -> re-wait.
10. CLOSE              Once the review pass is clean, mark complete in conversation.
```

**Why PRE-REVIEW exists.** Codex catches bugs the implementer didn't catch in self-review. A reviewer subagent run on the diff *before* pushing catches ~50% of what Codex would catch, locally, at ~30-60 sec wall-clock cost — saving one full Codex round (5-15 min + agent context). Combined with a substantive Concerns section (BRIEF step 6 references the template requirement), round-1-clean Codex reviews become the norm rather than the exception. The diff Codex sees is the diff that survived a self-review pass; Codex's job shifts from "find bugs" to "sanity-check the implementer's stated uncertainties".

### 1. STAGE

```bash
git status -sb
git diff --stat
git diff   # the actual content if not already obvious from the session
```

Group changes into a coherent review unit. If the working tree mixes a feature change and an unrelated drive-by fix, split them into two commits — Codex reviews much better when each commit has one clear intent. If the user has explicitly said "ship it all together," follow that instruction.

### 2. COMMIT

Use a conventional-commit message. Lead the body with **why**, not what — the diff already shows what.

```
feat(auth): redirect to /login when JWT decode fails

Previously a malformed token threw a 500 because the middleware assumed
verify() never returned null. We now treat decode failure the same as
"no token present" so the user gets the login page instead of a stack
trace. Bug surfaced in #482.
```

Stage specific files (not `git add -A`) to avoid sweeping in `.env`, build artifacts, or unrelated edits.

### 3. PRE-REVIEW — spawn a reviewer subagent on the diff before pushing

**The cheapest upstream layer.** Before pushing, spawn a code-reviewer subagent against the just-committed diff with no other context. The subagent's job is to find bugs, missed edge cases, and inconsistencies that the implementer (you) didn't catch through confirmation bias on their own work. Fix what it surfaces. THEN push.

**Why this saves Codex rounds.** Codex catches roughly two categories of finding: (a) bugs the implementer didn't see, and (b) intentional design choices Codex questions. A pre-push self-review eats most of (a) before Codex ever runs. Combined with concerns-enumeration (step 6 BRIEF) eating most of (b), round-1-clean Codex reviews become the default.

**Cost vs. value.** Subagent invocation: ~30-60 sec wall-clock + modest token cost. Saved: typically one Codex round = 5-15 min wall-clock + tokens + agent context retained across the wait + cognitive overhead of triage. Net win at any non-trivial PR size.

**How to invoke — heuristic specialist dispatch.** Always run the generic reviewer; ALSO dispatch specialists matching the diff shape. Specialists catch failure-class bugs the generic reviewer averages over.

| Diff shape | Specialist to ALSO dispatch | Why |
|---|---|---|
| Always | `pr-review-toolkit:code-reviewer` (or `coderabbit:code-review`) | General quality / project-convention check; baseline |
| Adds/modifies try/except/catch blocks, error returns, fallback branches | `pr-review-toolkit:silent-failure-hunter` | Silent-failure patterns require dedicated lens; generic reviewer often misses fail-open shapes (see install-gate skip-and-error memory) |
| Introduces new types/dataclasses/interfaces/struct definitions | `pr-review-toolkit:type-design-analyzer` | Type design quality is invariant-shaped; generic reviewer focuses on bug-shaped findings |
| Adds tests or modifies test files | `pr-review-toolkit:pr-test-analyzer` | Test coverage gaps and behavioural-vs-implementation testing distinctions need a specialist |
| Adds substantial new comments/docstrings (>~10 lines of new commentary) | `pr-review-toolkit:comment-analyzer` | Comment rot and accuracy-vs-code drift are their own class |

**Dispatch in parallel when multiple specialists match** — they're independent passes against the same diff. The synthesis step (below) reconciles findings before you act.

**Fallback when specialists are unavailable.** Some host environments expose only `coderabbit:code-review` and not `pr-review-toolkit:*`. If a matched specialist isn't reachable, fall back to the generic reviewer alone and **note the skipped specialist in the synthesis step / PR description** — so the operator knows the specialist lens wasn't applied. Don't silently downgrade; surface the gap. Never block on unreachable specialists.

**The prompt to each subagent must be:**

```
You have no other context for this change. Review this diff for:
  - bugs
  - security issues
  - missed edge cases
  - inconsistencies with the apparent surrounding patterns
  - missing tests for new behavior

Do not flag stylistic preferences. Do not propose refactors that are out of
scope for the diff. Cite each finding with file:line.

Here is the diff:
<paste the output of `git diff <base>...HEAD`>
```

Specialists may interpret their own remit through the prompt — `silent-failure-hunter` will naturally focus on error-handling shapes regardless of the generic prompt; that's the intent.

**Synthesis step (whenever any specialist fires alongside the baseline reviewer).** After all dispatched reviewers return, read their reports, dedupe overlapping findings (the same line flagged by both `code-reviewer` and `silent-failure-hunter`), rank by severity, then triage per the table below. The baseline generic reviewer ALWAYS runs, so synthesis triggers whenever even one specialist also fires — duplicates between baseline + specialist are the most common case, not the multi-specialist scenario. Don't act on each report in isolation — that's how operator context gets shredded by 5 parallel reviews.

**Triage the findings.**

| Class | Action |
|---|---|
| **Real bug** | Fix locally before pushing. |
| **Real edge case missed** | Fix locally; add a test if applicable. |
| **Subagent misunderstood the intent** | Note it — it's a sign your Concerns bullets need to clarify intent. |
| **Stylistic preference (you asked it not to flag these but it did)** | Ignore. |
| **"Add a test for X"** where X is out-of-scope | Move to a follow-up issue, don't bloat this PR. |

**When to skip PRE-REVIEW.** The fixed cost of one subagent invocation dominates for tiny diffs. Skip for:

- Pure docs (`.md`, `.rst`, `.txt`) or pure config (`.yml`, `.toml`, `.json`) changes
- ≤50 LOC **and** the change is mechanical (rename, single-line fix, type annotation tightening)
- Throwaway scratch work explicitly marked experimental

**Never-skip carve-out.** Even if the diff matches a skip criterion above, do NOT skip PRE-REVIEW when the change touches **auth, serialization, data storage, or anything with security or correctness invariants that can fail silently**. Those categories punish missed edge cases out of proportion to their LOC count; the subagent's 30-60 sec is cheap insurance.

**Anti-patterns:**

- Skipping PRE-REVIEW because "Codex will catch it" — that's the whole point of the cost/value math: catching it before Codex catches it saves the entire Codex round, not the time-to-fix-the-finding.
- Asking the subagent to evaluate intent ("is this the right approach?") — that's what Codex with concerns-enumeration is for. PRE-REVIEW is for *bugs you didn't see in your own diff*, not for design ratification.
- Dispatching specialists that don't match the diff shape (e.g. running `type-design-analyzer` on a pure logic fix). The heuristic dispatch matrix exists to avoid this — only fire specialists whose remit matches the diff.
- Skipping the synthesis step whenever any specialist fires alongside the baseline reviewer. Baseline + 1 specialist is the most common case — duplicates between them are routine. Acting on each report in isolation produces duplicate work and shreds operator context. Always dedupe and rank first.
- Dispatching every specialist on every diff "for completeness". The matrix is a filter, not a checklist. Five parallel reviews on a small diff is the anti-pattern this replaced.

### 4. PUSH

If the branch is `main` or `master`, create a feature branch first — never push direct review work to a default branch.

```bash
# If on main/master:
git switch -c <type>/<short-slug>   # e.g. fix/jwt-decode-redirect

git push -u origin HEAD
```

### 5. PR — open or update

Detect whether a PR already exists for the branch:

```bash
gh pr view --json number,url,state -q '.number' 2>/dev/null
```

If none exists, open one with a description that mirrors the brief structure (Codex will read the PR body too):

```bash
gh pr create --fill-first --body-file <(cat <<'EOF'
## Goal
<one sentence>

## Approach
<2-4 bullets>

## Out of scope
<what this PR explicitly does NOT touch>
EOF
)
```

If a PR exists, the new commits are already attached — proceed to BRIEF.

### 6. BRIEF — tag @codex with structured context

The template lives at `references/codex-briefing-template.md` — read it now if this is the first invocation. The template explains *why* each section earns better reviews.

Post the brief as a fresh PR comment (not a review comment, not the PR body — comments are what Codex polls):

```bash
gh pr comment <PR_NUM> --body-file <(cat <<'EOF'
@codex please review.

## Goal
<one sentence — user-visible problem this solves>

## Approach
- <design choice + why this over the obvious alternative>
- <any non-trivial decision worth flagging>

## Scope of this commit
- `path/to/file1.py` — <one-line summary>
- `path/to/file2.ts` — <one-line summary>

## Concerns / things I'm unsure about  (REQUIRED — 3 to 5 bullets)
- <specific concern 1, with file:line>
- <specific concern 2, with file:line>
- <specific concern 3>
- <(4th if warranted)>
- <(5th if warranted)>

## Out of scope
<what this PR explicitly does NOT touch>
EOF
)
```

**Why each section earns its keep:** see the briefing template for the full reasoning. In short: Goal sets evaluation criteria; Approach explains design intent so Codex doesn't waste tokens questioning settled decisions; Concerns directs the review toward the parts you actually want a second pair of eyes on; Out-of-scope prevents Codex from raising "you should also fix X" noise.

### 7. WAIT

Codex usually replies in 5-10 minutes, occasionally faster, occasionally up to 20-30 min under load. Do NOT use an in-process bash poll on `gh pr view --json comments` — that approach has two failure modes confirmed in the field:

1. **Wrong surface.** Codex posts as a **pull-request review** by `chatgpt-codex-connector[bot]`, not as an issue comment. `gh pr view --json comments` only returns issue comments, so the bash loop never sees Codex's reply and times out at 5 minutes even though Codex answered at minute 7.
2. **In-process polling burns context** and dies when the agent session ends. Spawn the wait as a background process and let it notify the agent on exit instead.

Use `scripts/wait-for-codex.py` — it probes three surfaces at once (PR reviews, issue comments, GitHub notifications inbox) and matches any author login containing `codex` (case-insensitive). It also re-pings @codex at a configurable interval if Codex has gone silent, so a single transient miss doesn't strand the review.

```bash
# Record the briefing timestamp first so we don't match an older Codex reply.
BRIEFING_TS="$(gh api repos/<owner>/<repo>/issues/<PR>/comments \
  --jq '.[-1].created_at')"

python "$HOME/.claude/skills/codex-review/scripts/wait-for-codex.py" \
  --pr <PR> \
  --repo <owner>/<repo> \
  --since "$BRIEFING_TS"
```

Run this **in the background** (e.g. via your environment's background-process facility — `run_in_background=true` for the Bash tool in Claude Code) so the agent is notified on exit instead of blocking the conversation. The script writes JSON to stdout on success with `kind`, `author`, `body`, `ts`, `url`. Exit codes:

| Exit | Meaning | Action |
|---|---|---|
| 0 | Codex posted a review or comment | Read the body, TRIAGE |
| 2 | Timeout (default 90min) reached with no Codex reply | Surface to user; check that the Codex GitHub app is actually installed on the repo; consider whether usage is exhausted and rescheduling is right |
| 3 | Codex reacted 👍 (no findings) | This is Codex's "looks good" signal — proceed to CLOSE |

**Why the three-surface probe matters.** GitHub doesn't have a single feed that captures every shape of Codex output. The reviews endpoint is where the actual feedback lands; the comments endpoint catches the rare cases where Codex posts an issue comment instead (e.g. for very short responses); the notifications inbox is a useful liveness signal (it confirms *something* happened on the PR even if you haven't found it on the content endpoints yet, which can speed up the next probe). The wait script unifies all three; never go back to single-surface polling.

**Why we don't sleep in-process.** The skill used to recommend a 5-minute cap on in-process polling, which turned out to be far too short — Codex frequently takes 7-15 minutes, and the agent would time out, abandon the wait, and either move on (missing real findings) or sit silently for hours (operator confusion). Background process + exit notification is the right pattern: no context burn while waiting, and the agent picks up the result the moment Codex actually replies.

**Tuning knobs:**
- `--timeout-seconds` (default 5400 = 90min) — total ceiling. Bump up if you know Codex is rate-limited.
- `--poll-interval-seconds` (default 30) — between probes. Don't go below 30s; Codex doesn't reply faster than that.
- `--reping-after-seconds` (default 1800 = 30min) — re-ping `@codex` after this much silence. Set to 0 to disable.
- `--max-repings` (default 2) — re-ping budget. Two re-pings + the original = three total nudges across 90min.

**Failure mode: usage exhausted.** If Codex never replies and you've burned the re-ping budget, the most likely cause is Codex's own quota/availability, not your PR. Surface this to the user with the PR URL and the exit code; do not silently retry. The operator may want to wait 24h and re-tag manually.

**Quota-limit signal vs silence.** Codex sometimes replies with a quota-limit *comment* by `chatgpt-codex-connector[bot]` (body contains `usage limits` and a link to the Codex usage dashboard) instead of going silent. `wait-for-codex.py` returns exit 0 with that comment as the matched body — it looks like a successful review at the script level but it isn't one. **Always check the matched body for the "usage limit" string before treating exit 0 as a clean review.** When you see the quota signal: skip to the Gemini fallback below; do not iterate against the quota-limit comment.

### 7a. Gemini Code Assist fallback

**Why this exists.** Codex's GitHub bot is gated by a separate ChatGPT-side quota that can exhaust without warning. Google's Gemini Code Assist GitHub app (`gemini-code-assist[bot]`) auto-fires on every PR in repos where it's installed — no mention or tag required, the review just appears within minutes of the PR opening. Confirmed working on `martinduncanson/agenticq` PR #16 / #17 (2026-05-28). Catches the same shape of findings as Codex: missing security gates, dead code, abort-signal correctness, test-state realism.

**When to invoke the fallback.** Either:
- Codex replied with the `usage limit` quota comment described above, or
- `wait-for-codex.py` exits 2 (timeout) after re-pings exhausted AND you have evidence the Codex bot is healthy on other PRs in the same window (otherwise the silence is a transient probe miss, not quota).

**How to check for a Gemini review.** Gemini posts as a PR review (not a comment), so the gh API path is `pulls/<n>/reviews` with `author.login == "gemini-code-assist"`:

```bash
gh api repos/<owner>/<repo>/pulls/<PR>/reviews \
  --jq '.[] | select(.user.login == "gemini-code-assist[bot]")
              | {id, state, submitted_at, body}'
```

For inline line-level comments (the actionable findings live here, not in the summary body):

```bash
gh api repos/<owner>/<repo>/pulls/<PR>/comments \
  --jq '.[] | select(.user.login == "gemini-code-assist[bot]")
              | {path, line, body}'
```

**How to verify Gemini is installed before relying on it.** Repos without the app installed will return zero reviews from `gemini-code-assist[bot]`. Confirm at `https://github.com/<owner>/<repo>/settings/installations` or by checking whether any prior PR has a `gemini-code-assist[bot]` review. If the app isn't installed and Codex is exhausted, surface to the operator — do not fake a review pass.

**Triage Gemini findings exactly like Codex.** The TRIAGE table at §8 applies unchanged. The severity badges Gemini emits (`security-high`, `high`, `medium`, `low`) are useful first-pass sorting hints but don't override your own classification — Gemini sometimes flags `medium` for dead code that's genuinely harmless, and occasionally rates real security bypasses as `medium` rather than `high`. Read the body.

**Skill update queued (2026-05-28).** `wait-for-codex.py` does not yet match `gemini-code-assist` author by default; a follow-up will rename/extend it so the bot dispatch is automatic instead of operator-driven. Until then, perform the Gemini check manually whenever the Codex signal is quota-limited or silent-with-evidence.

### 8. TRIAGE

Read Codex's reply carefully. For each finding, classify into:

| Class | Action |
|---|---|
| **Real bug** | Fix it. No debate. |
| **Real improvement** | Fix it unless it's clearly out-of-scope for this PR — in which case file an issue and reference it in the next brief. |
| **Stylistic preference** | Apply if it aligns with the project; push back politely if it doesn't. Codex isn't always right about local conventions. |
| **Misunderstanding** | Reply in-thread explaining the actual constraint. Don't blindly "fix" something that wasn't broken. |
| **False positive** | Reply briefly explaining why, so the next round doesn't repeat the suggestion. |

Don't accept findings just to make Codex stop. If a suggestion is wrong, say so — with reasoning. The point is correct code, not Codex-pleasing code.

### 9. ITERATE

Apply accepted fixes:

```bash
# make changes, then:
git add -p
git commit -m "fix(<scope>): <one-line — what changed and why>"
git push
gh pr comment <PR_NUM> --body "@codex re-review. Addressed: <bulleted summary of what changed since last review>. Skipped: <briefly note anything intentionally not changed and why>."
```

Re-wait using the same `wait-for-codex.py` script, with `--since` set to **the timestamp of your re-ping comment** (not the original briefing). This way the script only matches Codex replies posted after your latest comment, not the previous-round review:

```bash
REPING_TS="$(gh api repos/<owner>/<repo>/issues/<PR>/comments \
  --jq '.[-1].created_at')"

python "$HOME/.claude/skills/codex-review/scripts/wait-for-codex.py" \
  --pr <PR> --repo <owner>/<repo> --since "$REPING_TS"
```

Iterate until either:
- Codex's reply contains no actionable findings (the standard "looks good" / "no issues" / 👍-reaction signal), or
- The user explicitly tells you to stop iterating

**Loop budget:** if you're on round 4+, something is wrong — pause and ask the user. Either the change is too large for review (split it), the brief is missing context Codex keeps re-flagging, or there's a genuine disagreement that needs human judgment.

### 10. CLOSE

Tell the user the review is clean and what was changed across rounds. Do not auto-merge — merging is a human decision. Leave the PR open and ready.

## Briefing template

The full template with rationale lives at `references/codex-briefing-template.md`. Read it the first time you use this skill in a session. It explains the why behind each section and shows good vs. weak examples.

## Common mistakes

| Mistake | Why it's bad | Do this instead |
|---|---|---|
| Tagging `@codex` with just "please review" | No context = generic review = no real value | Use the structured brief; concerns section is the highest-leverage part |
| Bundling unrelated changes in one PR | Codex's review surface explodes; findings get muddled | One coherent unit per review; split if needed |
| Accepting every finding without thought | Drift toward Codex-pleasing rather than correct code | Triage first; push back on false positives |
| Posting brief as PR description, then never commenting | Codex polls comments, not always the body | Comment is the canonical signal |
| Skipping the brief on the second round | Codex loses thread context | Always summarise what changed and why on re-review |
| Re-tagging after every tiny commit | Wastes review cycles | Batch commits into a logical unit, then re-tag once |
| Polling `gh pr view --json comments` for a Codex reply | Codex posts as a **review** (`chatgpt-codex-connector[bot]`), not a comment — your loop never sees the reply | Use `scripts/wait-for-codex.py` which probes reviews + comments + notifications |
| Capping wait at 5 minutes | Codex frequently takes 7-15 min, longer under load — early timeout abandons real reviews | Use the wait script's 90-min default; the operator can override |
| Polling in-process with bash sleep loops | Burns agent context; dies if session ends | Background the wait script; agent gets notified on exit |
| Skipping PRE-REVIEW because "Codex will catch it" | Defeats the point — you wanted to save the entire Codex round, not just the time-to-fix | Run a reviewer subagent on the diff before pushing; ~30-60s cost vs. one Codex round saved |
| Sub-3 bullets in Concerns section | Codex defaults to find-bugs mode and round-count rises | Sit with the diff another five minutes; find three real uncertainties to surface |
| >5 bullets in Concerns section | Design intent too foggy; review will fragment across too many uncertainties | Defer the review and do a design pass first; come back when unknowns are bounded |

## Red flags — stop and reconsider

- About to push to `main` or `master` directly → branch first
- Skipped PRE-REVIEW for a diff >50 LOC or anything touching auth/data/serialization → run the reviewer subagent before pushing
- Brief Concerns section has fewer than 3 bullets, or "I'm not sure if this is right" without a file:line → you haven't audited yourself enough
- Brief Concerns section has more than 5 bullets → design intent too foggy; defer the review and do a design pass
- Diff is 1000+ lines → too large for one review; split
- 4+ iteration rounds on the same PR → escalate to user
- Codex keeps suggesting the same fix you've explained twice → fix the explanation in the next brief, or accept and move on

## Why this skill exists (the meta-point)

Code review is not bureaucracy. Every untouched bug compounds; every review-shaped conversation surfaces an assumption that would otherwise have ossified. Codex is fast, cheap, available, and operating-context-aware in a way no human reviewer can match for routine work. The cost of consulting it is seconds; the cost of not consulting it is the bugs that ship. Use it.
