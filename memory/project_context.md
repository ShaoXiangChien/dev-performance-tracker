---
name: project-context
description: Dev performance tracker is an experimental tool for user's company manager (a micromanager). Goal is to provide non-biased, growth-oriented metrics from GitHub PR data — must not harm developers. Reviewers matter as much as implementers.
type: project
---

Building a developer performance tracking tool using GitHub PR API data.

**Why:** User's company manager requested it — manager is a micromanager. User wants to protect developers by providing genuinely useful, non-biased metrics that reflect real performance and team health, rather than punitive or misleading indicators.

**How to apply:** Every metric proposed must pass the "could this be weaponized against a developer unfairly?" test. Prioritize team growth signals over individual ranking. Reviewer contribution is equally important as authoring.

**Team context:** Firmware department. Manager's specific pain point: devs use AI-assisted coding (which is fine) but often submit code that's bloated/not concise — they don't properly self-review AI output. In firmware, bloated code that "works" still causes system overhead. Need LLM-based code quality analysis as part of the tool.
