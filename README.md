# Obsidian Brain Bot

A Telegram bot that turns your group chat into a personal knowledge base — using the same [three-folder architecture](https://x.com/NickSpisak_/status/2040448463540830705) that Karpathy uses for building AI-native knowledge systems.



https://github.com/user-attachments/assets/4319b4f5-9093-48b2-b3ae-c3cb3795f70f


[Download the complete PDF setup guide](https://sophiacode.gumroad.com/l/glpsbw).

You send messages to Telegram topics. The bot dumps them into `raw/`. An AI organizes them into a `wiki/`. You query the wiki and save answers to `outputs/`.

```
your-vault/
  raw/          ← bot writes here (your junk drawer of source material)
  wiki/         ← AI maintains this (organized, connected, searchable)
  outputs/      ← you write here (answers, reports, research from Claude Code sessions)
```

No special software. No database. Just folders, text files, and a Telegram bot.

## What the bot does

- Routes messages from Telegram group topics into separate markdown files in `raw/`
- Fetches and extracts content from links (articles, tweets, YouTube, Reddit, etc.)
- Transcribes video/audio from Instagram, TikTok, and YouTube using Whisper
- Generates AI summaries for links and documents (via OpenRouter/Claude)
- Extracts next-steps from meeting notes automatically
- Auto-updates a `wiki/` with organized, theme-based summaries after every new entry
- Handles `.md` file uploads (saves to `raw/storage/`, adds summary + Obsidian link)

## How it works

```
Telegram group topic → bot.py → raw/topic-name.md → (AI) → wiki/topic-name.md
                                                              ↓
                                              wiki/INDEX.md (master index)
```

Each Telegram topic maps to a file. When you send a message:

1. The raw text (+ extracted link content, transcripts, summaries) goes into `raw/`
2. The bot calls Claude to update the corresponding `wiki/` page — organized by theme, not by date
3. Meeting notes get special treatment: the wiki maintains a "What I Need To Work On" section with consolidated action items

The `wiki/` is what you actually read and query. The `raw/` is the source of truth. The `outputs/` folder is where you save answers when you run Claude Code against your wiki.

## Setup

### 1. Create a Telegram bot

- Open Telegram, search for `@BotFather`
- Send `/newbot`, follow the prompts, copy the token
- Send `/setjoingroups` → select your bot → **Enable**
- Send `/setprivacy` → select your bot → **Disable** (so the bot can read group messages)

### 2. Create your Telegram group

- Create a group chat (this is your "brain")
- Enable Topics (Group Settings → Topics)
- Add the bot as a member
- Create topics for each area you want to track (e.g., "AI Trends", "Meeting Notes", "Ideas")

### 3. Configure

```bash
cp config.example.py config.py
```

Edit `config.py`:
- Paste your bot token
- Set your vault path (where `raw/`, `wiki/`, `outputs/` will live)
- Map your topic names to filenames
- Optionally add an [OpenRouter API key](https://openrouter.ai/keys) for AI summaries + wiki updates

### 4. Build the bot with Claude Code

This repo gives you the architecture and config — you build the actual `bot.py` using Claude Code (or Cursor, or any AI coding tool).

Open Claude Code in this directory and prompt it:

```
Build a Telegram bot that:
- Reads config from config.py (TELEGRAM_BOT_TOKEN, OBSIDIAN_VAULT_PATH, TOPIC_TO_FILE, TOPIC_THREAD_IDS, ALLOWED_USER_IDS, OPENROUTER_API_KEY)
- Routes messages from Telegram group topics to markdown files in raw/
- Uses TOPIC_THREAD_IDS to map thread IDs to topic names (more reliable than Telegram's forum_topic_created which gets stale after renames)
- Extracts and saves content from URLs (articles, tweets, YouTube, etc.)
- Generates AI summaries via OpenRouter API (model: anthropic/claude-3.5-haiku)
- After saving to raw/, calls Claude to update the corresponding wiki/ file (organized by theme, not by date)
- Meeting notes topic gets special handling: wiki maintains "What I Need To Work On" with consolidated action items, "Active Projects & Context", and "Key Decisions & Commitments"
- Meeting notes get "Next Steps" extraction instead of generic summaries
- Has /debug command that shows thread ID and config mapping
- Has /start command that shows routing info
- Handles .md file uploads (save to raw/storage/, add summary + Obsidian link to topic file)
- Uses python-telegram-bot library
- Uses drop_pending_updates=True on startup
```

Install the dependencies it generates:

```bash
pip install -r requirements.txt
```

### 5. Get thread IDs

```bash
python bot.py
```

Send `/debug` in each Telegram topic. Copy the thread IDs into `TOPIC_THREAD_IDS` in your config:

```python
TOPIC_THREAD_IDS = {
    4: "AI TRENDS",
    7: "CONTENT",
    316: "MEETING NOTES",
}
```

### 6. Use it

Send messages to your Telegram topics. The bot saves to `raw/`, updates `wiki/`, and confirms in chat.

To query your knowledge base, point Claude Code at your vault:

```
Read wiki/ and tell me the three biggest themes across my research this month.
```

Save the answer to `outputs/`.

## The schema file

Create a `CLAUDE.md` in your vault root. This tells Claude Code how your knowledge base is organized:

```markdown
# Knowledge Base Schema

## How It's Organized
- raw/ contains unprocessed source material from Telegram. Never modify these files.
- wiki/ contains the organized wiki. AI maintains this entirely.
- outputs/ contains generated reports, answers, and analyses.

## Wiki Rules
- Every topic gets its own .md file in wiki/
- Every wiki file starts with a one-paragraph summary
- Link related topics using [[wiki/topic-name]] format
- Maintain an INDEX.md in wiki/ that lists every topic
- When new raw sources are added, update relevant wiki articles
- Organize by theme/concept, NOT by date

## My Interests
[List what you want this knowledge base to focus on]
```

## Running 24/7

```bash
# Simple background process
nohup python bot.py &

# macOS Launch Agent (runs on login)
# See Apple docs for ~/Library/LaunchAgents/ plist format

# VPS (DigitalOcean, Hetzner, etc.)
# Deploy with systemd service — bot writes to local disk,
# rsync files to your machine on a cron
```

## Adding more topics

1. Create the topic in your Telegram group
2. Send `/debug` in the new topic to get its thread ID
3. Add entries to `TOPIC_TO_FILE` and `TOPIC_THREAD_IDS` in config.py
4. Restart the bot

## Credits

Architecture inspired by [Karpathy's LLM knowledge base approach](https://x.com/NickSpisak_/status/2040448463540830705) — three folders, one schema file, and an AI that maintains everything.
