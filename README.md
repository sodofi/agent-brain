# Obsidian Brain Bot

A Telegram bot that routes messages from group chat topics into separate Obsidian files.



https://github.com/user-attachments/assets/4319b4f5-9093-48b2-b3ae-c3cb3795f70f



[Download the complete PDF setup guide](https://sophiacode.gumroad.com/l/glpsbw).

## Setup

### 1. Create a Telegram bot
- Open Telegram, search for `@BotFather`
- Send `/newbot`, follow the prompts, copy the token
- **Important:** Send `/setjoingroups` → select your bot → Enable
- **Important:** Send `/setprivacy` → select your bot → Disable (so the bot can read group messages)

### 2. Add the bot to your group
- Create a "BRAIN" group chat
- Add the bot as a member
- Make sure the group has Topics enabled (Group Settings → Topics)

### 3. Configure
```bash
cp config.example.py config.py
```
Edit `config.py`:
- Paste your bot token
- Set your Obsidian vault path
- The topic routing is pre-configured for your setup

### 4. Get thread IDs (one-time step)
```bash
python bot.py
```
Then go to each topic in your Telegram group and send `/debug`. The bot will reply with the thread ID. Copy those into `TOPIC_THREAD_IDS` in your config:
```python
TOPIC_THREAD_IDS = {
    123456: "AI TRENDS",
    789012: "CONTENT",
}
```
This is a fallback — Telegram sometimes sends thread IDs instead of topic names.

### 5. Install and run
```bash
pip install -r requirements.txt
python bot.py
```

### 6. (Optional) Enable AI summaries

Get an API key from [OpenRouter](https://openrouter.ai/keys) and add it to `config.py`:

```python
OPENROUTER_API_KEY = "sk-or-..."
```

When set, links and `.md` file uploads get a 2-3 sentence AI summary (powered by Claude). Leave it as an empty string to skip summaries.

## Usage

Just send messages to your group topics as normal:

- **Plain text** in AI TRENDS → saved to `BRAIN/ai-trends.md`
- **A link** in CONTENT → fetched, extracted, saved to `BRAIN/content.md`
- **A `.md` file** in any topic → full file saved to `BRAIN/storage/`, summary + Obsidian link added to the topic file
- **`/debug`** in any topic → shows routing info

The bot replies with a confirmation showing where it saved and what it extracted.

Non-`.md` file uploads are silently ignored.

## Adding more topics

Just add entries to `TOPIC_TO_FILE` in config.py:

```python
TOPIC_TO_FILE = {
    "AI TRENDS": "BRAIN/ai-trends.md",
    "CONTENT": "BRAIN/content.md",
    "MEETINGS": "BRAIN/meetings.md",    # new
    "IDEAS": "BRAIN/ideas.md",           # new
}
```

Run `/debug` in the new topics to get their thread IDs.

## Running in the background

```bash
# Simple
nohup python bot.py &

# macOS: create a Launch Agent (runs on login)
# See Apple docs for ~/Library/LaunchAgents/ plist format
```
