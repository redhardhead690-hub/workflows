#!/usr/bin/env python3
"""
Weekly management-journal digest.

Pulls the past week's articles from a set of RSS feeds, asks Claude to
summarize them, and emails the result. Built to run once a week via
GitHub Actions (or any cron scheduler).
"""

import os
import re
import smtplib
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import feedparser
from anthropic import Anthropic

# ---------------------------------------------------------------------------
# CONFIG  — the only part you normally edit
# ---------------------------------------------------------------------------

# The top academic management journals, ordered by relevance for
# organizational consulting / leadership development. Comment out any line
# (add a #) to drop a journal, or paste a new feed URL to add one.
FEEDS = {
    "Academy of Management Journal":      "https://journals.aom.org/action/showFeed?type=etoc&feed=rss&jc=amj",
    "Leadership Quarterly":               "https://rss.sciencedirect.com/publication/science/10489843",
    "Journal of Applied Psychology":      "https://psycnet.apa.org/journals/apl.rss",
    "Academy of Management Review":       "https://journals.aom.org/action/showFeed?type=etoc&feed=rss&jc=amr",
    "Organization Science":               "https://pubsonline.informs.org/action/showFeed?type=etoc&feed=rss&jc=orsc",
    "Journal of Organizational Behavior": "https://onlinelibrary.wiley.com/feed/10991379/most-recent",
    "Strategic Management Journal":       "https://onlinelibrary.wiley.com/feed/10970266/most-recent",
    "Administrative Science Quarterly":   "https://journals.sagepub.com/action/showFeed?ui=0&mi=ehikzz&ai=2b4&jc=asqa&type=etoc&feed=rss",
    "Journal of Management":              "https://journals.sagepub.com/action/showFeed?ui=0&mi=ehikzz&ai=2b4&jc=joma&type=etoc&feed=rss",
    "Personnel Psychology":              "https://onlinelibrary.wiley.com/feed/17446570/most-recent",
}

# Map each journal to a "school" (אסכולה). The digest is grouped by these.
# To move a journal to a different school, just edit this dict.
SCHOOLS = {
    "אסכולת התיאוריה (Theory)": [
        "Academy of Management Review",
    ],
    "אסכולת המחקר האמפירי (Empirical Research)": [
        "Academy of Management Journal",
        "Journal of Management",
    ],
    "אסכולת הארגון כמערכת חברתית (Organization as Social System)": [
        "Administrative Science Quarterly",
        "Organization Science",
    ],
    "אסכולת האסטרטגיה (Strategy)": [
        "Strategic Management Journal",
    ],
    "אסכולת הפסיכולוגיה הארגונית (Organizational Psychology)": [
        "Journal of Applied Psychology",
        "Personnel Psychology",
        "Journal of Organizational Behavior",
    ],
    "אסכולת המנהיגות (Leadership)": [
        "Leadership Quarterly",
    ],
}

RECIPIENT     = "yossi.tali@gmail.com"   # where the digest is sent
DAYS_BACK     = 7                        # look-back window; keep equal to how
                                         # often the job runs (see README)
MAX_PER_FEED  = 8                        # cap articles per journal
CLAUDE_MODEL  = "claude-opus-4-8"        # -> "claude-haiku-4-5" or
                                         #    "claude-sonnet-5" to cut cost

# ---------------------------------------------------------------------------
# SECRETS — supplied as environment variables (see README)
# ---------------------------------------------------------------------------

ANTHROPIC_API_KEY  = os.environ["ANTHROPIC_API_KEY"].strip()
GMAIL_ADDRESS      = os.environ["GMAIL_ADDRESS"].strip()           # sending Gmail
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"].replace(" ", "").strip()  # 16-char app password


def _clean(html: str) -> str:
    """Strip HTML tags from an RSS summary and trim it."""
    text = re.sub(r"<[^>]+>", " ", html or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:600]


