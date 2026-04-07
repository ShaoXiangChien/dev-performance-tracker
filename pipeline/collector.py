"""
pipeline/collector.py
Importable refactor of collect_pr_data.py.
All GitHub credentials are passed as parameters — nothing is read at import time.
"""
import json
import os
import time
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

BOT_LOGINS = {"Copilot"}  # exact-match bots (in addition to [bot] suffix check)


def _is_bot(login: str) -> bool:
    return login.endswith("[bot]") or login in BOT_LOGINS


def _make_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def get(url, headers, params=None):
    """GET with rate-limit retry."""
    while True:
        r = requests.get(url, headers=headers, params=params)
        if r.status_code == 403 and "rate limit" in r.text.lower():
            reset = int(r.headers.get("X-RateLimit-Reset", time.time() + 60))
            wait = max(reset - time.time(), 1)
            time.sleep(wait)
            continue
        r.raise_for_status()
        return r.json()


def paginate(url, headers, params=None, max_items=500):
    params = {**(params or {}), "per_page": 100, "page": 1}
    items = []
    while len(items) < max_items:
        batch = get(url, headers, params)
        if not batch:
            break
        items.extend(batch)
        if len(batch) < 100:
            break
        params["page"] += 1
    return items[:max_items]


def pr_cycle_time_hours(pr):
    if not pr.get("merged_at"):
        return None
    created = datetime.fromisoformat(pr["created_at"].replace("Z", "+00:00"))
    merged = datetime.fromisoformat(pr["merged_at"].replace("Z", "+00:00"))
    return round((merged - created).total_seconds() / 3600, 2)


def first_review_lag_hours(pr, reviews):
    author = pr["user"]["login"]
    created = datetime.fromisoformat(pr["created_at"].replace("Z", "+00:00"))
    others = [r for r in reviews if r["user"]["login"] != author and r["submitted_at"]]
    if not others:
        return None
    first = min(
        datetime.fromisoformat(r["submitted_at"].replace("Z", "+00:00")) for r in others
    )
    return round((first - created).total_seconds() / 3600, 2)


def collect(
    github_token: str,
    repo: str,
    days: int = 90,
    limit: int = 200,
    include_diffs: bool = False,
    output_path: str = "data/pr_raw.json",
    progress_callback=None,
) -> list:
    """
    Fetch PR data from GitHub API and return list of PR dicts.
    Writes output to output_path.

    progress_callback(current, total, message) — called after each PR is processed.
    include_diffs — if True, fetches file patches per PR (~2x API calls).
    """
    headers = _make_headers(github_token)
    base = f"https://api.github.com/repos/{repo}"
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    prs_list = paginate(
        f"{base}/pulls",
        headers,
        params={"state": "closed", "sort": "updated", "direction": "desc"},
        max_items=limit,
    )
    prs_list = [p for p in prs_list if p.get("closed_at") and p["closed_at"] >= since]

    total = len(prs_list)
    raw_prs = []

    for i, pr_stub in enumerate(prs_list, 1):
        num = pr_stub["number"]
        pr = get(f"{base}/pulls/{num}", headers)
        author = pr["user"]["login"]

        if progress_callback:
            progress_callback(i, total, f"PR #{num} by {author}")

        reviews = get(f"{base}/pulls/{num}/reviews", headers)
        review_comments = get(f"{base}/pulls/{num}/comments", headers)
        issue_comments = get(f"{base}/issues/{num}/comments", headers)

        lag = first_review_lag_hours(pr, reviews)

        non_author_reviews = [r for r in reviews if r["user"]["login"] != author]
        rounds = len(set(
            (r["user"]["login"], r["submitted_at"][:10])
            for r in non_author_reviews
        ))

        record = {
            "number": num,
            "title": pr["title"],
            "author": author,
            "state": pr["state"],
            "merged": pr["merged"],
            "draft": pr["draft"],
            "created_at": pr["created_at"],
            "merged_at": pr["merged_at"],
            "closed_at": pr["closed_at"],
            "base_branch": pr["base"]["ref"],
            "head_branch": pr["head"]["ref"],
            "additions": pr["additions"],
            "deletions": pr["deletions"],
            "changed_files": pr["changed_files"],
            "commits": pr["commits"],
            "cycle_time_h": pr_cycle_time_hours(pr),
            "first_review_lag_h": lag,
            "review_rounds": rounds,
            "labels": [l["name"] for l in pr["labels"]],
            "reviews": [
                {
                    "reviewer": r["user"]["login"],
                    "state": r["state"],
                    "submitted_at": r["submitted_at"],
                }
                for r in reviews
            ],
            "review_comments": [
                {
                    "author": c["user"]["login"],
                    "path": c["path"],
                    "line": c.get("line"),
                    "created_at": c["created_at"],
                    "body": c["body"],
                }
                for c in review_comments
            ],
            "issue_comments": [
                {
                    "author": c["user"]["login"],
                    "created_at": c["created_at"],
                    "body": c["body"],
                }
                for c in issue_comments
            ],
        }

        if include_diffs:
            files = get(f"{base}/pulls/{num}/files", headers)
            record["files"] = [
                {
                    "filename": f["filename"],
                    "status": f["status"],
                    "additions": f["additions"],
                    "deletions": f["deletions"],
                    "patch": f.get("patch", ""),
                }
                for f in files
            ]

        raw_prs.append(record)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(raw_prs, f, indent=2)

    return raw_prs


def load_raw(path: str = "data/pr_raw.json") -> list:
    with open(path) as f:
        return json.load(f)
