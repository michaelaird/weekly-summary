# Weekly Weak Signal Summary

Sends a Friday 6 AM email with 3 AI-generated weak signals across:
- Software architecture patterns
- Canadian banking regulation (OSFI, Open Banking)
- AI's impact on developer teams

Powered by **Claude** (with native web search) + **Gmail SMTP with App Password** + **GitHub Actions**.

---

## Folder Structure

```
your-repo/
├── .github/
│   └── workflows/
│       └── weekly_summary.yml   ← GitHub Actions scheduler
├── weekly_summary.py            ← Main script
├── requirements.txt
├── README.md
└── setup_gmail_token.py         ← Deprecated historical reference
```

---

## Setup (one-time, ~10 minutes)

### Step 1 — Create a Gmail App Password

1. Open your Gmail account
2. Turn on **2-Step Verification**
3. Go to Google Account → Security → App passwords
4. Create an app password for **Mail**
5. Copy the 16-character password

### Step 2 — GitHub repo secrets

In your GitHub repo → Settings → Secrets and variables → Actions → New secret:

| Secret name | Value |
|---|---|
| `ANTHROPIC_API_KEY` | Your Anthropic API key |
| `GMAIL_USERNAME` | Your Gmail address (for example `you@gmail.com`) |
| `GMAIL_APP_PASSWORD` | The 16-character Gmail app password |
| `TO_EMAIL` | The recipient email address |
| `CC_EMAIL` | Optional CC recipient email |

### Step 3 — Push to GitHub

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
export GMAIL_USERNAME=you@gmail.com
export GMAIL_APP_PASSWORD=abcd-efgh-ijkl-mnop
export TO_EMAIL=you@gmail.com
export CC_EMAIL=team@example.com
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