def collect_articles() -> dict:
    """Fetch recent entries from each feed."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=DAYS_BACK)
    by_journal = {}

    for name, url in FEEDS.items():
        # A browser-like agent avoids 403s from some publisher feeds.
        feed = feedparser.parse(url, agent="Mozilla/5.0 (weekly-digest-bot)")
        items = []
        for entry in feed.entries:
            stamp = entry.get("published_parsed") or entry.get("updated_parsed")
            pub_dt = datetime(*stamp[:6], tzinfo=timezone.utc) if stamp else None
            if pub_dt and pub_dt < cutoff:
                continue

            items.append({
                "title":   entry.get("title", "(untitled)"),
                "link":    entry.get("link", ""),
                "date":    pub_dt.strftime("%Y-%m-%d") if pub_dt else "",
                "excerpt": _clean(entry.get("summary", "") or entry.get("description", "")),
            })
            if len(items) >= MAX_PER_FEED:
                break
        by_journal[name] = items

    return by_journal


def build_prompt(by_journal: dict):
    """Group articles by school, then build a prompt. Returns (prompt, has_content)."""
    header = (
        "You are preparing an email digest of recent peer-reviewed articles "
        "from top academic management journals, for a reader who works in "
        "organizational consulting and leadership development.\n\n"
        "The articles below are already grouped into six academic 'schools' "
        "(אסכולות). KEEP THIS GROUPING in your output — use the school name "
        "as an <h2> heading (keep both the Hebrew and English). Under each "
        "school, list the articles. For each article give:\n"
        "- The journal name in parentheses after the title\n"
        "- A 1-2 sentence plain-language summary of the finding in your own "
        "words (do not copy the abstract)\n"
        "- A short italic 'Why it matters for practice' note\n\n"
        "Skip schools that have no new articles this period. Keep it "
        "skimmable. Finish with a single-line 'Theme of the period' if you "
        "notice a common thread across schools.\n\n"
        "Return clean HTML using only <h2>, <h3>, <p>, <ul>, <li>, <em>, and "
        "<a> tags (no <html>/<body> wrapper). Make each article title a link "
        "to its URL.\n\nArticles by school:\n"
    )

    lines, has_content = [header], False
    for school, journals in SCHOOLS.items():
        school_items = []
        for journal in journals:
            for it in by_journal.get(journal, []):
                it_with_journal = {**it, "journal": journal}
                school_items.append(it_with_journal)

        lines.append(f"\n## {school}")
        if not school_items:
            lines.append("(no new articles this period)")
            continue
        for it in school_items:
            has_content = True
            lines.append(
                f"- TITLE: {it['title']}\n"
                f"  JOURNAL: {it['journal']}\n"
                f"  DATE: {it['date']}\n"
                f"  URL: {it['link']}\n"
                f"  EXCERPT: {it['excerpt']}"
            )
    return "\n".join(lines), has_content


def summarize(prompt: str) -> str:
    client = Anthropic(api_key=ANTHROPIC_API_KEY)
    resp = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=2500,
        messages=[{"role": "user", "content": prompt}],
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError("The model declined to respond to this batch.")
    return "".join(b.text for b in resp.content if b.type == "text")


def send_email(html_body: str) -> None:
    today = datetime.now().strftime("%b %d, %Y")
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Management Research Digest \u2014 {today}"
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = RECIPIENT

    full_html = f"""<html><body style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;
max-width:640px;margin:auto;color:#1a1a1a;line-height:1.5;">
  <h1 style="font-size:20px;">Management Research Digest</h1>
  {html_body}
  <hr style="border:none;border-top:1px solid #eee;margin:24px 0;">
  <p style="font-size:12px;color:#888;">Generated automatically. Summaries by
  Claude; tap any title to read the full article.</p>
</body></html>"""

    msg.attach(MIMEText(full_html, "html"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        server.send_message(msg)


def main() -> None:
    by_journal = collect_articles()
    prompt, has_content = build_prompt(by_journal)
    body = summarize(prompt) if has_content else (
        f"<p>No new articles from your journals in the past {DAYS_BACK} days. "
        "These journals publish slowly, so quiet periods are normal.</p>"
    )
    send_email(body)
    print("Digest sent to", RECIPIENT)


if __name__ == "__main__":
    main()
