"""
Script 1: Explore what raw fields a single PR gives us.
Run this first to understand the data shape.
"""
import json
import os
import requests
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("GITHUB_TOKEN")
REPO  = os.getenv("GITHUB_REPO")  # "owner/repo"

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}


def get(url, params=None):
    r = requests.get(url, headers=HEADERS, params=params)
    r.raise_for_status()
    return r.json()


def explore_single_pr():
    # Grab the most recently closed PR
    prs = get(f"https://api.github.com/repos/{REPO}/pulls", params={
        "state": "closed", "per_page": 1, "sort": "updated", "direction": "desc"
    })
    if not prs:
        print("No closed PRs found.")
        return

    pr_number = prs[0]["number"]
    # The list endpoint omits some fields (e.g. `merged`, `additions`, `deletions`)
    # Fetch the full single-PR object to get everything.
    pr = get(f"https://api.github.com/repos/{REPO}/pulls/{pr_number}")
    print(f"\n=== PR #{pr_number}: {pr['title']} ===\n")

    # ── Top-level PR fields ────────────────────────────────────────────────────
    interesting = {
        "number":            pr["number"],
        "state":             pr["state"],
        "draft":             pr["draft"],
        "title":             pr["title"],
        "author":            pr["user"]["login"],
        "created_at":        pr["created_at"],
        "updated_at":        pr["updated_at"],
        "closed_at":         pr["closed_at"],
        "merged_at":         pr["merged_at"],
        "merged":            pr["merged"],
        "merge_commit_sha":  pr["merge_commit_sha"],
        "base_branch":       pr["base"]["ref"],
        "head_branch":       pr["head"]["ref"],
        "additions":         pr["additions"],
        "deletions":         pr["deletions"],
        "changed_files":     pr["changed_files"],
        "commits":           pr["commits"],
        "comments":          pr["comments"],          # issue-style comments
        "review_comments":   pr["review_comments"],   # inline code review comments
        "labels":            [l["name"] for l in pr["labels"]],
        "milestone":         pr["milestone"]["title"] if pr["milestone"] else None,
        "requested_reviewers": [r["login"] for r in pr["requested_reviewers"]],
        "assignees":         [a["login"] for a in pr["assignees"]],
        "author_association": pr["author_association"],   # OWNER / MEMBER / CONTRIBUTOR / etc.
    }
    print("── Core fields ──")
    print(json.dumps(interesting, indent=2))

    # ── Reviews ───────────────────────────────────────────────────────────────
    reviews = get(f"https://api.github.com/repos/{REPO}/pulls/{pr_number}/reviews")
    print(f"\n── Reviews ({len(reviews)} total) ──")
    for rv in reviews:
        print(f"  {rv['user']['login']:20s}  state={rv['state']:20s}  submitted={rv['submitted_at']}")
    # Possible states: APPROVED, CHANGES_REQUESTED, COMMENTED, DISMISSED, PENDING

    # ── Review comments (inline) ──────────────────────────────────────────────
    review_comments = get(f"https://api.github.com/repos/{REPO}/pulls/{pr_number}/comments")
    print(f"\n── Inline review comments ({len(review_comments)} total) ──")
    for c in review_comments[:5]:   # first 5 only
        print(f"  {c['user']['login']:20s}  path={c['path']}:{c['line']}  created={c['created_at']}")
    if len(review_comments) > 5:
        print(f"  ... and {len(review_comments) - 5} more")

    # ── Commits ───────────────────────────────────────────────────────────────
    commits = get(f"https://api.github.com/repos/{REPO}/pulls/{pr_number}/commits")
    print(f"\n── Commits ({len(commits)} total) ──")
    for c in commits[:5]:
        author = c["author"]["login"] if c["author"] else c["commit"]["author"]["name"]
        print(f"  {author:20s}  {c['sha'][:8]}  {c['commit']['message'][:60]}")
    if len(commits) > 5:
        print(f"  ... and {len(commits) - 5} more")

    # ── Files changed ─────────────────────────────────────────────────────────
    files = get(f"https://api.github.com/repos/{REPO}/pulls/{pr_number}/files")
    print(f"\n── Files changed ({len(files)} total) ──")
    for f in files[:8]:
        print(f"  {f['status']:10s}  +{f['additions']:4d} -{f['deletions']:4d}  {f['filename']}")
    if len(files) > 8:
        print(f"  ... and {len(files) - 8} more")

    # ── Issue comments (general discussion) ──────────────────────────────────
    issue_comments = get(f"https://api.github.com/repos/{REPO}/issues/{pr_number}/comments")
    print(f"\n── Issue/discussion comments ({len(issue_comments)} total) ──")
    for c in issue_comments[:5]:
        print(f"  {c['user']['login']:20s}  created={c['created_at']}")
    if len(issue_comments) > 5:
        print(f"  ... and {len(issue_comments) - 5} more")

    # ── CI / Check runs ───────────────────────────────────────────────────────
    # Requires the token to have Checks read access; skip gracefully if not granted.
    head_sha = pr["head"]["sha"]
    try:
        check_runs = get(f"https://api.github.com/repos/{REPO}/commits/{head_sha}/check-runs")
        runs = check_runs.get("check_runs", [])
        print(f"\n── CI check runs ({len(runs)} total) ──")
        for cr in runs[:8]:
            print(f"  {cr['name']:40s}  status={cr['status']:10s}  conclusion={cr['conclusion']}")
        if len(runs) > 8:
            print(f"  ... and {len(runs) - 8} more")
    except Exception as e:
        print(f"\n── CI check runs ──\n  (skipped: {e})")


if __name__ == "__main__":
    explore_single_pr()
