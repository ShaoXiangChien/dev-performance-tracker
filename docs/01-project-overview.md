# Developer Performance Tracker — Project Overview

## Problem Statement

Engineering managers need visibility into team performance and health, but most available tools reduce developers to leaderboards and vanity metrics (lines of code, PR count, commit frequency). These metrics are easily gamed, context-free, and often punish the wrong behaviors.

Specific pain points this tool aims to address:

1. **No visibility into reviewer contribution.** Managers who only see "PRs authored" undervalue senior devs who spend significant time reviewing, mentoring, and unblocking others.
2. **AI-assisted code without self-review.** Developers increasingly use AI coding tools, which is encouraged. However, AI-generated code is often verbose, over-abstracted, and not tailored to project conventions. In firmware environments, this directly translates to unnecessary system overhead — even if the code "works."
3. **Lack of growth tracking.** Managers see snapshots, not trajectories. There is no easy way to see whether a developer is improving in specific areas over time.
4. **Biased metrics cause harm.** A cycle time metric without context blames the author for slow reviews. A PR count metric penalizes someone doing careful, complex work. The tool must avoid producing ammunition for micromanagement.

## Design Principles

### 1. Context over numbers

Every metric must be presented with the context needed to interpret it correctly. A number without context is a weapon.

- Cycle time must distinguish "author working" from "waiting for review."
- PR size must be paired with complexity and review feedback.
- Individual metrics must be viewable against team baseline, not ranked.

### 2. Team health over individual ranking

The primary output is team health signals, not developer rankings. Individual data exists to support growth conversations between a developer and their lead — not for stack-ranking.

### 3. Reviewers are first-class contributors

Review work is measured with the same rigor as authoring work. The tool should make it impossible to overlook someone who spends 40% of their time unblocking teammates through reviews.

### 4. Non-gameable by design

If a metric can be improved by doing something that doesn't actually help the team, it's a bad metric. Examples of what we deliberately avoid:

- Counting PRs (incentivizes splitting trivially)
- Counting lines of code (incentivizes verbosity)
- Counting commits (incentivizes noisy git history)
- Counting review comments (incentivizes nitpicking)

### 5. Detect quality, not tools

The code quality analysis detects whether submitted code meets quality standards — not whether it was written by a human or an AI. Policing tool usage destroys trust. Measuring output quality drives the right behavior regardless of how the code was produced.

## Data Source

All data is sourced from the GitHub REST API via Pull Request endpoints. See [02-available-data.md](02-available-data.md) for the full inventory of fields confirmed through API exploration.

## Key Components

| Component | Purpose | Document |
|---|---|---|
| Data collection | Fetch PR data, reviews, comments, diffs from GitHub API | [02-available-data.md](02-available-data.md) |
| Quantitative metrics | Compute delivery, review, and collaboration metrics | [03-metrics-design.md](03-metrics-design.md) |
| LLM code quality analysis | Analyze PR diffs for conciseness, self-review signals, firmware concerns | [04-code-quality-analysis.md](04-code-quality-analysis.md) |
| Reporting | Generate team health reports and individual growth summaries | [03-metrics-design.md](03-metrics-design.md) |
| Implementation plan | Phases, architecture, dependencies | [05-implementation-plan.md](05-implementation-plan.md) |
