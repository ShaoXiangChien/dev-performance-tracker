# Developer Performance Tracker

A Streamlit demo app that turns GitHub PR data into actionable team health insights — without weaponizing metrics against individual developers.

Built for firmware/embedded teams. Uses GitHub's REST API for quantitative metrics and Claude (Anthropic) for LLM-powered analysis.

---

## What it does

The app walks through a 4-step pipeline, each step on its own screen:

| Step | What happens | Output |
|---|---|---|
| **1. Data Collection** | Fetch PR data from GitHub API (or upload a saved file) | `data/pr_raw.json` |
| **2. Process Data** | Compute cycle time, PR size, review load, collaboration network | `data/metrics.json` |
| **3. LLM Analysis** | Classify review comments; score code quality (needs diffs) | `data/llm_analysis.json` |
| **4. Reports** | Generate team health and individual growth reports | `data/reports/*.md` |

Each step saves its output and can reload from a previous run — no need to re-run expensive steps for every demo.

---

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env`:

```env
# Required for Step 1 (Data Collection)
GITHUB_TOKEN=ghp_your_token_here     # Read-only PAT is sufficient
GITHUB_REPO=owner/repo-name          # e.g. myorg/firmware

# Required for Step 3 (LLM Analysis)
OPENROUTER_API_KEY=sk-or-v1-your_key_here
```

Get a free OpenRouter key at https://openrouter.ai/keys — no credit card required for free-tier models.

The app also accepts these values directly in the UI — the `.env` values just pre-fill the input fields.

### 3. Run

```bash
streamlit run app.py
```

---

## GitHub Token permissions

A **read-only** Personal Access Token is sufficient. Required scopes:

- `repo` (for private repos) — or `public_repo` for public repos only

The token is used to call:
- `GET /repos/{owner}/{repo}/pulls`
- `GET /repos/{owner}/{repo}/pulls/{number}/reviews`
- `GET /repos/{owner}/{repo}/pulls/{number}/comments`
- `GET /repos/{owner}/{repo}/issues/{number}/comments`
- `GET /repos/{owner}/{repo}/pulls/{number}/files` *(only when "Include diffs" is checked)*

Rate limit: 5,000 requests/hour for authenticated PATs — enough for ~1,000 PRs per run.

---

## LLM Analysis

Step 3 uses [OpenRouter](https://openrouter.ai) (free-tier models) to:

- **Classify review comments** into 8 categories: `bug_catch`, `security`, `performance`, `architecture`, `test_gap`, `style`, `question`, `praise`
- **Score code quality** across 3 dimensions (requires diff patches):
  - **Conciseness** — detects bloated, over-engineered, or AI-generated-and-not-reviewed code
  - **Self-review signal** — flags signs the author didn't review before submitting
  - **Firmware concerns** — heap allocation, resource leaks, busy-waits, non-atomic shared state

**Available free models (selectable in the UI):**

| Model ID | Strengths |
|---|---|
| `qwen/qwen3.6-plus:free` | SOTA coding, 1M context |
| `deepseek/deepseek-r1:free` | Strong reasoning |
| `google/gemma-3-27b-it:free` | Fast, reliable |
| `meta-llama/llama-3.3-70b-instruct:free` | General purpose |

> **Note:** `pr_raw.json` does **not** include diff patches by default. To enable code quality scoring, go to Step 1 and check **"Include diff patches"** before fetching. This doubles the API calls per PR (~2x rate limit usage).

**Cost:** Free-tier models have no cost. Free tier allows 20 requests/min and 50 requests/day (1,000/day with any paid credits on the account).

---

## Project structure

```
dev-performance-tracker/
├── app.py                  # Streamlit UI entry point
├── pipeline/
│   ├── collector.py        # GitHub API data collection
│   ├── metrics.py          # Quantitative metrics computation
│   ├── llm_analysis.py     # Claude API analysis
│   └── reports.py          # Markdown report generation
├── prompts/                # LLM prompt templates
│   ├── review_classification.txt
│   ├── conciseness.txt
│   ├── self_review.txt
│   └── firmware_concerns.txt
├── data/                   # Runtime outputs (not committed)
│   ├── pr_raw.json
│   ├── metrics.json
│   ├── llm_analysis.json
│   └── reports/
├── docs/                   # Design documentation
│   ├── 01-project-overview.md
│   ├── 02-available-data.md
│   ├── 03-metrics-design.md
│   ├── 04-code-quality-analysis.md
│   └── 05-implementation-plan.md
├── collect_pr_data.py      # Original standalone collector (still works)
├── requirements.txt
└── .env.example
```

---

## Design principles

This tool is intentionally designed to **resist misuse**:

- Every metric is shown with context — no raw numbers without interpretation
- Cycle time is always shown as a **distribution** (p50/p75/p95), never a single average
- Review turnaround is **team-level only** — not attributed to individual reviewers
- Individual reports go to **the developer**, not the manager
- Bots (GitHub Copilot, etc.) are automatically excluded from all team metrics

See [`docs/01-project-overview.md`](docs/01-project-overview.md) for the full design rationale.
