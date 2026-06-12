# Weekly Weak Signal Summary

Sends a Friday 6 AM email with 3 AI-generated weak signals across:
- Software architecture patterns
- Canadian banking regulation (OSFI, Open Banking)
- AI's impact on developer teams

Powered by **Claude** (with native web search) + **Gmail API** + **GitHub Actions**.

---

## Folder Structure

```
your-repo/
├── .github/
│   └── workflows/
│       └── weekly_summary.yml   ← GitHub Actions scheduler
├── weekly_summary.py            ← Main script
├── setup_gmail_token.py         ← One-time local setup
├── requirements.txt
└── README.md
```

---

## Setup (one-time, ~15 minutes)

### Step 1 — Google Cloud / Gmail API

1. Go to [https://console.cloud.google.com](https://console.cloud.google.com)
2. Create a new project (e.g. `weekly-summary`)
3. Enable the **Gmail API** (APIs & Services → Enable APIs → search Gmail)
4. Configure **OAuth consent screen**:
   - User type: External
   - Add your Gmail address as a **Test user**
5. Create **Credentials** → OAuth 2.0 Client ID → **Desktop app**
6. Download the JSON → rename it `credentials.json`, place in this folder

### Step 2 — Generate Gmail token locally

```bash
pip install google-auth-oauthlib
python setup_gmail_token.py
```

A browser window opens → sign in → grant permission.
The script prints a long base64 string — **copy it**.

### Step 3 — GitHub repo secrets

In your GitHub repo → Settings → Secrets and variables → Actions → New secret:

| Secret name | Value |
|---|---|
| `ANTHROPIC_API_KEY` | Your Anthropic API key |
| `GOOGLE_TOKEN_JSON` | The base64 string from Step 2 |
| `RECIPIENT_EMAIL` | Your Gmail address |

### Step 4 — Push to GitHub

```bash
git init  # if not already a repo
git add .
git commit -m "Add weekly summary workflow"
git push origin main
```

The workflow runs automatically every **Friday at 10:00 UTC (6 AM EDT)**.

---

## Testing manually

In GitHub → Actions tab → "Weekly Weak Signal Summary" → **Run workflow**.

Or run locally:

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
export RECIPIENT_EMAIL=you@gmail.com
export GOOGLE_TOKEN_JSON=$(base64 -i token.json)
python weekly_summary.py
```

---

## DST note

GitHub Actions cron runs in UTC and doesn't adjust for DST.
- **Summer (EDT, Apr–Oct):** 10:00 UTC = 6:00 AM ✅
- **Winter (EST, Nov–Mar):** 10:00 UTC = 5:00 AM ⚠️

To fix winter timing, update the cron in `weekly_summary.yml` to `0 11 * * 5` from November through March (or just accept the 1-hour drift).

---

## Customising the prompt

Edit `SYSTEM_PROMPT` and `USER_PROMPT` in `weekly_summary.py`.
The `max_uses` parameter on the web search tool controls how many searches Claude makes per run (default: 8).
