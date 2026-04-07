"""
pipeline/reports.py
Generate markdown reports from metrics and LLM analysis data.
Pure string formatting — no LLM required.
"""
from datetime import datetime, timezone
from pathlib import Path


def _fmt(val, suffix="", na="—"):
    if val is None:
        return na
    return f"{val}{suffix}"


def _cycle_time_note(p50, p75, p95):
    if p50 is None:
        return "No cycle time data available."
    return (
        f"p50: **{p50}h**, p75: **{p75}h**, p95: **{p95}h**  \n"
        "*(Includes review wait time — high values often reflect reviewer availability, "
        "not author pace)*"
    )


def _size_dist_line(dist: dict) -> str:
    total = sum(dist.values())
    if total == 0:
        return "No data"
    parts = [f"{k}: {v} ({round(v/total*100)}%)" for k, v in dist.items() if v > 0]
    return ", ".join(parts)


def generate_team_report(metrics: dict, analysis: dict = None) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    computed_at = metrics.get("computed_at", now)[:10]
    team = metrics.get("team", {})
    pr_count = metrics.get("pr_count", 0)
    merged_count = metrics.get("merged_count", 0)

    # Filter non-bot developers
    by_dev = {
        k: v for k, v in metrics.get("by_developer", {}).items()
        if not v.get("is_bot")
    }
    dev_count = len(by_dev)

    # PRs with zero human review
    unreviewed = [
        p for p in metrics.get("by_pr", [])
        if p.get("merged") and not p.get("human_reviewers")
    ]

    # Review network summary
    network = team.get("review_network", [])
    network_lines = "\n".join(
        f"  - {e['from']} → {e['to']}: {e['count']} review(s)"
        for e in sorted(network, key=lambda x: -x["count"])
    ) or "  - No cross-review data"

    # LLM section
    has_analysis = analysis and analysis.get("results")
    if has_analysis:
        results = analysis["results"]
        all_categories = []
        for r in results:
            for c in r.get("review_classifications", []):
                all_categories.append(c.get("category", ""))
        from collections import Counter
        cat_counts = Counter(all_categories)
        top_cats = cat_counts.most_common(3)
        cat_summary = ", ".join(f"{cat} ({n})" for cat, n in top_cats)
        llm_section = f"""
## Code Review Analysis

Review comment categories (top 3 team-wide): **{cat_summary or 'N/A'}**

> *Note: Code quality scores (conciseness, self-review, firmware) require diff patch data. \
Re-run data collection with "Include diffs" enabled for full analysis.*
"""
    else:
        llm_section = """
## Code Review Analysis

*LLM analysis not yet run. Go to the LLM Analysis step to classify review comments \
and score code quality.*
"""

    # Reviewer load table
    reviewer_rows = sorted(
        [(dev, d) for dev, d in by_dev.items()],
        key=lambda x: -x[1].get("unique_prs_reviewed", 0),
    )
    reviewer_table = "| Developer | PRs Reviewed | Review Comments Given | Approvals | Changes Requested |\n"
    reviewer_table += "|---|---|---|---|---|\n"
    for dev, d in reviewer_rows:
        reviewer_table += (
            f"| {dev} | {d.get('unique_prs_reviewed', 0)} "
            f"| {d.get('review_comments_given', 0)} "
            f"| {d.get('approvals_given', 0)} "
            f"| {d.get('changes_requested_given', 0)} |\n"
        )

    # Delivery table
    delivery_rows = sorted(
        [(dev, d) for dev, d in by_dev.items() if d.get("prs_authored", 0) > 0],
        key=lambda x: -x[1].get("prs_authored", 0),
    )
    delivery_table = "| Developer | PRs Authored | Merged | Merge Rate | Avg Cycle Time | Net Lines |\n"
    delivery_table += "|---|---|---|---|---|---|\n"
    for dev, d in delivery_rows:
        ct = _fmt(d.get("avg_cycle_time_h"), "h")
        delivery_table += (
            f"| {dev} | {d.get('prs_authored', 0)} "
            f"| {d.get('prs_merged', 0)} "
            f"| {_fmt(d.get('merge_rate_pct'), '%')} "
            f"| {ct} "
            f"| {d.get('net_lines', 0):+d} |\n"
        )

    unreviewed_section = ""
    if unreviewed:
        unreviewed_section = f"""
### Merged Without Human Review ({len(unreviewed)} PRs)

| PR | Author |
|---|---|
""" + "\n".join(f"| #{p['number']}: {p['title'][:50]} | {p['author']} |" for p in unreviewed)
    else:
        unreviewed_section = "\n**All merged PRs received at least one human review.** ✓"

    report = f"""# Team Health Report

**Generated:** {now}
**Data period ending:** {computed_at}
**PRs analyzed:** {pr_count} total, {merged_count} merged
**Team size:** {dev_count} developers (bots excluded)

---

> This report is designed for team-level discussion and continuous improvement.
> Individual metrics are not intended for performance ranking or HR decisions.

---

## Delivery

**Cycle Time Distribution** (open → merge, human authors only)

{_cycle_time_note(team.get('cycle_time_p50'), team.get('cycle_time_p75'), team.get('cycle_time_p95'))}

**PR Size Distribution:** {_size_dist_line(team.get('size_distribution', {}))}

{delivery_table}

---

## Review Health

**Review Coverage:** {_fmt(team.get('review_coverage_pct'), '%')} of PRs received at least one human review
**Median Review Turnaround:** {_fmt(team.get('median_review_turnaround_h'), 'h')} (team-wide, not attributed to individuals)

{reviewer_table}

{unreviewed_section}

---

## Collaboration

**Review Network** (who reviews whose work):

{network_lines}

---
{llm_section}

---

## Team Risks

"""

    # Add risk signals
    risks = []
    if team.get("review_coverage_pct", 100) < 80:
        risks.append(
            f"- **Review coverage below 80%** ({team.get('review_coverage_pct')}%). "
            "Increase peer review adoption."
        )
    if unreviewed:
        risks.append(
            f"- **{len(unreviewed)} merged PRs had no human review.** "
            "Consider branch protection rules requiring at least one approval."
        )
    if team.get("cycle_time_p95") and team.get("cycle_time_p50"):
        ratio = team["cycle_time_p95"] / team["cycle_time_p50"]
        if ratio > 5:
            risks.append(
                f"- **High cycle time variance** (p95={team['cycle_time_p95']}h vs p50={team['cycle_time_p50']}h). "
                "A few PRs are taking significantly longer — investigate review bottlenecks."
            )

    if not risks:
        risks.append("- No significant team-level risks detected in this dataset.")

    report += "\n".join(risks)
    report += "\n\n---\n\n*Report generated by Developer Performance Tracker. "
    report += "Metrics are designed to surface team health signals, not to rank individuals.*\n"

    return report


