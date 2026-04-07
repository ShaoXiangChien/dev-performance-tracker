# Metrics Design

This document defines every metric the tool computes, how it's calculated, what it actually measures, and — critically — how it can be misinterpreted and what safeguards prevent that.

## Metric Categories

```
A. Delivery Metrics        — What is the team shipping?
B. Review Metrics           — How is the team reviewing?
C. Collaboration Metrics    — How is the team working together?
D. Code Quality Metrics     — What is the quality of the output? (LLM-powered, see also 04-code-quality-analysis.md)
E. Growth Metrics           — How are individuals improving over time? (LLM-powered)
```

---

## A. Delivery Metrics

These measure the authoring/shipping side of development work.

### A1. PR Merge Rate

| | |
|---|---|
| **Formula** | `merged_prs / opened_prs` (per developer, per time window) |
| **Data source** | `pr.merged`, `pr.state` |
| **What it measures** | Proportion of opened PRs that successfully merge |
| **What it does NOT measure** | Code quality. A 100% merge rate with no reviews is worse than 80% with thorough review. |
| **Bias risk** | PRs closed then reopened on the same branch (e.g., to rebase or fix CI) inflate the "unmerged" count. |
| **Safeguard** | **Dedup by `head.ref` (branch name)**. If multiple PRs share the same head branch, treat them as one logical PR — only the final outcome counts. |
| **Presentation** | Show as a single number per dev, but flag if the denominator is small (< 5 PRs). Small samples are not meaningful. |

### A2. Cycle Time Distribution

| | |
|---|---|
| **Formula** | `merged_at - created_at` for each merged PR |
| **Data source** | `pr.created_at`, `pr.merged_at` |
| **What it measures** | Wall-clock time from PR open to merge |
| **What it does NOT measure** | How much of that time the author was actively working. A PR waiting 20 hours for review is not the author's problem. |
| **Bias risk** | **High.** This is the single most abused metric in engineering management. Showing an average punishes devs whose PRs wait for reviewers. |
| **Safeguard** | **Never report as a single average.** Report as distribution: p50, p75, p95. Additionally, compute "review wait time" (time from PR open to first review) separately, so cycle time can be decomposed into: `author_work_time ≈ cycle_time - first_review_lag` (rough proxy). |
| **Presentation** | Show distribution chart. Annotate p95 outliers with the specific PR(s) causing them, so the team can investigate root cause (usually a reviewer bottleneck or unclear requirements, not laziness). |

### A3. PR Size Distribution

| | |
|---|---|
| **Formula** | `additions + deletions` per PR, bucketed into S (< 100), M (100-400), L (400-1000), XL (> 1000) |
| **Data source** | `pr.additions`, `pr.deletions` |
| **What it measures** | How large PRs tend to be |
| **What it does NOT measure** | Complexity. A 500-line migration file is trivial to review; a 50-line concurrency fix is not. |
| **Bias risk** | Penalizes developers working on inherently large tasks (e.g., new module scaffolding, schema migrations). Penalizes devs who do valuable deletion/cleanup work (high deletions). |
| **Safeguard** | **Pair with review feedback density.** A large PR with zero review issues is fine. A small PR with many issues is concerning. Also **separate additions and deletions** in reporting — deletions are often net positive work. |
| **Presentation** | Histogram per developer. Team-level guideline: "We aim for most PRs to be M or smaller" is healthy. "Dev X has too many L PRs" without context is not. |

### A4. Net Code Change

| | |
|---|---|
| **Formula** | `total_additions - total_deletions` per developer per time window |
| **Data source** | `pr.additions`, `pr.deletions` |
| **What it measures** | Whether a developer is net adding or net removing code |
| **What it does NOT measure** | Value. More code is not better code. Especially in firmware. |
| **Bias risk** | Low, because this metric is explicitly NOT framed as "more is better." |
| **Safeguard** | Present as context, not as a score. A developer with net negative LOC might be doing the most valuable work on the team (removing dead code, simplifying). |
| **Presentation** | Show alongside PR count to provide context. Never rank by this. |

---

## B. Review Metrics

These measure the reviewing/unblocking side of development work.

### B1. Review Load

| | |
|---|---|
| **Formula** | `unique_prs_reviewed` + `review_comments_left` per developer per time window |
| **Data source** | Reviews endpoint: unique PRs where the developer submitted a review; review comments endpoint: count of inline comments |
| **What it measures** | Volume of review work a developer is doing |
| **What it does NOT measure** | Quality of reviews. A developer who rubber-stamps 20 PRs with "LGTM" has high volume but zero value. |
| **Bias risk** | Medium. Could incentivize high-volume, low-quality reviews if used as a KPI. |
| **Safeguard** | **Always pair with Review Depth (B2, LLM-powered)**. Volume without quality analysis is meaningless. |
| **Presentation** | Show alongside authoring metrics to make review work visible. The primary purpose is to prevent review work from being invisible, not to rank reviewers. |

### B2. Review Depth (LLM-powered)

