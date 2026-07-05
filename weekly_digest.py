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
    return text[:1200]


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
    # Color palette for the six schools — used in the prompt so Claude
    # wraps each school section in the matching color.
    school_colors = {
        "אסכולת התיאוריה (Theory)":                                  "#6C63FF",
        "אסכולת המחקר האמפירי (Empirical Research)":                 "#2D9CDB",
        "אסכולת הארגון כמערכת חברתית (Organization as Social System)": "#27AE60",
        "אסכולת האסטרטגיה (Strategy)":                               "#E67E22",
        "אסכולת הפסיכולוגיה הארגונית (Organizational Psychology)":   "#E74C3C",
        "אסכולת המנהיגות (Leadership)":                              "#8E44AD",
    }
    color_instructions = "\n".join(
        f"  - {name}: use color {color}" for name, color in school_colors.items()
    )

    header = (
        "You are preparing a beautifully designed HTML email digest of recent "
        "peer-reviewed articles from top academic management journals, for a "
        "Hebrew-speaking reader who works in organizational consulting and "
        "leadership development.\n\n"
        "CRITICAL: Write the ENTIRE digest in high-register Hebrew (עברית "
        "תקנית גבוהה). All summaries, all labels, all notes — everything "
        "must be in Hebrew. The only exceptions are: article titles (keep in "
        "the original English and make them clickable links), journal names "
        "(keep in English in parentheses), and the school headings (keep "
        "both Hebrew and English as given below).\n\n"
        "DESIGN INSTRUCTIONS — use inline CSS for everything (email clients "
        "ignore <style> blocks):\n"
        "- Each school section should have an <h2> with a colored left "
        "border (4px solid) and matching colored text. The colors per school "
        "are:\n"
        f"{color_instructions}\n"
        "- Each article should be wrapped in a card: a <div> with "
        "background:#f8f9fa, border-radius:8px, padding:16px, "
        "margin-bottom:12px, and a thin top border (3px solid) in the "
        "school's color.\n"
        "- Article titles should be <h3> with color:#1a1a1a and linked to "
        "the URL. The journal name in parentheses should be in a <span> "
        "with color:#666 and font-size:13px.\n"
        "- Labels (שאלת מחקר, שיטה ומדגם, ממצאים מרכזיים) should be "
        "<strong> with color:#333.\n"
        "- The 'למה זה חשוב לפרקטיקה' note should be in an <em> block "
        "with background:#e8f4fd, border-radius:6px, padding:8px 12px, "
        "display:block, margin-top:8px, color:#1a5276, font-size:14px.\n"
        "- Use a small decorative emoji before each label: 🔍 for שאלת "
        "מחקר, 🧪 for שיטה ומדגם, 📊 for ממצאים מרכזיים, 💡 for למה זה "
        "חשוב לפרקטיקה.\n\n"
        "For each article give:\n"
        "- שם כתב העת בסוגריים אחרי הכותרת\n"
        "- 🔍 <strong>שאלת מחקר:</strong> מה השאלה שהמחקר שאל? (משפט אחד)\n"
        "- 🧪 <strong>שיטה ומדגם:</strong> כיצד נבדק? כללו את שיטת המחקר "
        "(סקר, ניסוי, מחקר שדה, מטה-אנליזה, מחקר איכותני, אורכי וכו׳), "
        "סוג המשתתפים או הארגונים, התעשייה או המגזר אם צוינו, וגודל "
        "המדגם אם זמין. (1-2 משפטים)\n"
        "- 📊 <strong>ממצאים מרכזיים:</strong> מה מצאו? סכמו את המסקנות "
        "העיקריות בשפה פשוטה וברורה. (2-3 משפטים)\n"
        "- 💡 <em>למה זה חשוב לפרקטיקה:</em> הערה קצרה כיצד יועץ ארגוני או "
        "מנהל יכולים להשתמש בממצא הזה. (משפט אחד)\n\n"
        "כתבו הכל במילים שלכם — אל תעתיקו מהתקציר. דלגו על אסכולות ללא "
        "מאמרים חדשים. סיימו ב׳🎯 נושא התקופה׳ — תיבה מעוצבת עם "
        "background:#fff3cd, border:1px solid #ffc107, border-radius:8px, "
        "padding:16px, אם זיהיתם חוט מקשר בין האסכולות.\n\n"
        "Return the HTML fragment only (no <html>/<body>/<head> wrapper). "
        "Use ONLY inline styles, no CSS classes.\n\nArticles by school:\n"
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
        max_tokens=8000,
        messages=[{"role": "user", "content": prompt}],
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError("The model declined to respond to this batch.")
    return "".join(b.text for b in resp.content if b.type == "text")


def send_email(html_body: str) -> None:
    today = datetime.now().strftime("%b %d, %Y")
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"סיכום מחקרי ניהול — {today}"
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = RECIPIENT

    full_html = f"""<html dir="rtl"><head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background-color:#f0f2f5;font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;">
<div style="max-width:660px;margin:0 auto;padding:20px;">

  <!-- Header -->
  <div style="background:linear-gradient(135deg,#1a1a2e 0%,#16213e 50%,#0f3460 100%);
    border-radius:12px 12px 0 0;padding:32px 28px;text-align:center;">
    <h1 style="color:#ffffff;font-size:24px;margin:0 0 6px 0;font-weight:700;">
      📚 סיכום מחקרי ניהול
    </h1>
    <p style="color:#a8b2d1;font-size:14px;margin:0;">{today}</p>
  </div>

  <!-- Body -->
  <div style="background:#ffffff;padding:28px;border-radius:0 0 12px 12px;
    direction:rtl;text-align:right;line-height:1.7;color:#2c3e50;">
    {html_body}
  </div>

  <!-- Footer -->
  <div style="text-align:center;padding:20px;direction:rtl;">
    <p style="font-size:12px;color:#95a5a6;margin:0;">
      נוצר אוטומטית · הסיכומים נכתבו על ידי Claude · לחצו על כותרת מאמר לקריאת המקור המלא
    </p>
  </div>

</div>
</body></html>"""

    msg.attach(MIMEText(full_html, "html"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        server.send_message(msg)


def main() -> None:
    by_journal = collect_articles()
    prompt, has_content = build_prompt(by_journal)
    body = summarize(prompt) if has_content else (
        '<div style="background:#f8f9fa;border-radius:8px;padding:20px;text-align:center;">'
        '<p style="font-size:16px;color:#666;">🔇 אין מאמרים חדשים מכתבי העת '
        f'ב-{DAYS_BACK} הימים האחרונים.</p>'
        '<p style="font-size:14px;color:#999;">כתבי עת אקדמיים מתפרסמים לאט — '
        'זה תקין לגמרי.</p></div>'
    )
    send_email(body)
    print("Digest sent to", RECIPIENT)


if __name__ == "__main__":
    main()
