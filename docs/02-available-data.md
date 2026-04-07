# Available Data from GitHub API

This document catalogs every field we confirmed is available through the GitHub REST API using a Fine-grained Personal Access Token (PAT), based on hands-on exploration against a real repository.

## Authentication & Rate Limits

| Method | Rate limit | Notes |
|---|---|---|
| Fine-grained PAT | 5,000 req/hour | Recommended. Requires: Pull requests (read), Contents (read), Metadata (read) |
| Classic PAT | 5,000 req/hour | Requires `repo` scope only |
| GitHub App | 15,000 req/hour | Needed only at scale; also grants Checks permission (unavailable on fine-grained PATs) |
| Unauthenticated | 60 req/hour | Not viable |

**Cost estimate:** Each PR requires ~4 API calls (PR detail + reviews + review comments + issue comments). Fetching diff patches adds ~1 call per PR. At 5 calls/PR, a 5,000 req/hour budget supports ~1,000 PRs per run.

## Endpoints Used

### 1. Pull Request Detail

**Endpoint:** `GET /repos/{owner}/{repo}/pulls/{pull_number}`

Must fetch individually — the list endpoint (`GET /repos/{owner}/{repo}/pulls`) omits key fields like `merged`, `additions`, `deletions`, `changed_files`.

| Field | Type | Description | Metric relevance |
|---|---|---|---|
| `number` | int | PR number | Identifier |
| `title` | string | PR title | LLM: description quality analysis |
| `body` | string | PR description (markdown) | LLM: description quality, scope clarity |
| `state` | string | `open` / `closed` | Delivery metrics |
| `merged` | bool | Whether the PR was merged | Merge rate calculation |
| `draft` | bool | Whether it was a draft PR | Filter out WIP from metrics |
| `user.login` | string | Author's GitHub username | Per-developer attribution |
| `author_association` | string | `OWNER` / `MEMBER` / `CONTRIBUTOR` / `NONE` | Context for external contributors |
| `created_at` | datetime | When the PR was opened | Cycle time start |
| `merged_at` | datetime | When the PR was merged | Cycle time end |
| `closed_at` | datetime | When the PR was closed (merged or not) | Closed-unmerged detection |
| `updated_at` | datetime | Last activity on the PR | Staleness detection |
| `base.ref` | string | Target branch (e.g., `main`) | Filter by branch policy |
| `head.ref` | string | Source branch name | Dedup reopened PRs (same branch = same work) |
| `head.sha` | string | Head commit SHA | Link to check runs (if accessible) |
| `additions` | int | Lines added | PR size metrics |
| `deletions` | int | Lines removed | PR size metrics |
| `changed_files` | int | Number of files modified | PR size metrics |
| `commits` | int | Number of commits in the PR | Commit density metrics |
| `comments` | int | Count of issue-style comments | Discussion activity |
| `review_comments` | int | Count of inline review comments | Review depth indicator |
| `labels` | array | Label names | Categorization (bug, feature, etc.) |
| `milestone` | object/null | Associated milestone | Sprint/release tracking |
| `requested_reviewers` | array | Users requested for review | Review assignment tracking |
| `assignees` | array | Assigned users | Responsibility tracking |

### 2. Reviews

**Endpoint:** `GET /repos/{owner}/{repo}/pulls/{pull_number}/reviews`

| Field | Type | Description | Metric relevance |
|---|---|---|---|
| `user.login` | string | Reviewer username | Review attribution |
| `state` | string | `APPROVED` / `CHANGES_REQUESTED` / `COMMENTED` / `DISMISSED` | Review outcome |
| `submitted_at` | datetime | When the review was submitted | Review turnaround, review rounds |
| `body` | string | Top-level review comment | LLM: review quality analysis |

**Key observation:** A reviewer can submit multiple reviews on the same PR (e.g., first `CHANGES_REQUESTED`, then `APPROVED` after fixes). Each is a separate entry. This enables tracking review rounds.

### 3. Review Comments (Inline)

**Endpoint:** `GET /repos/{owner}/{repo}/pulls/{pull_number}/comments`

| Field | Type | Description | Metric relevance |
|---|---|---|---|
| `user.login` | string | Comment author | Review attribution |
| `path` | string | File path the comment is on | Which files draw the most review feedback |
| `line` | int/null | Line number in the diff | Specificity of feedback |
| `body` | string | Comment text (markdown) | LLM: classify comment type (bug, style, architecture, etc.) |
| `created_at` | datetime | When comment was posted | Timeline reconstruction |

**Key observation:** These are the richest data for LLM analysis. Comment bodies contain specific technical feedback, suggested code changes, and reasoning. In our test repo, Copilot bot left detailed comments with code suggestions — real human reviewers would produce similar data.

### 4. Issue Comments (Discussion)

**Endpoint:** `GET /repos/{owner}/{repo}/issues/{pull_number}/comments`