| | |
|---|---|
| **Formula** | For each review comment, use LLM to classify into categories. Aggregate per reviewer. |
| **Categories** | `bug_catch` — identifies a functional defect or logic error |
| | `security` — flags a security vulnerability or risk |
| | `performance` — identifies performance or resource concern |
| | `architecture` — comments on design, structure, or abstraction |
| | `test_gap` — identifies missing or inadequate test coverage |
| | `style_nit` — formatting, naming, or minor convention issue |
| | `question` — asks for clarification, not asserting an issue |
| | `praise` — positive feedback on good work |
| **Data source** | Review comment `body` field |
| **What it measures** | What kind of value the reviewer contributes |
| **What it does NOT measure** | Whether the author acted on the feedback |
| **Bias risk** | LLM classification inconsistency — the same type of comment might be classified differently across reviewers. |
| **Safeguard** | Use structured prompts with examples for each category. Run calibration: classify a sample of comments manually, compare with LLM output, tune prompt until agreement > 85%. |
| **Presentation** | Per-reviewer breakdown: "Dev A's reviews: 40% bug catches, 30% architecture, 20% style, 10% questions." This shows the reviewer's strength profile. |

### B3. Review Turnaround

| | |
|---|---|
| **Formula** | `first_non_author_review.submitted_at - pr.created_at` |
| **Data source** | Reviews endpoint: earliest review from someone other than the PR author |
| **What it measures** | How long PRs wait before getting review attention |
| **What it does NOT measure** | Review quality. Fast review might mean rubber-stamping. |
| **Bias risk** | **High if attributed to individual reviewers.** A slow turnaround might mean the reviewer was deep in their own complex task, on PTO, or in a different timezone. |
| **Safeguard** | **Report as a team-level metric only.** "Median review turnaround this sprint was 4 hours" is useful. "Dev A takes 8 hours to review" is harmful without context. |
| **Presentation** | Team-level trend over time. If it's degrading, that's a staffing/process signal, not an individual performance issue. |

### B4. Review Rounds

| | |
|---|---|
| **Formula** | Count of distinct (reviewer, date) pairs on non-author reviews per PR |
| **Data source** | Reviews endpoint: `submitted_at` grouped by reviewer |
| **What it measures** | How much back-and-forth happens before a PR merges |
| **What it does NOT measure** | Whether the rounds were productive. One round of "changes requested" followed by "approved" is healthy. Five rounds of the same issue might indicate unclear feedback or an unresponsive author. |
| **Bias risk** | High rounds could mean: (a) thorough review culture (good), (b) unclear initial submission (author issue), or (c) nitpicky reviewer (reviewer issue). Ambiguous without context. |
| **Safeguard** | **Pair with LLM analysis of review comments across rounds.** Did later rounds address earlier feedback? Or were they new issues? |
| **Presentation** | Distribution across the team. "Average 1.5 rounds per PR" is a team characteristic. Flag outlier PRs (> 4 rounds) for retrospective discussion. |

---

## C. Collaboration Metrics

These measure how the team works together. They are inherently team-level and should never be used to rank individuals.

### C1. Knowledge Distribution (Bus Factor)

| | |
|---|---|
| **Formula** | For each directory (or module), count unique developers who have authored merged PRs touching files in it. |
| **Data source** | Files endpoint: `filename` field, grouped by directory prefix |
| **What it measures** | How many people know each part of the codebase |
| **Presentation** | Heatmap: directory × developer. Red = only 1 person has touched it. Green = 3+ people. This is a team risk metric, not an individual performance metric. |

### C2. Review Network

| | |
|---|---|
| **Formula** | Directed graph: edge from reviewer → author for each review submitted. Weight = number of reviews. |
| **Data source** | Reviews endpoint: `user.login` (reviewer) + PR `user.login` (author) |
| **What it measures** | Who reviews whose work. Reveals silos, bottlenecks, and gaps. |
| **Presentation** | Graph visualization. Flag patterns like: "Dev A reviews everyone but nobody reviews Dev A" or "Dev B and Dev C never interact." These are team structure signals. |

### C3. Review Coverage

| | |
|---|---|
| **Formula** | Percentage of merged PRs that received at least one non-bot, non-author review |
| **Data source** | Reviews endpoint: filter out bot reviewers and self-reviews |
| **What it measures** | Whether the team is actually reviewing each other's work |
| **Presentation** | Team-level percentage. "This sprint, 85% of PRs had at least one human review" is a process health metric. Flag PRs merged with zero human review for visibility. |

### C4. Discussion Activity

| | |
|---|---|
| **Formula** | Count of issue comments per PR, separated by author vs. others |
| **Data source** | Issue comments endpoint |
| **What it measures** | Level of discussion and collaboration on PRs |
| **Presentation** | Team average per PR. Low discussion isn't inherently bad (clear PRs need less discussion), but zero discussion on complex PRs might indicate insufficient review. |

---

## D. Code Quality Metrics (LLM-powered)

Detailed in [04-code-quality-analysis.md](04-code-quality-analysis.md). Summary:

| Metric | What LLM analyzes | Output |
|---|---|---|
| **Conciseness score** | PR diff for unnecessary abstraction, duplication, verbosity | 1-5 score + specific issues |
| **Self-review signal score** | PR diff for orphaned code, inconsistencies, TODOs, style clashes | 1-5 score + specific issues |
| **Firmware concern score** | PR diff for memory efficiency, code size, resource management | 1-5 score + specific issues |
| **Review comment classification** | Review comment bodies | Category per comment (bug, architecture, style, etc.) |

---

## E. Growth Metrics (LLM-powered)

These are the most valuable and least gameable metrics. They require data accumulated over multiple time windows.

### E1. Issue Category Trend

| | |
|---|---|
| **Formula** | For each developer, track the categories of review comments their PRs receive over time (using B2 classifications). Plot category distribution per month/sprint. |
| **What it measures** | Whether the types of issues found in a developer's code are changing over time. |
| **Example** | "In March, 60% of review feedback on Dev A's PRs was about error handling. In April, that dropped to 15% and the feedback shifted to architecture. This suggests Dev A internalized the error handling patterns and is now tackling higher-level concerns." |
| **Presentation** | Per-developer trend chart (shown to the developer, not the team). Narrative summary generated by LLM. |

### E2. Code Quality Trend

| | |
|---|---|
| **Formula** | Track D-metrics (conciseness, self-review signals) per developer over time. |
| **What it measures** | Whether code quality is improving, stable, or degrading. |
| **Presentation** | Trend line per developer. Highlight inflection points with context (e.g., "conciseness improved after sprint 12 — correlates with team discussion on coding standards"). |

### E3. Reviewer Growth

| | |
|---|---|
| **Formula** | Track B2 (review depth) categories per reviewer over time. |
| **What it measures** | Whether a reviewer's feedback is becoming more substantive over time. |
| **Example** | "Dev B's reviews shifted from 80% style nits in March to 50% architecture + 20% bug catches in April. Their review work is becoming more impactful." |

---

## Report Formats

### Team Health Report (for manager, weekly/sprint cadence)

```
Sprint 2026-W14 Team Health Report
===================================

DELIVERY
- 12 PRs merged across 4 developers
- Median cycle time: 6h (p75: 14h, p95: 28h)
  → p95 driven by PR #45, which waited 22h for review (holiday weekend)
- Size distribution: 7 small, 3 medium, 2 large
- Net code change: +1,200 / -400 (net +800 lines)

REVIEW HEALTH
- Review coverage: 10/12 PRs (83%) received human review
  → 2 unreviewed PRs were both config-only changes
- Median review turnaround: 3.2h
- Review work distribution: A (6 PRs), B (4 PRs), C (2 PRs), D (0 PRs)
  → D was on PTO this sprint

CODE QUALITY (LLM analysis)
- 3/12 PRs flagged for conciseness concerns
  → Common pattern: redundant error handling wrappers (appeared in 2 PRs)
- 1 PR flagged for potential resource leak (missing close() on file handle)
- 0 PRs flagged for firmware-specific concerns

COLLABORATION
- Knowledge distribution: payments module still single-owner (A only)
- New: C made first contribution to auth module this sprint

GROWTH HIGHLIGHTS
- B's PRs received 40% fewer review comments vs. last sprint
  (same PR complexity) — suggesting improved self-review
- A's review depth improved — more architecture-level feedback,
  fewer style nits compared to last month
```

### Individual Growth Report (for the developer only, monthly cadence)

```
Monthly Growth Report: Dev B — March 2026
==========================================

YOUR AUTHORING
- 8 PRs merged (team median: 6)
- Median cycle time: 5h (team median: 7h)
- Size: mostly small-medium, 1 large (PR #32, schema migration)

REVIEW FEEDBACK YOU RECEIVED
- 14 review comments across 8 PRs
- Categories: 5 style (36%), 4 architecture (29%), 3 bug (21%), 2 test gap (14%)
- Trend: style comments down from 55% last month → 36% this month ✓
- Recurring: architecture feedback on service layer boundaries (PRs #28, #32)
  → Consider reviewing the team's service layer conventions doc

YOUR CODE QUALITY
- Conciseness: 4.2/5 avg (up from 3.8 last month) ✓
- Self-review signals: 4.0/5 avg (stable)
- 1 PR flagged for unnecessary wrapper functions — review before submitting next time

YOUR REVIEW CONTRIBUTIONS
- Reviewed 5 PRs this month
- Your review depth: 40% bug catches, 35% architecture, 25% style
- Highlight: caught a race condition in PR #29 before it reached production
```

---

## Anti-gaming Properties

| Metric | Gaming attempt | Why it fails |
|---|---|---|
| PR count | Split work into trivially small PRs | Size distribution + LLM quality analysis catches thin PRs |
| Cycle time | Merge without review to look fast | Review coverage metric flags unreviewed merges |
| Lines of code | Write verbose code | LLM conciseness scoring penalizes verbosity |
| Review comment count | Leave many shallow "nit" comments | Review depth classification exposes nit-heavy reviewers |
| Review turnaround | Rubber-stamp approve quickly | Review depth shows empty reviews have no substance |
| Code quality score | Write minimal code to avoid LLM flags | Paired with delivery metrics — shipping nothing also shows up |
