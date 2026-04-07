"""
Script 2: Collect a batch of PRs and compute per-developer metrics.
Outputs raw numbers so you can decide what's meaningful before building a score.

Usage:
    python collect_pr_data.py [--days 90] [--limit 200]
"""
import argparse
import json
import os
import time
from collections import defaultdict
from datetime import datetime, timezone, timedelta

import requests
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("GITHUB_TOKEN")
REPO  = os.getenv("GITHUB_REPO")

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}


def get(url, params=None):
    """GET with simple rate-limit retry."""
    while True:
        r = requests.get(url, headers=HEADERS, params=params)
        if r.status_code == 403 and "rate limit" in r.text.lower():
            reset = int(r.headers.get("X-RateLimit-Reset", time.time() + 60))
            wait = max(reset - time.time(), 1)
            print(f"  [rate limit] sleeping {wait:.0f}s …")
            time.sleep(wait)
            continue
        r.raise_for_status()
        return r.json()


def paginate(url, params=None, max_items=500):
    params = {**(params or {}), "per_page": 100, "page": 1}
    items = []
    while len(items) < max_items:
        batch = get(url, params)
        if not batch:
            break
        items.extend(batch)
        if len(batch) < 100:
            break
        params["page"] += 1
    return items[:max_items]


def pr_cycle_time_hours(pr):
    """Wall-clock hours from PR open → merge."""
    if not pr["merged_at"]:
        return None
    created = datetime.fromisoformat(pr["created_at"].replace("Z", "+00:00"))
    merged  = datetime.fromisoformat(pr["merged_at"].replace("Z",  "+00:00"))
    return (merged - created).total_seconds() / 3600


def first_review_lag_hours(pr, reviews):
    """Hours from PR open until the first non-author review activity."""
    author = pr["user"]["login"]
    created = datetime.fromisoformat(pr["created_at"].replace("Z", "+00:00"))
    others = [
        r for r in reviews
        if r["user"]["login"] != author and r["submitted_at"]
    ]
    if not others:
        return None
    first = min(datetime.fromisoformat(r["submitted_at"].replace("Z", "+00:00")) for r in others)
    return (first - created).total_seconds() / 3600


def collect(days, limit):
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    print(f"Fetching up to {limit} closed PRs from {REPO} (last {days} days) …")

    prs = paginate(
        f"https://api.github.com/repos/{REPO}/pulls",
        params={"state": "closed", "sort": "updated", "direction": "desc"},
        max_items=limit,
    )

    # Filter to within the time window
    prs = [
        p for p in prs
        if p["closed_at"] and p["closed_at"] >= since
    ]
    print(f"  {len(prs)} PRs in window\n")

    # Per-developer accumulators
    authors   = defaultdict(lambda: {
        # ── authoring ──────────────────────────────────────────────────
        "prs_opened":          0,
        "prs_merged":          0,
        "prs_closed_unmerged": 0,
        "total_additions":     0,
        "total_deletions":     0,
        "total_files_changed": 0,
        "total_commits":       0,
        "cycle_times_h":       [],   # hours open→merge, per PR
        # ── review work received ───────────────────────────────────────
        "review_rounds":       [],   # #review-rounds per PR (back-and-forth proxy)
        "first_review_lag_h":  [],   # hours until first review
        # ── commenting ────────────────────────────────────────────────
        "discussion_comments_received": 0,
        "review_comments_received":     0,
    })

    reviewers = defaultdict(lambda: {
        # ── review work given ──────────────────────────────────────────
        "reviews_given":           0,
        "approvals":               0,
        "changes_requested":       0,
        "review_comments_left":    0,
        "prs_reviewed":            set(),   # unique PRs reviewed
    })

    commenters = defaultdict(lambda: {
        "discussion_comments_left": 0,
    })

    raw_prs = []  # full per-PR data for pr_raw.json

    for i, pr in enumerate(prs, 1):
        num    = pr["number"]
        # Fetch full PR object — the list endpoint omits merged, additions, deletions, etc.
        pr     = get(f"https://api.github.com/repos/{REPO}/pulls/{num}")
        author = pr["user"]["login"]
        print(f"  [{i:3d}/{len(prs)}] PR #{num} by {author}", end="  ", flush=True)

        # ── basic authoring metrics ────────────────────────────────────────────
        a = authors[author]
        a["prs_opened"] += 1
        if pr["merged"]:
            a["prs_merged"] += 1
        else:
            a["prs_closed_unmerged"] += 1
        a["total_additions"]     += pr["additions"]
        a["total_deletions"]     += pr["deletions"]
        a["total_files_changed"] += pr["changed_files"]
        a["total_commits"]       += pr["commits"]

        ct = pr_cycle_time_hours(pr)
        if ct is not None:
            a["cycle_times_h"].append(ct)

        # ── reviews ───────────────────────────────────────────────────────────
        reviews = get(f"https://api.github.com/repos/{REPO}/pulls/{num}/reviews")
        lag = first_review_lag_hours(pr, reviews)
        if lag is not None:
            a["first_review_lag_h"].append(lag)

        # Count review rounds (distinct submit times from non-author reviewers)
        non_author_reviews = [r for r in reviews if r["user"]["login"] != author]
        # A "round" = a reviewer submitting after the author's last push
        # Simple proxy: just count unique (reviewer, day) pairs
        rounds = len(set(
            (r["user"]["login"], r["submitted_at"][:10])
            for r in non_author_reviews
        ))
        a["review_rounds"].append(rounds)

        for rv in reviews:
            reviewer = rv["user"]["login"]
            if reviewer == author:
                continue
            rv_data = reviewers[reviewer]
            rv_data["reviews_given"] += 1
            rv_data["prs_reviewed"].add(num)
            if rv["state"] == "APPROVED":
                rv_data["approvals"] += 1
            elif rv["state"] == "CHANGES_REQUESTED":
                rv_data["changes_requested"] += 1

        # ── inline review comments ────────────────────────────────────────────
        review_comments = get(f"https://api.github.com/repos/{REPO}/pulls/{num}/comments")
        a["review_comments_received"] += sum(
            1 for c in review_comments if c["user"]["login"] != author
        )
        for c in review_comments:
            commenter = c["user"]["login"]
            if commenter != author:
                reviewers[commenter]["review_comments_left"] += 1

        # ── discussion comments ───────────────────────────────────────────────
        issue_comments = get(f"https://api.github.com/repos/{REPO}/issues/{num}/comments")
        a["discussion_comments_received"] += sum(
            1 for c in issue_comments if c["user"]["login"] != author
        )
        for c in issue_comments:
            commenter = c["user"]["login"]
            commenters[commenter]["discussion_comments_left"] += 1

        raw_prs.append({
            "number":           num,
            "title":            pr["title"],
            "author":           author,
            "state":            pr["state"],
            "merged":           pr["merged"],
            "draft":            pr["draft"],
            "created_at":       pr["created_at"],
            "merged_at":        pr["merged_at"],
            "closed_at":        pr["closed_at"],
            "base_branch":      pr["base"]["ref"],
            "head_branch":      pr["head"]["ref"],
            "additions":        pr["additions"],
            "deletions":        pr["deletions"],
            "changed_files":    pr["changed_files"],
            "commits":          pr["commits"],
            "cycle_time_h":     pr_cycle_time_hours(pr),
            "first_review_lag_h": lag,
            "labels":           [l["name"] for l in pr["labels"]],
            "reviews": [
                {
                    "reviewer":     r["user"]["login"],
                    "state":        r["state"],
                    "submitted_at": r["submitted_at"],
                }
                for r in reviews
            ],
            "review_comments": [
                {
                    "author":     c["user"]["login"],
                    "path":       c["path"],
                    "line":       c.get("line"),
                    "created_at": c["created_at"],
                    "body":       c["body"],
                }
                for c in review_comments
            ],
            "issue_comments": [
                {
                    "author":     c["user"]["login"],
                    "created_at": c["created_at"],
                    "body":       c["body"],
                }
                for c in issue_comments
            ],
        })

        print("✓")

    with open("pr_raw.json", "w") as f:
        json.dump(raw_prs, f, indent=2)
    print("Raw PR data saved to pr_raw.json")

    return authors, reviewers, commenters