| Field | Type | Description | Metric relevance |
|---|---|---|---|
| `user.login` | string | Comment author | Discussion attribution |
| `body` | string | Comment text | LLM: mentoring signals, decision context |
| `created_at` | datetime | When posted | Timeline |

**Key observation:** In many teams, the real human review feedback lives here (not in formal reviews). In our test repo, the tech lead's approval messages with detailed feedback were all issue comments, not formal review submissions.

### 5. Files Changed

**Endpoint:** `GET /repos/{owner}/{repo}/pulls/{pull_number}/files`

| Field | Type | Description | Metric relevance |
|---|---|---|---|
| `filename` | string | File path | Knowledge distribution, scope analysis |
| `status` | string | `added` / `modified` / `removed` / `renamed` | Type of change |
| `additions` | int | Lines added in this file | Per-file size |
| `deletions` | int | Lines removed in this file | Per-file size |
| `patch` | string | Unified diff content | **LLM: code quality analysis on actual code changes** |

**Key observation:** The `patch` field is critical — it contains the actual diff (added/removed lines with context). This is what enables LLM-powered code quality review. For very large files, this field may be truncated or absent; the API returns files up to ~300 KB of diff content per file.

### 6. PR Commits

**Endpoint:** `GET /repos/{owner}/{repo}/pulls/{pull_number}/commits`

| Field | Type | Description | Metric relevance |
|---|---|---|---|
| `sha` | string | Commit hash | Identification |
| `author.login` | string | GitHub user who authored | Co-authorship detection |
| `commit.author.name` | string | Git author name | Fallback when GitHub user is null |
| `commit.message` | string | Commit message | LLM: commit message quality |
| `commit.author.date` | datetime | When committed | Work pattern analysis |

### 7. Check Runs (CI Status)

**Endpoint:** `GET /repos/{owner}/{repo}/commits/{ref}/check-runs`

| Field | Type | Description | Metric relevance |
|---|---|---|---|
| `name` | string | Check name (e.g., "CI / test") | CI identification |
| `status` | string | `queued` / `in_progress` / `completed` | CI state |
| `conclusion` | string | `success` / `failure` / `neutral` / etc. | CI pass rate per developer |

**⚠️ Limitation:** The Checks permission is **not available** on fine-grained PATs (GitHub disabled it). This endpoint returns 403. To access CI data, you need either a Classic PAT with `repo` scope, or a GitHub App token. For the initial version of this tool, CI data is excluded.

## Data NOT Available from GitHub API

| Data point | Why it matters | Alternative |
|---|---|---|
| Time spent coding | Would measure actual effort | Not possible — no proxy is reliable |
| Who actually read the diff | "Approved" doesn't mean "reviewed" | LLM analysis of review comment quality as proxy |
| IDE telemetry / AI tool usage | Manager wants this but it's invasive | Detect code quality instead (see [04-code-quality-analysis.md](04-code-quality-analysis.md)) |
| Private messages / Slack context | Often explains why a PR was slow | Out of scope — too invasive |
| Branch protection bypass | Whether someone merged without required reviews | Available via audit log (GitHub Enterprise only) |

## Data Collection Architecture

```
                    ┌──────────────────────────────────────────────┐
                    │              GitHub REST API                  │
                    └──────────┬───────────────────────────────────┘
                               │
                    ┌──────────▼───────────────────────────────────┐
                    │         Data Collection Layer                 │
                    │                                               │
                    │  1. List PRs (paginated, filtered by date)    │
                    │  2. For each PR:                              │
                    │     a. Fetch full PR detail                   │
                    │     b. Fetch reviews                          │
                    │     c. Fetch review comments                  │
                    │     d. Fetch issue comments                   │
                    │     e. Fetch files with patches               │
                    │  3. Rate limit handling (sleep on 403)        │
                    │  4. Dedup reopened PRs (same head branch)     │
                    │                                               │
                    └──────────┬───────────────────────────────────┘
                               │
                    ┌──────────▼───────────────────────────────────┐
                    │            Raw Data Store                     │
                    │                                               │
                    │  pr_raw.json     — Full PR data + diffs       │
                    │  pr_summary.json — Aggregated per-dev stats   │
                    │                                               │
                    └──────────┬───────────────────────────────────┘
                               │
              ┌────────────────┼────────────────┐
              ▼                ▼                ▼
     Quantitative       LLM Quality       LLM Qualitative
     Metrics Engine     Analysis           Analysis
     (03-metrics)       (04-quality)       (03-metrics)
              │                │                │
              └────────────────┼────────────────┘
                               ▼
                    ┌──────────────────────────────────────────────┐
                    │         Report Generation                    │
                    │                                               │
                    │  Team health report (for manager)             │
                    │  Individual growth report (for developer)     │
                    │                                               │
                    └──────────────────────────────────────────────┘
```
