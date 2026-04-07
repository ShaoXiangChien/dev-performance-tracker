# Setup

## 1. Get a GitHub Personal Access Token

1. Go to https://github.com/settings/tokens?type=beta  (Fine-grained tokens — recommended)
2. Click **"Generate new token"**
3. Set:
   - **Token name**: anything, e.g. `dev-perf-tracker`
   - **Expiration**: 90 days (or whatever you need)
   - **Repository access**: select the specific repo(s) you want to analyse
   - **Permissions** → Repository permissions:
     - `Pull requests` → **Read-only**
     - `Contents` → **Read-only** (needed by some endpoints)
     - `Metadata` → **Read-only** (auto-selected)
4. Click **Generate token** and copy it immediately (you won't see it again)

> Classic tokens also work. If you use one, you only need the `repo` scope.

## 2. Configure .env

```bash
cp .env.example .env
```

Edit `.env`:
```
GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx
GITHUB_REPO=your-org/your-repo
```

## 3. Install dependencies

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## 4. Run the scripts in order

```bash
# Check credentials and rate limit budget
python explore_rate_limits.py

# Inspect what a single PR looks like
python explore_pr_fields.py

# Collect metrics across many PRs (default: last 90 days, up to 200 PRs)
python collect_pr_data.py

# Narrow the window or limit if you hit rate limits
python collect_pr_data.py --days 30 --limit 50
```

`collect_pr_data.py` writes `pr_data_summary.json` with the full per-developer table.

## Rate limit notes

- Unauthenticated: 60 req/hour (not enough)
- Personal Access Token: **5,000 req/hour**
- GitHub App token: 15,000 req/hour (if you ever need more scale)

Each PR costs ~3 API calls, so 5,000 req ≈ 1,600 PRs per hour.