def generate_individual_report(developer: str, metrics: dict, analysis: dict = None) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    by_dev = metrics.get("by_developer", {})

    if developer not in by_dev:
        return f"# No data found for {developer}\n"

    d = by_dev[developer]
    by_pr = [p for p in metrics.get("by_pr", []) if p.get("author") == developer]

    # PRs authored
    authored_table = "| PR | Merged | Size | Cycle Time | Review Rounds | Comments Received |\n"
    authored_table += "|---|---|---|---|---|---|\n"
    for p in by_pr:
        authored_table += (
            f"| #{p['number']}: {p['title'][:40]} "
            f"| {'✓' if p.get('merged') else '✗'} "
            f"| {p.get('size_bucket', '?')} "
            f"| {_fmt(p.get('cycle_time_h'), 'h')} "
            f"| {p.get('review_rounds', 0)} "
            f"| {p.get('review_comment_count', 0)} |\n"
        )

    # LLM feedback analysis
    llm_section = ""
    if analysis and analysis.get("results"):
        dev_results = [r for r in analysis["results"] if r.get("author") == developer]
        if dev_results:
            from collections import Counter
            received_cats = []
            for r in dev_results:
                for c in r.get("review_classifications", []):
                    received_cats.append(c.get("category", ""))
            cat_counts = Counter(received_cats)

            llm_section = "\n## Review Feedback You Received\n\n"
            llm_section += "**Comment categories:**\n\n"
            llm_section += "| Category | Count |\n|---|---|\n"
            for cat, count in sorted(cat_counts.items(), key=lambda x: -x[1]):
                llm_section += f"| {cat.replace('_', ' ').title()} | {count} |\n"

            # Quality scores
            scores = {
                "Conciseness": [r["conciseness"]["score"] for r in dev_results if r["conciseness"].get("score")],
                "Self-Review": [r["self_review"]["score"] for r in dev_results if r["self_review"].get("score")],
                "Firmware": [r["firmware_concerns"]["score"] for r in dev_results if r["firmware_concerns"].get("score")],
            }
            has_scores = any(v for v in scores.values())
            if has_scores:
                llm_section += "\n## Code Quality Scores\n\n"
                llm_section += "| Dimension | Avg Score (1–5) |\n|---|---|\n"
                for dim, vals in scores.items():
                    if vals:
                        avg = round(sum(vals) / len(vals), 1)
                        llm_section += f"| {dim} | {avg} |\n"
            else:
                llm_section += (
                    "\n*Code quality scores not available — diffs were not collected. "
                    "Re-run data collection with 'Include diffs' to enable.*\n"
                )

    report = f"""# Developer Report — {developer}

**Generated:** {now}
*(This report is for your own reference and 1-on-1 discussions with your lead — not for team-wide distribution)*

---

## Your Authoring Activity

- **PRs Authored:** {d.get('prs_authored', 0)}
- **Merged:** {d.get('prs_merged', 0)} ({_fmt(d.get('merge_rate_pct'), '%')} merge rate)
- **Avg Cycle Time:** {_fmt(d.get('avg_cycle_time_h'), 'h')} *(open → merge, includes review wait)*
- **Avg Review Rounds:** {_fmt(d.get('avg_review_rounds'))}
- **Net Lines:** {d.get('net_lines', 0):+d}

{authored_table}

---

## Your Review Contributions

- **PRs Reviewed:** {d.get('unique_prs_reviewed', 0)}
- **Review Comments Left:** {d.get('review_comments_given', 0)}
- **Approvals Given:** {d.get('approvals_given', 0)}
- **Changes Requested:** {d.get('changes_requested_given', 0)}

---
{llm_section}

---

## Growth Areas

*Trend analysis requires data from multiple collection runs (historical comparison not yet available).*

---

*This report is generated automatically from GitHub PR data. "
"It surfaces patterns to help guide growth conversations — not to evaluate performance in isolation.*
"""

    return report


def save_report(content: str, path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


def load_report(path: str) -> str:
    with open(path) as f:
        return f.read()
