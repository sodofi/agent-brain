"""
Obsidian Brain Bot — routes Telegram group chat topics to Obsidian files.

Messages in "AI TRENDS" → BRAIN/ai-trends.md
Messages in "CONTENT"   → BRAIN/content.md

Links get fetched and content extracted. Text gets saved as-is.

Setup:
1. Talk to @BotFather on Telegram, create a bot, grab the token
2. Copy config.example.py to config.py and fill in your values
3. Run: python bot.py
"""

import re
import asyncio
import logging
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import (
    Application,
    MessageHandler,
    CommandHandler,
    filters,
    ContextTypes,
)

try:
    from readability import Document as ReadabilityDocument
    HAS_READABILITY = True
except ImportError:
    HAS_READABILITY = False

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

try:
    from config import (
        TELEGRAM_BOT_TOKEN,
        OBSIDIAN_VAULT_PATH,
        TOPIC_TO_FILE,
        DEFAULT_FILE,
        ALLOWED_USER_IDS,
        CLAUDE_API_KEY,
    )
except ImportError:
    print("Missing config.py — copy config.example.py to config.py and fill in your values.")
    raise SystemExit(1)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

URL_RE = re.compile(r"https?://[^\s<>\"'\)]+")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Build a lookup from lowercased topic name → file path
_TOPIC_LOOKUP: dict[str, str] = {k.lower(): v for k, v in TOPIC_TO_FILE.items()}


def get_file_for_topic(topic_name: str | None) -> Path:
    """Given a forum topic name, return the Obsidian file path."""
    if topic_name:
        match = _TOPIC_LOOKUP.get(topic_name.strip().lower())
        if match:
            return Path(OBSIDIAN_VAULT_PATH) / match
    return Path(OBSIDIAN_VAULT_PATH) / DEFAULT_FILE


