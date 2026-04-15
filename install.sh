#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="/opt/monitor"
CONFIG_DIR="/etc/monitor"
SERVICE_FILE="/etc/systemd/system/server-monitor.service"

echo "==> Installing server monitor..."

# 1. Copy files
mkdir -p "$INSTALL_DIR" "$CONFIG_DIR"
cp monitor.py "$INSTALL_DIR/monitor.py"
chmod +x "$INSTALL_DIR/monitor.py"

# 2. Write config (skip if it already exists)
if [ ! -f "$CONFIG_DIR/config.json" ]; then
    cp config.json "$CONFIG_DIR/config.json"
    echo "==> Config written to $CONFIG_DIR/config.json"
    echo "    Edit it to set your Telegram bot_token, chat_id, and thresholds."
else
    echo "==> Config already exists at $CONFIG_DIR/config.json — skipping."
fi

# 3. Install systemd service
cp monitor.service "$SERVICE_FILE"
systemctl daemon-reload
systemctl enable server-monitor
systemctl restart server-monitor

echo ""
echo "==> Done! Service status:"
systemctl status server-monitor --no-pager
echo ""
echo "Useful commands:"
echo "  journalctl -fu server-monitor   # live logs"
echo "  systemctl restart server-monitor"