def avg(lst):
    return round(sum(lst) / len(lst), 1) if lst else None


def summarise(authors, reviewers, commenters):
    print("\n" + "=" * 80)
    print("PER-DEVELOPER SUMMARY")
    print("=" * 80)

    all_devs = set(authors) | set(reviewers) | set(commenters)

    rows = []
    for dev in sorted(all_devs):
        a  = authors.get(dev,   {})
        rv = reviewers.get(dev, {})
        cm = commenters.get(dev, {})

        rows.append({
            "developer":                   dev,
            # authoring
            "prs_opened":                  a.get("prs_opened", 0),
            "prs_merged":                  a.get("prs_merged", 0),
            "merge_rate_%":                round(a["prs_merged"] / a["prs_opened"] * 100) if a.get("prs_opened") else None,
            "avg_cycle_time_h":            avg(a.get("cycle_times_h", [])),
            "avg_first_review_lag_h":      avg(a.get("first_review_lag_h", [])),
            "avg_review_rounds":           avg(a.get("review_rounds", [])),
            "total_additions":             a.get("total_additions", 0),
            "total_deletions":             a.get("total_deletions", 0),
            "total_files_changed":         a.get("total_files_changed", 0),
            "total_commits":               a.get("total_commits", 0),
            "review_comments_received":    a.get("review_comments_received", 0),
            # reviewing
            "unique_prs_reviewed":         len(rv.get("prs_reviewed", set())),
            "approvals_given":             rv.get("approvals", 0),
            "changes_requested_given":     rv.get("changes_requested", 0),
            "review_comments_left":        rv.get("review_comments_left", 0),
            # discussion
            "discussion_comments_left":    cm.get("discussion_comments_left", 0),
        })

    # Print as a table
    col_w = 32
    num_w = 10
    header_keys = list(rows[0].keys()) if rows else []
    print(f"\n{'developer':{col_w}}", end="")
    for k in header_keys[1:]:
        print(f"{k:{num_w}}", end="")
    print()
    print("-" * (col_w + num_w * (len(header_keys) - 1)))
    for row in rows:
        print(f"{row['developer']:{col_w}}", end="")
        for k in header_keys[1:]:
            v = row[k]
            print(f"{str(v) if v is not None else '-':{num_w}}", end="")
        print()

    # Also dump as JSON for later analysis
    out = "pr_data_summary.json"
    with open(out, "w") as f:
        json.dump(rows, f, indent=2)
    print(f"\nFull data saved to {out}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--days",  type=int, default=90,  help="Look-back window in days")
    parser.add_argument("--limit", type=int, default=200, help="Max PRs to fetch")
    args = parser.parse_args()

    authors, reviewers, commenters = collect(args.days, args.limit)
    summarise(authors, reviewers, commenters)