def ensure_file(path: Path) -> Path:
    """Create the file with a header if it doesn't exist."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        name = path.stem.replace("-", " ").title()
        path.write_text(f"# {name}\n\nAuto-populated from Telegram.\n\n---\n\n")
    return path


def classify_url(url: str) -> str:
    """Classify a URL into a content type for tagging."""
    domain = urlparse(url).netloc.lower()
    if "twitter.com" in domain or "x.com" in domain:
        return "twitter"
    if "instagram.com" in domain:
        return "instagram"
    if "youtube.com" in domain or "youtu.be" in domain:
        return "youtube"
    if "reddit.com" in domain:
        return "reddit"
    if "substack.com" in domain or "beehiiv.com" in domain:
        return "newsletter"
    if "arxiv.org" in domain:
        return "paper"
    if "github.com" in domain:
        return "github"
    if "podcast" in domain or "spotify.com" in domain or "apple.com/podcast" in url.lower():
        return "podcast"
    return "article"


async def fetch_and_extract(url: str) -> dict:
    """Fetch a URL and extract the useful bits."""
    source_type = classify_url(url)
    result = {"url": url, "source_type": source_type, "title": "", "content": "", "error": None}

    hard_to_scrape = source_type in ("instagram",)
    if hard_to_scrape:
        result["title"] = f"{source_type.title()} post"
        result["content"] = f"[Open link to view]({url})"
        return result

    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=15.0,
            headers=HEADERS,
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            html = resp.text

        if HAS_READABILITY:
            doc = ReadabilityDocument(html)
            result["title"] = doc.title() or ""
            article_html = doc.summary()
            soup = BeautifulSoup(article_html, "lxml")
            result["content"] = soup.get_text(separator="\n", strip=True)
        else:
            soup = BeautifulSoup(html, "lxml")
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()
            result["title"] = soup.title.string if soup.title else ""
            result["content"] = soup.get_text(separator="\n", strip=True)

        # Trim to ~1500 chars
        content = result["content"]
        if len(content) > 1500:
            cut = content[:1500].rfind(".")
            if cut > 500:
                content = content[: cut + 1] + "\n\n[...truncated]"
            else:
                content = content[:1500] + "\n\n[...truncated]"
        result["content"] = content.strip()

        # Twitter: try meta tags
        if source_type == "twitter":
            soup_full = BeautifulSoup(html, "lxml")
            og_desc = soup_full.find("meta", property="og:description")
            if og_desc and og_desc.get("content"):
                result["content"] = og_desc["content"]
                result["title"] = "X post"

    except Exception as e:
        result["error"] = str(e)
        result["content"] = f"[Failed to fetch: {e}]"

    return result


async def summarize_with_claude(content: str, url: str) -> str | None:
    """Optional: summarize using Claude API."""
    if not CLAUDE_API_KEY:
        return None
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": CLAUDE_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 300,
                    "messages": [
                        {
                            "role": "user",
                            "content": (
                                f"Summarize this in 2-3 sentences. Be specific about what's being built or claimed. "
                                f"Focus on: what is it, who's building it, why it matters.\n\n"
                                f"Source: {url}\n\n{content[:3000]}"
                            ),
                        }
                    ],
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return data["content"][0]["text"]
    except Exception as e:
        log.warning(f"Claude summarization failed: {e}")
        return None


def format_entry(
    text: str = "",
    urls: list[dict] | None = None,
    summary: str | None = None,
    sender: str = "",
) -> str:
    """Format a single capture entry as markdown."""
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M")

    lines = []
    lines.append(f"## {date_str} at {time_str}")
    if sender:
        lines.append(f"*From: {sender}*")
    lines.append("")

    # Source type tags
    if urls:
        tags = sorted(set(u["source_type"] for u in urls))
        lines.append(" ".join(f"#{t}" for t in tags))
        lines.append("")

    # Original text (skip if it's just the bare URL)
    bare_link = len(urls or []) == 1 and text.strip() == (urls or [{}])[0].get("url", "")
    if text and not bare_link:
        # Indent multiline text as a blockquote
        for line in text.split("\n"):
            lines.append(f"> {line}")
        lines.append("")

    # Link extractions
    if urls:
        for u in urls:
            title = u.get("title") or u["source_type"]
            lines.append(f"**Source:** [{title}]({u['url']})")
            if u.get("content"):
                lines.append("")
                lines.append(u["content"])
            if u.get("error"):
                lines.append(f"*Fetch error: {u['error']}*")
            lines.append("")

    # AI summary
    if summary:
        lines.append(f"**Summary:** {summary}")
        lines.append("")

    lines.append("---")
    lines.append("")

    return "\n".join(lines)


def append_to_file(filepath: Path, entry: str):
    """Insert an entry after the header (newest first)."""
    path = ensure_file(filepath)
    existing = path.read_text()

    separator = "---\n\n"
    idx = existing.find(separator)
    if idx != -1:
        insert_point = idx + len(separator)
        new_content = existing[:insert_point] + entry + existing[insert_point:]
    else:
        new_content = existing + "\n" + entry

    path.write_text(new_content)


def is_allowed(user_id: int) -> bool:
    if not ALLOWED_USER_IDS:
        return True
    return user_id in ALLOWED_USER_IDS


def get_topic_name(update: Update) -> str | None:
    """
    Extract the forum topic name from a message.

    Telegram forum topics use message_thread_id. The topic name comes from
    the reply_to_message's forum_topic_created field when it's the pinned
    service message, but more reliably we can get it from the chat's
    get_forum_topic method or from the thread's name field.

    As a fallback, we map thread IDs via config.
    """
    msg = update.message
    if not msg:
        return None

    # Check if the message itself is a forum topic creation
    if msg.forum_topic_created:
        return msg.forum_topic_created.name

    # Check reply_to_message for the topic header
    if msg.reply_to_message and msg.reply_to_message.forum_topic_created:
        return msg.reply_to_message.forum_topic_created.name

    return None


# ---------------------------------------------------------------------------
# Bot handlers
# ---------------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return

    msg = (
        "Brain bot is running.\n\n"
        "Send messages to the group topics and they'll land in your Obsidian vault:\n"
    )
    for topic, filepath in TOPIC_TO_FILE.items():
        msg += f"  • {topic} → {filepath}\n"
    msg += f"\nYour user ID: {update.effective_user.id}"

    await update.message.reply_text(msg)


async def cmd_debug(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Debug command — shows thread info so you can map topic IDs."""
    if not is_allowed(update.effective_user.id):
        return

    msg = update.message
    thread_id = msg.message_thread_id if msg.message_thread_id else "None"
    topic_name = get_topic_name(update) or "Unknown"
    target_file = get_file_for_topic(topic_name)

    await update.message.reply_text(
        f"Thread ID: {thread_id}\n"
        f"Topic name: {topic_name}\n"
        f"Target file: {target_file.relative_to(OBSIDIAN_VAULT_PATH)}\n"
        f"Chat ID: {msg.chat_id}\n"
        f"Chat type: {msg.chat.type}"
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle any message — route to the right Obsidian file based on topic."""
    if not update.message:
        return
    if not is_allowed(update.effective_user.id):
        return

    text = update.message.text or update.message.caption or ""
    if not text.strip():
        return

    # Figure out which topic this came from
    topic_name = get_topic_name(update)

    # Also try to detect topic from thread_id + topic name mapping
    # Telegram sometimes only gives us the thread_id, not the name.
    # After the first /debug in each topic, you can add thread_id mappings
    # to TOPIC_THREAD_IDS in config if needed.
    thread_id = update.message.message_thread_id
    if not topic_name and thread_id:
        # Check if there's a thread ID mapping in config
        thread_map = getattr(__import__("config"), "TOPIC_THREAD_IDS", {})
        topic_name = thread_map.get(thread_id)

    target_file = get_file_for_topic(topic_name)

    log.info(
        f"Message from {update.effective_user.first_name} "
        f"in topic '{topic_name or 'General'}' → {target_file.name}"
    )

    # Find URLs
    found_urls = URL_RE.findall(text)
    url_results = []
    summary = None

    if found_urls:
        # Fetch all URLs concurrently
        tasks = [fetch_and_extract(url) for url in found_urls[:5]]
        url_results = await asyncio.gather(*tasks)

        # Claude summary for first link
        if url_results and url_results[0].get("content") and CLAUDE_API_KEY:
            summary = await summarize_with_claude(
                url_results[0]["content"], url_results[0]["url"]
            )

    # Format and save
    sender = update.effective_user.first_name or ""
    entry = format_entry(text=text, urls=url_results or None, summary=summary, sender=sender)
    append_to_file(target_file, entry)

    # Confirm
    file_label = target_file.stem.replace("-", " ").title()
    if url_results:
        titles = [u.get("title", u["source_type"]) for u in url_results]
        label = ", ".join(t[:40] for t in titles if t)
        reply = f"→ {file_label}: {label}" if label else f"→ {file_label}"
        if any(u.get("error") for u in url_results):
            reply += " (some links failed)"
    else:
        preview = text[:50] + "..." if len(text) > 50 else text
        reply = f"→ {file_label}: {preview}"

    await update.message.reply_text(reply)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    log.info(f"Vault path: {OBSIDIAN_VAULT_PATH}")
    log.info(f"Topic routing: {TOPIC_TO_FILE}")
    log.info(f"Claude API: {'configured' if CLAUDE_API_KEY else 'off'}")

    vault = Path(OBSIDIAN_VAULT_PATH)
    if not vault.exists():
        log.error(f"Vault path does not exist: {OBSIDIAN_VAULT_PATH}")
        raise SystemExit(1)

    # Ensure all target files exist
    for filepath in TOPIC_TO_FILE.values():
        ensure_file(vault / filepath)
    ensure_file(vault / DEFAULT_FILE)
    log.info("All target files verified.")

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("debug", cmd_debug))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    log.info("Bot is running. Send messages to your group topics.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
