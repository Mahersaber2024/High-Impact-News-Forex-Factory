#!/usr/bin/env bash
set -e

APP_DIR="/opt/forexfactory-api"
REPO_URL="https://github.com/Mahersaber2024/High-Impact-News-Forex-Factory.git"
SERVICE_USER="root"

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

echo "1) Flask only  (run the API on this server, no bot)"
echo "2) Flask + Telegram Bot  (both on this same server)"
echo "3) Telegram Bot only  (bot on this server, Flask API runs elsewhere)"
read -p "Choose install mode [1/2/3]: " INSTALL_MODE

RUN_FLASK=true
RUN_BOT=false
FLASK_PORT="45869"
DOMAIN_NAME=""
CERTBOT_EMAIL=""
TELEGRAM_BOT_TOKEN=""
ADMIN_CHAT_ID="0"
SEND_RESTART_MSG="false"
REMOTE_API_BASE_URL=""

if [ "$INSTALL_MODE" = "3" ]; then
  RUN_FLASK=false
fi

# ---------------- Flask questions (modes 1 and 2) ----------------
if [ "$RUN_FLASK" = "true" ]; then
  read -p "Enter Flask port [default: 45869]: " FLASK_PORT
  FLASK_PORT=${FLASK_PORT:-45869}

  echo -e "${CYAN}The website (website/content) and the API are served together on one domain:${NC}"
  echo "  https://DOMAIN/            -> website"
  echo "  https://DOMAIN/api/forex/  -> API"
  read -p "Enter domain for the site + API (press Enter to skip, e.g. heysolo.online): " DOMAIN_NAME
  DOMAIN_NAME=${DOMAIN_NAME:-}
  DOMAIN_NAME=${DOMAIN_NAME#https://}; DOMAIN_NAME=${DOMAIN_NAME#http://}; DOMAIN_NAME=${DOMAIN_NAME%%/*}

  if [ -n "$DOMAIN_NAME" ]; then
    read -p "Enter email for SSL certificate [default: admin@$DOMAIN_NAME]: " CERTBOT_EMAIL
    CERTBOT_EMAIL=${CERTBOT_EMAIL:-admin@$DOMAIN_NAME}
  fi
fi

# ---------------- Bot questions (modes 2 and 3) ----------------
if [ "$INSTALL_MODE" = "2" ] || [ "$INSTALL_MODE" = "3" ]; then
  RUN_BOT=true
  read -s -p "Enter Telegram bot token: " TELEGRAM_BOT_TOKEN
  echo
  read -p "Enter Admin chat ID [default: 0]: " ADMIN_CHAT_ID
  ADMIN_CHAT_ID=${ADMIN_CHAT_ID:-0}

  if [ "$INSTALL_MODE" = "3" ]; then
    # Bot-only mode: ask for the remote Flask API base URL
    echo
    echo -e "${CYAN}This bot will NOT run its own Flask API — it needs the full API base URL of a Flask server running elsewhere.${NC}"
    echo "Example: https://iran.heysolo.ir/api/forex  (or http://SERVER_IP:45869/api/forex)"
    read -p "Enter the remote Flask API base URL: " REMOTE_API_BASE_URL
    while [ -z "$REMOTE_API_BASE_URL" ]; do
      read -p "This is required. Enter the remote Flask API base URL: " REMOTE_API_BASE_URL
    done
    # strip trailing slash, if any
    REMOTE_API_BASE_URL=${REMOTE_API_BASE_URL%/}
  fi

  # ============================================
  # سوال جدید: آیا پیام آنلاین شدن مجدد ارسال شود؟
  # ============================================
  echo
  echo -e "${CYAN}Do you want to send restart notification to all users when bot restarts?${NC}"
  echo "This will send a message to all users every time the bot service restarts."
  read -p "Enable restart notification? [y/N]: " SEND_RESTART_MSG_INPUT
  SEND_RESTART_MSG_INPUT=${SEND_RESTART_MSG_INPUT:-n}

  if [[ $SEND_RESTART_MSG_INPUT =~ ^[Yy]$ ]]; then
    SEND_RESTART_MSG="true"
    echo -e "${GREEN}✓ Restart notification will be sent to users.${NC}"
  else
    SEND_RESTART_MSG="false"
    echo -e "${YELLOW}✗ Restart notification disabled.${NC}"
  fi
fi


export DEBIAN_FRONTEND=noninteractive
unset GIT_ASKPASS
unset SSH_ASKPASS
export GIT_TERMINAL_PROMPT=0

apt update
if [ "$RUN_FLASK" = "true" ]; then
  apt install -y git python3 python3-venv python3-pip curl nginx
else
  # No nginx needed on a bot-only server (bot uses polling, not a webhook)
  apt install -y git python3 python3-venv python3-pip curl
fi


if [ ! -d "$APP_DIR/.git" ]; then
  rm -rf "$APP_DIR"
  git clone --depth 1 "$REPO_URL" "$APP_DIR" || {
    echo -e "${RED}Git clone failed. Check repository URL.${NC}"
    exit 1
  }
else
  cd "$APP_DIR"
  git pull || {
    echo -e "${RED}Git pull failed.${NC}"
    exit 1
  }
fi

cd "$APP_DIR"

# Old layout leftovers (files used to live in the project root)
rm -f "$APP_DIR/Dockerfile" "$APP_DIR/envshowrun"

python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

PUBLIC_BASE_URL=""
if [ -n "$DOMAIN_NAME" ]; then
  PUBLIC_BASE_URL="https://$DOMAIN_NAME"
elif [ "$RUN_FLASK" = "true" ]; then
  PUBLIC_BASE_URL="http://$(curl -4 -s --max-time 10 ifconfig.me/ip || echo YOUR_SERVER_IP)"
fi

# Local API_BASE_URL if Flask runs here, otherwise the remote URL the admin entered
if [ "$RUN_FLASK" = "true" ]; then
  API_BASE_URL="http://127.0.0.1:$FLASK_PORT/api/forex"
else
  API_BASE_URL="$REMOTE_API_BASE_URL"
fi

# .env is built by bot_settings.py (also moves an old forexbot.db into data/)
"$APP_DIR/.venv/bin/python" "$APP_DIR/bot_settings.py" set \
  "RUN_FLASK=$RUN_FLASK" \
  "FLASK_HOST=0.0.0.0" \
  "FLASK_PORT=$FLASK_PORT" \
  "FLASK_DEBUG=false" \
  "PUBLIC_BASE_URL=$PUBLIC_BASE_URL" \
  "RUN_BOT=$RUN_BOT" \
  "TELEGRAM_BOT_TOKEN=$TELEGRAM_BOT_TOKEN" \
  "ADMIN_CHAT_ID=$ADMIN_CHAT_ID" \
  "API_BASE_URL=$API_BASE_URL" \
  "SEND_RESTART_MSG=$SEND_RESTART_MSG"

if [ "$RUN_FLASK" = "true" ]; then
cat > /etc/systemd/system/flask.service <<EOF
[Unit]
Description=ForexFactory Flask API
After=network.target

[Service]
User=$SERVICE_USER
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/.env
ExecStart=$APP_DIR/.venv/bin/python $APP_DIR/api/flask_server.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable flask.service
systemctl restart flask.service
fi

if [ "$RUN_BOT" = "true" ]; then
AFTER_UNITS="network.target"
if [ "$RUN_FLASK" = "true" ]; then
  AFTER_UNITS="network.target flask.service"
fi

cat > /etc/systemd/system/telegram-bot.service <<EOF
[Unit]
Description=ForexFactory Telegram Bot
After=$AFTER_UNITS

[Service]
User=$SERVICE_USER
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/.env
ExecStart=$APP_DIR/.venv/bin/python $APP_DIR/bot/telegram_bot.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable telegram-bot.service
systemctl restart telegram-bot.service
fi

if [ "$RUN_FLASK" = "true" ]; then
# Website + API on one nginx site (template: website/nginx/site.conf.template)
SITE_DIR="$APP_DIR/website/content"
mkdir -p "$SITE_DIR/assets/downloads"
chmod 755 "$APP_DIR" "$APP_DIR/website" "$SITE_DIR"   # nginx (www-data) must reach the site folder
cp "$APP_DIR/website/nginx/ratelimit.conf" /etc/nginx/conf.d/forexfactory-ratelimit.conf
sed -e "s|__DOMAIN__|${DOMAIN_NAME:-_}|g" \
    -e "s|__ROOT__|$SITE_DIR|g" \
    -e "s|__FLASK_PORT__|$FLASK_PORT|g" \
    "$APP_DIR/website/nginx/site.conf.template" > /etc/nginx/sites-available/forexfactory-api

ln -sf /etc/nginx/sites-available/forexfactory-api /etc/nginx/sites-enabled/forexfactory-api
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl enable nginx
systemctl restart nginx

if [ -n "$DOMAIN_NAME" ]; then
  apt install -y certbot python3-certbot-nginx
  certbot --nginx --non-interactive --agree-tos -m "$CERTBOT_EMAIL" -d "$DOMAIN_NAME" --redirect || true
fi
fi


# ============================================
# بخش جدید: نمایش وضعیت و آموزش مدیریت سرویس
# ============================================

FLASK_STATUS="disabled"
if [ "$RUN_FLASK" = "true" ]; then
  FLASK_STATUS=$(systemctl is-active flask.service || true)
fi

BOT_STATUS="disabled"
if [ "$RUN_BOT" = "true" ]; then
  BOT_STATUS=$(systemctl is-active telegram-bot.service || true)
fi

SERVER_IP=$(curl -4 -s --max-time 10 ifconfig.me/ip || true)
if [ -z "$SERVER_IP" ]; then
  SERVER_IP=$(curl -4 -s --max-time 10 api.ipify.org || true)
fi
if [ -z "$SERVER_IP" ]; then
  SERVER_IP="YOUR_SERVER_IP"
fi

echo
echo -e "${CYAN}_________________________________${NC}"
echo -e "${CYAN}_________________________________${NC}"

if [ "$RUN_FLASK" = "true" ]; then
  if [ "$FLASK_STATUS" = "active" ]; then
    echo -e "${GREEN}Flask API: ACTIVE${NC}"
  else
    echo -e "${RED}Flask API: FAILED${NC}"
  fi
else
  echo -e "${YELLOW}Flask API: NOT INSTALLED (using remote: $REMOTE_API_BASE_URL)${NC}"
fi

if [ "$RUN_BOT" = "true" ]; then
  if [ "$BOT_STATUS" = "active" ]; then
    echo -e "${GREEN}Telegram Bot: ACTIVE${NC}"
  else
    echo -e "${RED}Telegram Bot: FAILED${NC}"
  fi
else
  echo -e "${YELLOW}Telegram Bot: DISABLED${NC}"
fi

# نمایش وضعیت ارسال پیام آنلاین شدن
if [ "$RUN_BOT" = "true" ]; then
  if [ "$SEND_RESTART_MSG" = "true" ]; then
    echo -e "${GREEN}Restart Notifications: ENABLED${NC}"
  else
    echo -e "${YELLOW}Restart Notifications: DISABLED${NC}"
  fi
fi


if [ "$RUN_FLASK" = "true" ]; then
  echo -e "${GREEN}Local API:${NC} http://127.0.0.1:$FLASK_PORT/api/forex/today"
  echo -e "${GREEN}Public IP API:${NC} http://$SERVER_IP/api/forex/today"

  if [ -n "$DOMAIN_NAME" ]; then
    echo -e "${GREEN}Domain API:${NC} https://$DOMAIN_NAME/api/forex/today"
  else
    echo -e "${YELLOW}Domain API:${NC} Not configured"
  fi
fi

echo -e "${CYAN}_________________________________${NC}"
echo -e "${CYAN}_________________________________${NC}"

# ============================================
# راهنمای مدیریت سرویس‌ها
# ============================================
echo -e "\n${CYAN}================== MANAGEMENT GUIDE ==================${NC}"
echo -e "${YELLOW}To check service status:${NC}"
if [ "$RUN_FLASK" = "true" ]; then
  echo "  systemctl status flask.service"
fi
if [ "$RUN_BOT" = "true" ]; then
  echo "  systemctl status telegram-bot.service"
fi

echo -e "\n${YELLOW}To stop a service:${NC}"
if [ "$RUN_FLASK" = "true" ]; then
  echo "  systemctl stop flask.service"
fi
if [ "$RUN_BOT" = "true" ]; then
  echo "  systemctl stop telegram-bot.service"
fi

echo -e "\n${YELLOW}To restart a service:${NC}"
if [ "$RUN_FLASK" = "true" ]; then
  echo "  systemctl restart flask.service"
fi
if [ "$RUN_BOT" = "true" ]; then
  echo "  systemctl restart telegram-bot.service"
fi

echo -e "\n${YELLOW}To view service logs:${NC}"
if [ "$RUN_FLASK" = "true" ]; then
  echo "  journalctl -u flask.service -f"
fi
if [ "$RUN_BOT" = "true" ]; then
  echo "  journalctl -u telegram-bot.service -f"
fi

# ============================================
# نمایش تنظیمات مربوط به پیام آنلاین شدن
# ============================================
if [ "$RUN_BOT" = "true" ]; then
  echo -e "\n${CYAN}================== RESTART NOTIFICATION SETTINGS ==================${NC}"
  echo -e "${YELLOW}To enable/disable restart notifications later:${NC}"
  echo "  $APP_DIR/.venv/bin/python $APP_DIR/bot_settings.py set SEND_RESTART_MSG=true   # or false"
  echo "  systemctl restart telegram-bot.service"
fi

echo -e "\n${CYAN}================== SETTINGS (bot_settings.py) ==================${NC}"
echo "  cd $APP_DIR && .venv/bin/python bot_settings.py        # interactive wizard"
echo "  cd $APP_DIR && .venv/bin/python bot_settings.py show   # show current config"

# Bot commands for switching the active Flask server
if [ "$RUN_BOT" = "true" ]; then
  echo -e "\n${CYAN}================== SWITCHING FLASK SERVERS FROM THE BOT ==================${NC}"
  echo -e "${YELLOW}As the admin (ADMIN_CHAT_ID), you can change which Flask API the bot uses at any time, without reinstalling:${NC}"
  echo "  /admin   → button panel: switch/add/delete Flask servers, 💾 full backup, ♻️ restore, 📦 EA versions"
  if [ "$RUN_FLASK" = "true" ]; then
    echo "  EA builds: send a .ex5 to the bot, it goes straight to the site's download page"
  fi
  echo "  /myid    → shows your chat ID (useful for setting ADMIN_CHAT_ID)"
  echo -e "${YELLOW}Current API base URL for this bot:${NC} $API_BASE_URL"
fi

echo -e "\n${GREEN}All services are installed and configured.${NC}"
