"""
pipeline/metrics.py
Compute quantitative metrics from raw PR data.
No LLM required — pure data aggregation.
"""
import json
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

BOT_LOGINS = {"Copilot"}


def _is_bot(login: str) -> bool:
    return login.endswith("[bot]") or login in BOT_LOGINS


def _size_bucket(additions: int, deletions: int) -> str:
    total = additions + deletions
    if total < 100:
        return "S"
    elif total < 400:
        return "M"
    elif total < 1000:
        return "L"
    else:
        return "XL"


def _percentile(data: list, p: float):
    if not data:
        return None
    sorted_data = sorted(data)
    idx = (len(sorted_data) - 1) * p / 100
    lo, hi = int(idx), min(int(idx) + 1, len(sorted_data) - 1)
    return round(sorted_data[lo] + (sorted_data[hi] - sorted_data[lo]) * (idx - lo), 2)


def compute(prs: list, output_path: str = "data/metrics.json") -> dict:
    """
    Compute all quantitative metrics from raw PR list.
    Returns metrics dict and writes to output_path.
    """
    dev_data = defaultdict(lambda: {
        "prs_authored": 0,
        "prs_merged": 0,
        "cycle_times_h": [],
        "size_buckets": {"S": 0, "M": 0, "L": 0, "XL": 0},
        "net_lines": 0,
        "first_review_lags_h": [],
        "review_rounds": [],
        "unique_prs_reviewed": set(),
        "review_comments_given": 0,
        "review_comments_received": 0,
        "discussion_comments_given": 0,
        "approvals_given": 0,
        "changes_requested_given": 0,
        "is_bot": False,
    })

    # Track review network: reviewer -> author -> count
    review_network_raw = defaultdict(lambda: defaultdict(int))

    all_cycle_times = []
    all_review_lags = []
    size_dist = {"S": 0, "M": 0, "L": 0, "XL": 0}
    prs_with_human_review = 0

    by_pr = []

    for pr in prs:
        author = pr["author"]
        dev_data[author]["is_bot"] = _is_bot(author)
        dev_data[author]["prs_authored"] += 1
        if pr.get("merged"):
            dev_data[author]["prs_merged"] += 1

        ct = pr.get("cycle_time_h")
        if ct is not None and not _is_bot(author):
            dev_data[author]["cycle_times_h"].append(ct)
            all_cycle_times.append(ct)

        bucket = _size_bucket(pr.get("additions", 0), pr.get("deletions", 0))
        dev_data[author]["size_buckets"][bucket] += 1
        size_dist[bucket] += 1

        net = pr.get("additions", 0) - pr.get("deletions", 0)
        dev_data[author]["net_lines"] += net

        lag = pr.get("first_review_lag_h")
        if lag is not None and not _is_bot(author):
            dev_data[author]["first_review_lags_h"].append(lag)
            all_review_lags.append(lag)

        rounds = pr.get("review_rounds", 0)
        dev_data[author]["review_rounds"].append(rounds)

        # Reviews
        reviews = pr.get("reviews", [])
        human_reviewers = set()
        for rv in reviews:
            reviewer = rv["reviewer"]
            if reviewer == author:
                continue
            dev_data[reviewer]["is_bot"] = _is_bot(reviewer)
            dev_data[reviewer]["unique_prs_reviewed"].add(pr["number"])
            if rv["state"] == "APPROVED":
                dev_data[reviewer]["approvals_given"] += 1
            elif rv["state"] == "CHANGES_REQUESTED":
                dev_data[reviewer]["changes_requested_given"] += 1
            if not _is_bot(reviewer):
                human_reviewers.add(reviewer)
                review_network_raw[reviewer][author] += 1

        if human_reviewers:
            prs_with_human_review += 1

        # Review comments
        for c in pr.get("review_comments", []):
            commenter = c["author"]
            dev_data[commenter]["is_bot"] = _is_bot(commenter)
            if commenter != author:
                dev_data[commenter]["review_comments_given"] += 1
                dev_data[author]["review_comments_received"] += 1

        # Discussion comments
        for c in pr.get("issue_comments", []):
            commenter = c["author"]
            dev_data[commenter]["is_bot"] = _is_bot(commenter)
            if commenter != author:
                dev_data[commenter]["discussion_comments_given"] += 1

        by_pr.append({
            "number": pr["number"],
            "title": pr["title"],
            "author": author,
            "merged": pr.get("merged", False),
            "additions": pr.get("additions", 0),
            "deletions": pr.get("deletions", 0),
            "size_bucket": bucket,
            "cycle_time_h": ct,
            "first_review_lag_h": lag,
            "review_rounds": rounds,
            "human_reviewers": list(human_reviewers),
            "review_comment_count": len([
                c for c in pr.get("review_comments", []) if c["author"] != author
            ]),
        })

    # Build review network list
    review_network = []
    for reviewer, targets in review_network_raw.items():
        for target_author, count in targets.items():
            review_network.append({"from": reviewer, "to": target_author, "count": count})

    # Build by_developer (serialize sets)
    by_developer = {}
    for dev, d in dev_data.items():
        by_developer[dev] = {
            "prs_authored": d["prs_authored"],
            "prs_merged": d["prs_merged"],
            "merge_rate_pct": round(d["prs_merged"] / d["prs_authored"] * 100, 1)
            if d["prs_authored"] else 0,
            "cycle_times_h": d["cycle_times_h"],
            "avg_cycle_time_h": round(statistics.mean(d["cycle_times_h"]), 2)
            if d["cycle_times_h"] else None,
            "size_buckets": d["size_buckets"],
            "net_lines": d["net_lines"],
            "avg_first_review_lag_h": round(statistics.mean(d["first_review_lags_h"]), 2)
            if d["first_review_lags_h"] else None,
            "avg_review_rounds": round(statistics.mean(d["review_rounds"]), 2)
            if d["review_rounds"] else None,
            "unique_prs_reviewed": len(d["unique_prs_reviewed"]),
            "review_comments_given": d["review_comments_given"],
            "review_comments_received": d["review_comments_received"],
            "discussion_comments_given": d["discussion_comments_given"],
            "approvals_given": d["approvals_given"],
            "changes_requested_given": d["changes_requested_given"],
            "is_bot": d["is_bot"],
        }

    merged_prs = [pr for pr in prs if pr.get("merged")]
    review_coverage = round(prs_with_human_review / len(prs) * 100, 1) if prs else 0

    metrics = {
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "pr_count": len(prs),
        "merged_count": len(merged_prs),
        "team": {
            "cycle_time_p50": _percentile(all_cycle_times, 50),
            "cycle_time_p75": _percentile(all_cycle_times, 75),
            "cycle_time_p95": _percentile(all_cycle_times, 95),
            "review_coverage_pct": review_coverage,
            "median_review_turnaround_h": _percentile(all_review_lags, 50),
            "size_distribution": size_dist,
            "review_network": review_network,
        },
        "by_developer": by_developer,
        "by_pr": by_pr,
    }

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(metrics, f, indent=2)

    return metrics


def load_metrics(path: str = "data/metrics.json") -> dict:
    with open(path) as f:
        return json.load(f)
