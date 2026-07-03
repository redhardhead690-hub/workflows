# Management Research Digest

An automated agent that periodically collects new articles from the top
academic management journals, summarizes each one with Claude (in plain
language, with a "why it matters for practice" note), and emails you the
digest. Each article title links to the full paper.

It runs for free on GitHub Actions — no server to maintain.

## Journals tracked
Ordered by relevance for organizational consulting / leadership development.
Edit the `FEEDS` list in `weekly_digest.py` to add, remove, or reorder.

1. Academy of Management Journal
2. The Leadership Quarterly
3. Journal of Applied Psychology
4. Academy of Management Review
5. Organization Science
6. Journal of Organizational Behavior
7. Strategic Management Journal
8. Administrative Science Quarterly
9. Journal of Management
10. Personnel Psychology

---

## What you'll need (all free)
1. A **GitHub** account
2. An **Anthropic API key** — https://console.anthropic.com (add a little credit; a run costs a few cents)
3. A **Gmail** account to send from (can be the same address that receives it)

---

## Setup — about 15 minutes

### 1. Put the files in a GitHub repo
Create a new repository and add these files, keeping the folder layout:
```
weekly_digest.py
requirements.txt
.github/workflows/weekly-digest.yml
```

### 2. Get your Anthropic API key
Anthropic Console -> API Keys -> create a key. Copy it (starts with `sk-ant-`).

### 3. Create a Gmail "app password"
Normal Gmail passwords don't work for scripts. Instead:
- Turn on 2-Step Verification (Google Account -> Security).
- Go to https://myaccount.google.com/apppasswords, create one, copy the 16-character code.

### 4. Add three secrets to GitHub
Repo -> Settings -> Secrets and variables -> Actions -> New repository secret:

| Name | Value |
|------|-------|
| `ANTHROPIC_API_KEY` | your `sk-ant-...` key |
| `GMAIL_ADDRESS` | the sending Gmail address |
| `GMAIL_APP_PASSWORD` | the 16-character app password (no spaces) |

### 5. Test it
Actions tab -> Management Research Digest -> Run workflow. In a minute or two
the digest lands in your inbox. Check the run log if it doesn't.

After that it runs automatically on the schedule.

---

## Important: these journals publish slowly
Unlike news sites, academic journals release new issues monthly to quarterly.
So in any given 7-day window several journals will have nothing new, and some
weeks may be quiet overall. That's expected. Two ways to handle it:

- **Keep it weekly** (default). You'll always get an email; on quiet weeks it
  simply says there's nothing new, so you know the agent is alive.
- **Run less often** (recommended for these sources): switch to every two
  weeks or monthly so each digest is fuller.

**To change the frequency, edit two things so they match:**
1. The `cron` line in `.github/workflows/weekly-digest.yml`
   - Weekly (Sundays): `0 7 * * 0`
   - Monthly (1st of month): `0 7 1 * *`
2. `DAYS_BACK` in `weekly_digest.py` — set it to the same interval
   (7 for weekly, 31 for monthly). Keeping these equal prevents the same
   article from appearing in two digests.

The schedule time is in **UTC**. Israel is UTC+3 in summer, UTC+2 in winter,
so `0 7` = 09:00–10:00 Israel time.

---

## Customizing
- **Change journals:** edit the `FEEDS` list in `weekly_digest.py`.
- **Lower the cost:** set `CLAUDE_MODEL` to `"claude-haiku-4-5"` (cheapest) or `"claude-sonnet-5"`.
- **More/fewer articles per journal:** change `MAX_PER_FEED`.

## If a feed ever stops working
Publisher feed URLs occasionally change. The script just skips a dead feed, so
one bad URL won't break the digest. To check a feed, paste its URL into a
browser — a working feed shows XML. The two most likely to need attention are
The Leadership Quarterly (ScienceDirect) and Journal of Applied Psychology
(APA), since those platforms change their feeds more often. If one dies, an
RSS generator such as RSS.app or Feedspot can rebuild a feed from the journal's
"latest articles" page.

## Notes
- Summaries are written by Claude from each journal's public RSS abstract/TOC entry; titles link to the full paper (often paywalled).
- Everything runs on GitHub's servers on schedule; your machine doesn't need to be on.
