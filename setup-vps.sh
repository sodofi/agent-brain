#!/bin/bash
# Run this on your DigitalOcean droplet after cloning the repo.
# Usage: bash setup-vps.sh

set -e

echo "=== Setting up Obsidian Brain Bot ==="

# Install Python and pip
sudo apt update && sudo apt install -y python3 python3-pip python3-venv

# Create data directory (where the bot writes files)
sudo mkdir -p /home/brain/data
sudo chown $USER:$USER /home/brain/data

# Set up venv and install deps
cd /home/$USER/obsidian-telegram-bot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Create the env file (you'll fill in the values)
if [ ! -f /home/$USER/.brain-bot.env ]; then
    cat > /home/$USER/.brain-bot.env << 'EOF'
TELEGRAM_BOT_TOKEN=your-token-here
OBSIDIAN_VAULT_PATH=/home/brain/data
OPENROUTER_API_KEY=your-key-here
EOF
    echo ""
    echo ">>> EDIT /home/$USER/.brain-bot.env with your actual tokens <<<"
    echo ""
fi

# Install systemd service
sudo tee /etc/systemd/system/brain-bot.service > /dev/null << EOF
[Unit]
Description=Obsidian Brain Telegram Bot
After=network.target

[Service]
User=$USER
WorkingDirectory=/home/$USER/obsidian-telegram-bot
EnvironmentFile=/home/$USER/.brain-bot.env
ExecStart=/home/$USER/obsidian-telegram-bot/venv/bin/python bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable brain-bot
sudo systemctl start brain-bot

echo ""
echo "=== Done! Bot is running. ==="
echo "Check status: sudo systemctl status brain-bot"
echo "View logs:    sudo journalctl -u brain-bot -f"
echo ""
echo "Files are written to /home/brain/data/"
echo "Set up rsync on your Mac to pull them into your Obsidian vault."
