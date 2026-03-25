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
import os
import json
import asyncio
import logging
import tempfile
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict
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
        OPENROUTER_API_KEY,
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
_TOPIC_LOOKUP: Dict[str, str] = {k.lower(): v for k, v in TOPIC_TO_FILE.items()}


def get_file_for_topic(topic_name: Optional[str]) -> Path:
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
    if "tiktok.com" in domain:
        return "tiktok"
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


async def transcribe_video(url: str) -> Dict[str, Optional[str]]:
    """Download audio from a video URL, get caption, and transcribe with Whisper."""
    result = {"transcript": None, "caption": None}
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            audio_path = os.path.join(tmpdir, "audio.m4a")

            # Step 1: Get caption/description via yt-dlp
            cap_proc = await asyncio.create_subprocess_exec(
                "yt-dlp",
                "--no-playlist",
                "--skip-download",
                "--print", "%(description)s",
                "--quiet",
                url,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            cap_out, _ = await asyncio.wait_for(cap_proc.communicate(), timeout=30)
            caption = cap_out.decode().strip() if cap_proc.returncode == 0 else ""
            if caption and caption != "NA":
                result["caption"] = caption

            # Step 2: Download audio with yt-dlp
            proc = await asyncio.create_subprocess_exec(
                "yt-dlp",
                "--no-playlist",
                "-x", "--audio-format", "m4a",
                "-o", audio_path,
                "--quiet",
                url,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
            if proc.returncode != 0:
                log.warning(f"yt-dlp failed for {url}: {stderr.decode()}")
                return result

            # yt-dlp may add extensions, find the actual file
            actual = None
            for f in os.listdir(tmpdir):
                if f.startswith("audio"):
                    actual = os.path.join(tmpdir, f)
                    break
            if not actual or not os.path.exists(actual):
                log.warning(f"No audio file found after yt-dlp for {url}")
                return result

            # Step 3: Transcribe with Whisper
            import whisper
            model = whisper.load_model("base")
            w_result = await asyncio.to_thread(model.transcribe, actual)
            text = w_result.get("text", "").strip()

            if text:
                if len(text) > 3000:
                    cut = text[:3000].rfind(".")
                    if cut > 1000:
                        text = text[: cut + 1] + "\n\n[...truncated]"
                    else:
                        text = text[:3000] + "\n\n[...truncated]"
                result["transcript"] = text

    except Exception as e:
        log.warning(f"Video transcription failed for {url}: {e}")

    return result


async def fetch_and_extract(url: str) -> dict:
    """Fetch a URL and extract the useful bits."""
    source_type = classify_url(url)
    result = {"url": url, "source_type": source_type, "title": "", "content": "", "error": None}

    # Twitter/X: use GraphQL API with guest token for full tweet text
    if source_type == "twitter":
        try:
            tweet_id = re.search(r"/status/(\d+)", url)
            if not tweet_id:
                result["error"] = "Could not parse tweet ID"
                return result
            tid = tweet_id.group(1)

            async with httpx.AsyncClient(timeout=15.0, headers=HEADERS) as client:
                bearer = "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs=1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"

                # Get guest token
                token_resp = await client.post(
                    "https://api.twitter.com/1.1/guest/activate.json",
                    headers={"Authorization": f"Bearer {bearer}"},
                    content="",
                )
                token_resp.raise_for_status()
                guest_token = token_resp.json()["guest_token"]

                # Fetch full tweet via GraphQL
                variables = json.dumps({"tweetId": tid, "withCommunity": False, "includePromotedContent": False, "withVoice": False})
                features = json.dumps({
                    "longform_notetweets_consumption_enabled": True,
                    "longform_notetweets_rich_text_read_enabled": True,
                    "longform_notetweets_inline_media_enabled": True,
                    "responsive_web_graphql_exclude_directive_enabled": True,
                    "verified_phone_label_enabled": False,
                    "responsive_web_graphql_timeline_navigation_enabled": True,
                    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
                    "responsive_web_enhance_cards_enabled": False,
                    "creator_subscriptions_tweet_preview_api_enabled": True,
                    "communities_web_enable_tweet_community_results_fetch": True,
                    "c9s_tweet_anatomy_moderator_badge_enabled": True,
                    "articles_preview_enabled": True,
                    "responsive_web_edit_tweet_api_enabled": True,
                    "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
                    "view_counts_everywhere_api_enabled": True,
                    "responsive_web_twitter_article_tweet_consumption_enabled": True,
                    "tweet_awards_web_tipping_enabled": False,
                    "creator_subscriptions_quote_tweet_preview_enabled": False,
                    "freedom_of_speech_not_reach_fetch_enabled": True,
                    "standardized_nudges_misinfo": True,
                    "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
                    "rweb_video_timestamps_enabled": True,
                })
                resp = await client.get(
                    "https://api.twitter.com/graphql/Xl5pC_lBk_gcO2ItU39DQw/TweetResultByRestId",
                    params={"variables": variables, "features": features},
                    headers={
                        "Authorization": f"Bearer {bearer}",
                        "x-guest-token": guest_token,
                    },
                )
                resp.raise_for_status()
                data = resp.json()

            tweet_data = data["data"]["tweetResult"]["result"]
            legacy = tweet_data.get("legacy", {})
            core = tweet_data.get("core", {}).get("user_results", {}).get("result", {}).get("legacy", {})
            author = core.get("name", "unknown")
            handle = core.get("screen_name", "")
            result["title"] = f"X post by {author} (@{handle})"

            # Prefer note_tweet (long-form) over legacy full_text
            note = tweet_data.get("note_tweet", {}).get("note_tweet_results", {}).get("result", {})
            tweet_text = note.get("text") or legacy.get("full_text", "")

            parts = [tweet_text] if tweet_text else []

            # Include quoted tweet if present
            quoted = tweet_data.get("quoted_status_result", {}).get("result", {})
            if quoted:
                q_legacy = quoted.get("legacy", {})
                q_core = quoted.get("core", {}).get("user_results", {}).get("result", {}).get("legacy", {})
                q_note = quoted.get("note_tweet", {}).get("note_tweet_results", {}).get("result", {})
                q_text = q_note.get("text") or q_legacy.get("full_text", "")
                q_handle = q_core.get("screen_name", "")
                if q_text:
                    parts.append(f"\n> Quoting @{q_handle}:\n> {q_text}")

            result["content"] = "\n".join(parts).strip()

        except Exception as e:
            log.warning(f"Twitter GraphQL failed for {url}: {e}")
            # Fallback to syndication API
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(
                        "https://cdn.syndication.twimg.com/tweet-result",
                        params={"id": tid, "token": "0"},
                    )
                    resp.raise_for_status()
                    sdata = resp.json()
                user = sdata.get("user", {})
                result["title"] = f"X post by {user.get('name', 'unknown')} (@{user.get('screen_name', '')})"
                result["content"] = sdata.get("text", "")
            except Exception as e2:
                result["error"] = str(e2)
                result["content"] = f"[Failed to fetch tweet: {e2}]"
        return result

    video_types = ("instagram", "tiktok", "youtube")
    if source_type in video_types:
        result["title"] = f"{source_type.title()} video"
        video_data = await transcribe_video(url)
        parts = []
        if video_data.get("caption"):
            parts.append(f"**Caption:** {video_data['caption']}")
        if video_data.get("transcript"):
            parts.append(f"**Transcript:** {video_data['transcript']}")
        if parts:
            result["content"] = "\n\n".join(parts)
        else:
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


    except Exception as e:
        result["error"] = str(e)
        result["content"] = f"[Failed to fetch: {e}]"

    return result


async def summarize_with_claude(content: str, url: str) -> Optional[str]:
    """Optional: summarize using Claude API."""
    if not OPENROUTER_API_KEY:
        return None
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "content-type": "application/json",
                },
                json={
                    "model": "anthropic/claude-haiku-4-5-20251001",
                    "max_tokens": 300,
                    "messages": [
                        {
                            "role": "user",
                            "content": (
                                f"Summarize the following text in 2-3 sentences. Be specific about what's being built or claimed. "
                                f"Focus on: what is it, who's building it, why it matters. "
                                f"Do NOT say you cannot access links — the text content has already been extracted for you below.\n\n"
                                f"{content[:3000]}"
                            ),
                        }
                    ],
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
    except Exception as e:
        log.warning(f"Summarization failed: {e}")
        return None


def format_entry(
    text: str = "",
    urls: Optional[List[Dict]] = None,
    summary: Optional[str] = None,
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


def get_topic_name(update: Update) -> Optional[str]:
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

        # Claude summary for first link (skip if content is just a view link)
        first = url_results[0] if url_results else None
        if first and first.get("content") and not first["content"].startswith("[Open link") and OPENROUTER_API_KEY:
            summary = await summarize_with_claude(
                first["content"], first["url"]
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


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle .md file uploads — save to storage/ and append summary + Obsidian link to topic file."""
    if not update.message or not update.message.document:
        return
    if not is_allowed(update.effective_user.id):
        return

    doc = update.message.document
    filename = doc.file_name or ""
    if not filename.lower().endswith(".md"):
        return

    # Download the file
    tg_file = await doc.get_file()
    file_bytes = await tg_file.download_as_bytearray()
    md_content = file_bytes.decode("utf-8", errors="replace").strip()

    if not md_content:
        await update.message.reply_text("File was empty.")
        return

    # Save full file to BRAIN/storage/
    storage_dir = Path(OBSIDIAN_VAULT_PATH) / "storage"
    storage_dir.mkdir(parents=True, exist_ok=True)

    storage_path = storage_dir / filename
    if storage_path.exists():
        # Handle name collision by appending timestamp
        stem = storage_path.stem
        suffix = storage_path.suffix
        ts = datetime.now().strftime("%Y%m%d%H%M%S")
        filename = f"{stem}_{ts}{suffix}"
        storage_path = storage_dir / filename

    storage_path.write_text(md_content, encoding="utf-8")
    log.info(f"Saved file to {storage_path}")

    # Figure out which topic this came from
    topic_name = get_topic_name(update)
    thread_id = update.message.message_thread_id
    if not topic_name and thread_id:
        thread_map = getattr(__import__("config"), "TOPIC_THREAD_IDS", {})
        topic_name = thread_map.get(thread_id)

    target_file = get_file_for_topic(topic_name)

    log.info(
        f".md file '{filename}' from {update.effective_user.first_name} "
        f"in topic '{topic_name or 'General'}' → {target_file.name}"
    )

    # Summarize the content
    summary = None
    if OPENROUTER_API_KEY:
        summary = await summarize_with_claude(md_content, filename)

    # Format entry with summary + Obsidian link
    caption = update.message.caption or ""
    sender = update.effective_user.first_name or ""

    now = datetime.now()
    lines = []
    lines.append(f"## {now.strftime('%Y-%m-%d')} at {now.strftime('%H:%M')}")
    if sender:
        lines.append(f"*From: {sender}*")
    lines.append("")
    lines.append("#document")
    lines.append("")
    if caption:
        lines.append(f"> {caption}")
        lines.append("")
    if summary:
        lines.append(f"**Summary:** {summary}")
        lines.append("")
    lines.append(f"**File:** [[storage/{filename}]]")
    lines.append("")
    lines.append("---")
    lines.append("")

    entry = "\n".join(lines)
    append_to_file(target_file, entry)

    file_label = target_file.stem.replace("-", " ").title()
    await update.message.reply_text(f"→ {file_label}: 📄 {filename} saved to storage/")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    log.info(f"Vault path: {OBSIDIAN_VAULT_PATH}")
    log.info(f"Topic routing: {TOPIC_TO_FILE}")
    log.info(f"Claude API: {'configured' if OPENROUTER_API_KEY else 'off'}")

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
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))

    log.info("Bot is running. Send messages to your group topics.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
