"""
Configuration for the Obsidian Brain Bot.
Copy this file to config.py and fill in your values.
"""

import os

# ---------------------------------------------------------------------------
# Required
# ---------------------------------------------------------------------------

# Get this from @BotFather on Telegram
TELEGRAM_BOT_TOKEN = os.environ.get(
    "TELEGRAM_BOT_TOKEN",
    "your-bot-token-here",
)

# Absolute path to your Obsidian vault root folder (or any folder on your machine)
# This is where raw/, wiki/, and outputs/ will live
# On a VPS, use something like /home/brain/data
OBSIDIAN_VAULT_PATH = os.environ.get(
    "OBSIDIAN_VAULT_PATH",
    "/Users/you/path-to-your-vault",
)

# ---------------------------------------------------------------------------
# Topic → File Routing
# ---------------------------------------------------------------------------
# Map your Telegram group topics to files inside raw/.
# Keys = topic names in your Telegram group (case-insensitive)
# Values = file paths relative to raw/ (the bot prepends raw/ automatically)
#
# Example: a message in "AI TRENDS" → raw/ai-trends.md
# The bot also updates the corresponding wiki/ai-trends.md

TOPIC_TO_FILE = {
    "AI TRENDS": "ai-trends.md",
    "CONTENT": "content-ideas.md",
    "MEETING NOTES": "meeting-notes.md",
    # Add your own topics here
}

# Messages that don't match any topic land here
DEFAULT_FILE = "inbox.md"

# ---------------------------------------------------------------------------
# Topic Thread ID Mapping (fill in after running /debug)
# ---------------------------------------------------------------------------
# Telegram forum topics use thread IDs internally. Topic names from
# Telegram's API can be stale after renames, so thread IDs are the
# reliable way to route messages.
#
# Run /debug in each topic to get its thread ID, then map them here.
# The thread ID is the small number (not the chat ID, which is the same
# for all topics in the same group).

TOPIC_THREAD_IDS = {
    # 4: "AI TRENDS",
    # 7: "CONTENT",
    # 316: "MEETING NOTES",
}

# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------

# Your Telegram user ID(s). Only these users can send to the bot.
# Leave empty [] to allow anyone (not recommended for group bots).
# Run the bot and send /start to see your user ID.
ALLOWED_USER_IDS = []

# ---------------------------------------------------------------------------
# Optional: OpenRouter API for AI features
# ---------------------------------------------------------------------------

# Powers: link summaries, meeting notes next-steps extraction, wiki updates.
# Without this, the bot still saves everything to raw/ but won't maintain
# the wiki or generate summaries.
# Get a key at: https://openrouter.ai/keys
OPENROUTER_API_KEY = os.environ.get(
    "OPENROUTER_API_KEY",
    "",
)
