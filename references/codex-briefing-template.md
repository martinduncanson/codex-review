# Codex briefing template — full version with rationale

Read this once per session before invoking the codex-review skill. It explains why each section of the brief earns better reviews, with good vs. weak examples.

## The template

```markdown
@codex please review.

## Goal
<one sentence — the user-visible problem this change solves>

## Approach
- <design choice + why this over the obvious alternative>
- <any non-trivial decision worth flagging>
- <library/pattern/architecture choice that's not self-evident>

## Scope of this commit
- `path/to/file1.py` — <one-line summary>
- `path/to/file2.ts` — <one-line summary>
- (etc.)

## Concerns / things I'm unsure about  (REQUIRED — 3 to 5 bullets)
- <specific concern 1, with file:line>
- <specific concern 2, with file:line>
- <specific concern 3>
- <(4th if warranted)>
- <(5th if warranted)>

## Out of scope
<what this PR explicitly does NOT touch — prevents drive-by suggestions>

## Test coverage
<what's tested, what isn't, and whether new tests were added>
```

**The Concerns count is load-bearing, not stylistic.** 3-5 bullets is the calibration band. Fewer than 3 means you haven't audited yourself enough — go back and find them. More than 5 means your design intent is too foggy to ship; defer to a design pass before the review. The point of the count isn't volume — it's forcing the implementer to surface real uncertainties rather than skip the section.

## Why each section earns its keep

### Goal — sets the evaluation criteria

Without it, Codex evaluates the diff against an implicit "is this generally good code?" standard, which produces generic reviews. With a Goal, it evaluates against "does this solve the stated problem correctly?" which is the question you actually want answered.

**Weak:** *"Refactoring the auth module."*
**Strong:** *"Stop the 500 error users see when they paste a malformed JWT into the cookie editor — they should land on /login instead."*

### Approach — explains intent so review focuses on execution

Tells Codex what design decisions are settled. Without this, half the review tokens get spent questioning choices you've already deliberately made. With it, the review focuses on whether the implementation matches the intent.

**Weak:** *"Added middleware."*
**Strong:** *"Treating decode-failure identically to no-token-present (single redirect path) instead of throwing a custom AuthError, because the downstream error handler can't distinguish them anyway and a custom class would just add surface area."*

### Scope of this commit — orients the reviewer

Useful for diffs over ~5 files. Codex builds a mental model of the change faster when it knows up front what each file is doing. Skip for trivial diffs.

### Concerns — the highest-leverage section, and the one that makes round-1-clean possible

This is the section most agents skip, and it's the one that actually earns the review. Tell Codex *what you specifically want a second pair of eyes on*. The review will be 3-5x more substantive — and Codex's response will shift from "find bugs" mode to "sanity-check the implementer's stated uncertainties" mode. Empirically, briefs with a substantive Concerns section often return round-1-clean, because each named uncertainty either gets confirmed or pre-empts a finding Codex would otherwise have spent a round discovering.

**Required count: 3 to 5 bullets.** This is a hard floor and ceiling — not arbitrary, calibration:

- **Fewer than 3** = you haven't audited yourself enough. The implementer who can't name 3 places they're unsure has either over-confidence or under-attention. Sit with the diff for another five minutes and find them.
- **More than 5** = your design intent is too foggy. Five concerns on one PR means the PR is doing too many uncertain things at once. Defer the review and do a design pass first; come back when the unknowns are bounded.
- **Exactly the right band: 3-5** = you've genuinely audited and your concerns are real, but the diff has coherent intent.

**What makes a concern substantive vs. padding:**

| Substantive (earns review) | Padding (skip) |
|---|---|
| Specific file:line, names a tradeoff, asks a decidable question | Vague worry without a path |
| "I picked X over Y because Z. Was that right?" | "Hope this is OK" |
| Names the alternative that was non-obvious to dismiss | Restates that the code is hard |
| Flags an invariant the reviewer might not know is load-bearing | Generic test-coverage anxiety |

**Weak (no concerns section):**
> *(generic review of the whole diff)*

**Weak (vague concerns):**
> ## Concerns
> - Hope the error handling is right
> - Wasn't sure about the test names

**Strong (3 substantive concerns):**
> ## Concerns
> - `auth/middleware.py:47` — am I handling the race when two requests arrive with the same expired token? The cache lookup is non-atomic; I considered taking a lock but decided the window is so short it's not worth the contention. Was that right?
> - The `verify_or_none` pattern is new in this codebase. Existing verifiers throw; this one returns None. Is the asymmetry the right call, or should it conform?
> - Test coverage for the redirect loop is thin — I have a happy-path test but not the "redirected user gets the same bad cookie back" case. Should I block this PR on adding it, or land separately?

Each bullet (a) cites a specific place or decision, (b) names what the implementer considered and rejected, (c) asks a question Codex can answer with a yes/no or a redirect. That's the shape that makes concerns-enumeration upstream of finding-discovery — Codex either ratifies the implementer's call or surfaces the case they didn't think of.

The meta-pattern: when the implementer can name 3-5 design choices they're uncertain about, Codex's value shifts from *finder* to *checker*. Most rounds spent in the codex-review loop are findings the implementer would have caught in self-review. The Concerns section makes that self-review explicit, so Codex doesn't have to redo it.

### Out of scope — prevents drive-by noise

Without this, Codex sees adjacent code and suggests changes to it. With it, you get a focused review.

**Strong examples:**
- *"Out of scope: rate limiting (issue #501 covers that). Don't suggest changes there."*
- *"Out of scope: the legacy `LegacyAuthProvider` class — it's scheduled for deletion in a follow-up PR."*
- *"Out of scope: test naming conventions across the file. I matched the existing style intentionally."*

### Test coverage — pre-empts the most predictable suggestion

Codex defaults to "you should add tests for this." If you say where the tests are or why they're absent, the review skips that boilerplate and gets to substance.

**Strong:**
> ## Test coverage
> - `tests/auth/test_middleware.py::test_decode_fail_redirects` covers the happy path.
> - Race-condition case is *not* covered — open to suggestions on how to test it deterministically.
> - No integration test added because this path is exercised by the existing `e2e/login.spec.ts`.

## Re-review brief (rounds 2+)

For iteration rounds, the brief is shorter — Codex has the previous thread:

```markdown
@codex re-review.

## Addressed since last review
- `auth/middleware.py:47` — added a lock around the cache lookup; race is no longer possible.
- Added the missing test case (`test_redirect_loop_with_stale_cookie`).

## Skipped (with reasoning)
- The "consider extracting `_decode_or_none` into utils" suggestion — keeping it inline because it's only used in this one place and pulling it out would require importing config that the utils module doesn't currently depend on. Happy to revisit if it gets a second use.

## New concerns from this round
- `auth/middleware.py:53` — the lock timeout of 5s is a guess; not sure what the right value is.
```

Always state what was *not* changed and why, even if just one line. Otherwise Codex re-raises the same suggestion.

## Anti-patterns — what makes a review useless

| Anti-pattern | Why it fails |
|---|---|
| `@codex review` (no context at all) | Generic, surface-level review |
| Long, narrative prose paragraph | Codex skims; structure beats prose |
| "Make sure this is correct" | Vague — what does correct mean? |
| Posting the brief as the PR body, never as a comment | Codex polls comments primarily |
| Inventing concerns to fill the section | Pads the brief without earning anything |
| Skipping Out-of-scope on a large diff | Drive-by suggestions overwhelm real findings |
