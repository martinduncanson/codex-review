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

## Concerns / things I'm unsure about
- <specific concern 1, ideally with file:line>
- <specific concern 2>

## Out of scope
<what this PR explicitly does NOT touch — prevents drive-by suggestions>

## Test coverage
<what's tested, what isn't, and whether new tests were added>
```

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

### Concerns — the highest-leverage section

This is the section most agents skip and it's the one that actually earns the review. Tell Codex *what you specifically want a second pair of eyes on*. The review will be 3-5x more substantive.

**Weak (no concerns section):**
> *(generic review of the whole diff)*

**Strong:**
> ## Concerns
> - `auth/middleware.py:47` — am I handling the race when two requests arrive with the same expired token? The cache lookup is non-atomic.
> - The `verify_or_none` pattern is new in this codebase. Is this consistent with how we handle other null-returning verifiers?
> - Test coverage for the redirect loop is thin — I have a happy-path test but not the "redirected user gets the same bad cookie back" case.

This directs Codex to the parts where you genuinely don't know if you've got it right. Codex will engage with those specifics rather than producing surface-level commentary.

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
