"""
Configuration for the Obsidian Brain Bot.
Copy this file to config.py and fill in your values.
"""

# ---------------------------------------------------------------------------
# Required
# ---------------------------------------------------------------------------

# Get this from @BotFather on Telegram
TELEGRAM_BOT_TOKEN = "your-bot-token-here"

# Absolute path to your Obsidian vault root folder
# Example: "/Users/sodofi/Documents/ObsidianVault"
OBSIDIAN_VAULT_PATH = "/Users/sodofi/path-to-your-vault"

# ---------------------------------------------------------------------------
# Topic → File Routing
# ---------------------------------------------------------------------------
# Map your Telegram group topics to Obsidian files.
# Keys = topic names in your Telegram group (case-insensitive)
# Values = file paths relative to your vault root

TOPIC_TO_FILE = {
    "AI TRENDS": "BRAIN/ai-trends.md",
    "CONTENT": "BRAIN/content.md",
}

# Messages that don't match any topic land here
DEFAULT_FILE = "BRAIN/inbox.md"

# ---------------------------------------------------------------------------
# Topic Thread ID Mapping (optional, fill in after running /debug)
# ---------------------------------------------------------------------------
# Telegram sometimes only sends thread IDs, not topic names.
# Run /debug in each topic to get the thread ID, then map them here.
# Example: {123456: "AI TRENDS", 789012: "CONTENT"}

TOPIC_THREAD_IDS = {}

# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------

# Your Telegram user ID(s). Only these users can send to the bot.
# Leave empty [] to allow anyone (not recommended for group bots).
# Run the bot and send /start to see your user ID.
ALLOWED_USER_IDS = []

# ---------------------------------------------------------------------------
# Optional: Claude API for smarter summaries
# ---------------------------------------------------------------------------

# If set, links get a 2-3 sentence AI summary in addition to raw content.
# Leave empty string for raw extraction only (still useful, just no summary).
# Get a key at: https://console.anthropic.com/
CLAUDE_API_KEY = ""
