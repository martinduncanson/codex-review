#!/usr/bin/env python3
"""Wait for a Codex reply on a GitHub PR, polling three signals at once.

Why this exists
---------------
The original codex-review skill polled only `gh pr view --json comments` and
matched `codex` in the comment author login. Codex actually posts its review
as a **pull request review** by `chatgpt-codex-connector[bot]`, which lives at
`repos/{owner}/{repo}/pulls/{pr}/reviews` — invisible to the comments endpoint.
Result: agents sat waiting for hours on a PR Codex had already reviewed
within 5–10 minutes.

This script probes three surfaces and returns on the first hit:
  1. PR reviews        (where Codex actually posts)
  2. Issue comments    (where @codex acknowledgements sometimes land)
  3. User notifications (the same feed GitHub's web UI shows)

Usage
-----
    python wait-for-codex.py --pr 1 --repo owner/repo --since 2026-05-13T07:54:17Z

Exits
-----
  0   Codex replied. Reply body written to stdout (JSON: {kind, body, author, ts, url}).
  1   Usage error (missing repo, gh not authed, etc.)
  2   Timeout reached without a Codex reply.
  3   Detected Codex marked the PR with a 👍 reaction only (no issues found —
      this is Codex's "looks good" signal). Reply body is the reaction record.

Designed to be launched as a background process so the agent can resume on
exit instead of burning context on a sleep loop.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
import time
from typing import Any

# Authors that count as Codex. Case-insensitive substring match against login.
# `chatgpt-codex-connector[bot]` is the live login as of 2026-05-13;
# `codex[bot]` and `openai-codex` are conservative aliases against rename.
CODEX_LOGIN_PATTERNS = [
    re.compile(r"codex", re.IGNORECASE),
]


def log(msg: str) -> None:
    """Progress to stderr — stdout is reserved for the final JSON payload."""
    ts = dt.datetime.now(dt.timezone.utc).strftime("%H:%M:%S")
    print(f"[wait-for-codex {ts}] {msg}", file=sys.stderr, flush=True)


def gh_api(path: str) -> Any:
    """Call `gh api <path>` and return parsed JSON. Raises on non-zero exit."""
    result = subprocess.run(
        ["gh", "api", path],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise RuntimeError(f"gh api {path} failed: {result.stderr.strip()}")
    return json.loads(result.stdout) if result.stdout.strip() else None


def is_codex(login: str | None) -> bool:
    if not login:
        return False
    return any(p.search(login) for p in CODEX_LOGIN_PATTERNS)


def parse_iso(ts: str | None) -> dt.datetime | None:
    if not ts:
        return None
    # GitHub timestamps are like 2026-05-13T07:59:51Z
    return dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))


def check_reviews(owner: str, repo: str, pr: int, since: dt.datetime) -> dict | None:
    try:
        reviews = gh_api(f"repos/{owner}/{repo}/pulls/{pr}/reviews") or []
    except RuntimeError as e:
        log(f"reviews probe failed: {e}")
        return None
    for r in reviews:
        login = (r.get("user") or {}).get("login")
        submitted = parse_iso(r.get("submitted_at"))
        if is_codex(login) and submitted and submitted >= since:
            return {
                "kind": "review",
                "author": login,
                "state": r.get("state"),
                "body": r.get("body") or "",
                "ts": r.get("submitted_at"),
                "url": r.get("html_url"),
            }
    return None


def check_comments(owner: str, repo: str, pr: int, since: dt.datetime) -> dict | None:
    try:
        comments = gh_api(f"repos/{owner}/{repo}/issues/{pr}/comments") or []
    except RuntimeError as e:
        log(f"comments probe failed: {e}")
        return None
    for c in comments:
        login = (c.get("user") or {}).get("login")
        created = parse_iso(c.get("created_at"))
        if is_codex(login) and created and created >= since:
            return {
                "kind": "comment",
                "author": login,
                "body": c.get("body") or "",
                "ts": c.get("created_at"),
                "url": c.get("html_url"),
            }
    return None


def check_reactions(owner: str, repo: str, pr: int, since: dt.datetime) -> dict | None:
    """Codex's 'no issues' signal is a 👍 reaction on the PR (per Codex's own help text).
    We treat that as success — a clean review."""
    try:
        reactions = gh_api(
            f"repos/{owner}/{repo}/issues/{pr}/reactions?content=%2B1"
        ) or []
    except RuntimeError as e:
        log(f"reactions probe failed: {e}")
        return None
    for r in reactions:
        login = (r.get("user") or {}).get("login")
        created = parse_iso(r.get("created_at"))
        if is_codex(login) and created and created >= since:
            return {
                "kind": "reaction",
                "author": login,
                "body": "Codex reacted with +1 (no issues found).",
                "ts": r.get("created_at"),
                "url": None,
            }
    return None


def check_notifications(owner: str, repo: str, pr: int, since: dt.datetime) -> dict | None:
    """Hint-only: notifications confirm SOMETHING happened on the PR; the
    actual content comes from the reviews/comments probes. We return a hit
    here only if the other probes also confirm — this just speeds up the
    next loop iteration."""
    try:
        notifs = gh_api("notifications?all=true&per_page=20") or []
    except RuntimeError as e:
        log(f"notifications probe failed: {e}")
        return None
    for n in notifs:
        repo_full = (n.get("repository") or {}).get("full_name", "")
        if repo_full != f"{owner}/{repo}":
            continue
        url = (n.get("subject") or {}).get("url", "")
        if not url.endswith(f"/pulls/{pr}"):
            continue
        updated = parse_iso(n.get("updated_at"))
        if updated and updated >= since:
            # Something updated on the PR after our briefing — re-probe content surfaces.
            return {"kind": "notification-hint", "ts": n.get("updated_at")}
    return None


def find_codex_reply(
    owner: str, repo: str, pr: int, since: dt.datetime
) -> dict | None:
    """Run all probes; return the highest-fidelity hit, or None."""
    # Content probes first — these give us the actual reply body.
    for probe in (check_reviews, check_comments, check_reactions):
        hit = probe(owner, repo, pr, since)
        if hit:
            return hit
    # Notifications is a hint-only signal: if it fires but no content probe
    # hit, codex may still be drafting. Return None and keep polling.
    return None


def ping_codex(owner: str, repo: str, pr: int) -> None:
    """If Codex has been silent past the retry window, gently re-ping.
    Codex's help text says it responds to '@codex review' comments."""
    body = (
        "@codex review — pinging after extended silence. If you're queued "
        "or rate-limited, no rush; this is just to confirm the hook is live."
    )
    result = subprocess.run(
        ["gh", "pr", "comment", "-R", f"{owner}/{repo}", str(pr), "--body", body],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode == 0:
        log(f"re-pinged @codex on #{pr}")
    else:
        log(f"re-ping failed: {result.stderr.strip()}")


def parse_repo(repo_arg: str) -> tuple[str, str]:
    if "/" not in repo_arg:
        raise SystemExit(f"--repo must be in 'owner/name' form (got: {repo_arg!r})")
    owner, name = repo_arg.split("/", 1)
    return owner, name


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pr", type=int, required=True, help="PR number")
    ap.add_argument("--repo", required=True, help="owner/repo")
    ap.add_argument(
        "--since",
        required=True,
        help="ISO timestamp (UTC, Z-suffix OK) — replies before this are ignored. "
             "Use the briefing comment's createdAt.",
    )
    ap.add_argument(
        "--timeout-seconds", type=int, default=5400,
        help="Total wait ceiling. Default 90min — Codex is usually <10min but "
             "can stretch under load.",
    )
    ap.add_argument(
        "--poll-interval-seconds", type=int, default=30,
        help="Seconds between probes. Default 30s — Codex doesn't reply faster "
             "than ~30s anyway and we don't want to burn API budget.",
    )
    ap.add_argument(
        "--reping-after-seconds", type=int, default=1800,
        help="If no reply after this many seconds, post a re-ping comment and "
             "keep waiting. Default 30min. Set to 0 to disable re-pinging.",
    )
    ap.add_argument(
        "--max-repings", type=int, default=2,
        help="Maximum re-ping comments before giving up. Default 2 (so total "
             "wait is up to ~90min by default with re-pings at 30/60min).",
    )
    args = ap.parse_args()

    owner, repo = parse_repo(args.repo)
    since = parse_iso(args.since)
    if since is None:
        raise SystemExit(f"--since must be an ISO timestamp (got: {args.since!r})")

    log(f"waiting for codex on {owner}/{repo}#{args.pr} (since {since.isoformat()})")
    log(f"timeout={args.timeout_seconds}s poll={args.poll_interval_seconds}s reping={args.reping_after_seconds}s")

    start = time.monotonic()
    last_ping = start
    repings = 0

    while True:
        elapsed = time.monotonic() - start
        if elapsed >= args.timeout_seconds:
            log(f"timeout after {int(elapsed)}s - giving up")
            return 2

        hit = find_codex_reply(owner, repo, args.pr, since)
        if hit:
            if hit["kind"] == "reaction":
                log(f"codex +1 reaction at {hit['ts']} (clean review)")
                print(json.dumps(hit, indent=2))
                return 3
            log(f"codex {hit['kind']} from {hit['author']} at {hit['ts']}")
            print(json.dumps(hit, indent=2))
            return 0

        # Re-ping protocol
        if (
            args.reping_after_seconds > 0
            and repings < args.max_repings
            and (time.monotonic() - last_ping) >= args.reping_after_seconds
        ):
            ping_codex(owner, repo, args.pr)
            last_ping = time.monotonic()
            repings += 1
            # Move the `since` cursor to now so we don't see our own ping
            # as the codex reply.
            since = dt.datetime.now(dt.timezone.utc)

        time.sleep(args.poll_interval_seconds)


if __name__ == "__main__":
    sys.exit(main())
