#!/usr/bin/env bash
set -e

APP_DIR="/opt/forexfactory-api"
SERVICE_USER="root"

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${RED}========================================${NC}"
echo -e "${RED}    UNINSTALL FOREXFACTORY API${NC}"
echo -e "${RED}========================================${NC}"
echo

# بررسی وجود پروژه
if [ ! -d "$APP_DIR" ]; then
    echo -e "${YELLOW}Project directory $APP_DIR does not exist.${NC}"
    echo -e "${YELLOW}Nothing to uninstall.${NC}"
    exit 0
fi

echo -e "${YELLOW}WARNING: This will permanently delete:${NC}"
echo "  - Flask API service"
if systemctl list-units --full -all | grep -q "telegram-bot.service"; then
    echo "  - Telegram Bot service"
fi
echo "  - Nginx configuration for forexfactory-api"
if [ -f /etc/nginx/sites-available/forexfactory-api ]; then
    echo "  - Nginx site configuration"
fi
echo "  - All project files in $APP_DIR"
echo "  - Python virtual environment"
echo "  - Environment variables (.env file)"
echo

read -p "Are you sure you want to continue? [y/N]: " CONFIRM
CONFIRM=${CONFIRM:-N}

if [[ ! "$CONFIRM" =~ ^[Yy]$ ]]; then
    echo -e "${GREEN}Uninstall cancelled.${NC}"
    exit 0
fi

echo -e "\n${CYAN}Starting uninstall process...${NC}"

# 1. توقف و حذف سرویس Flask
echo -e "${YELLOW}Stopping and removing Flask service...${NC}"
if systemctl is-active --quiet flask.service; then
    systemctl stop flask.service
    echo -e "${GREEN}✓ Flask service stopped${NC}"
else
    echo -e "${YELLOW}⚠ Flask service was not running${NC}"
fi

if systemctl is-enabled --quiet flask.service 2>/dev/null; then
    systemctl disable flask.service
    echo -e "${GREEN}✓ Flask service disabled${NC}"
fi

if [ -f /etc/systemd/system/flask.service ]; then
    rm -f /etc/systemd/system/flask.service
    echo -e "${GREEN}✓ Flask service file removed${NC}"
fi

# 2. توقف و حذف سرویس Telegram Bot (در صورت وجود)
if systemctl list-units --full -all | grep -q "telegram-bot.service"; then
    echo -e "${YELLOW}Stopping and removing Telegram Bot service...${NC}"
    if systemctl is-active --quiet telegram-bot.service; then
        systemctl stop telegram-bot.service
        echo -e "${GREEN}✓ Telegram Bot service stopped${NC}"
    else
        echo -e "${YELLOW}⚠ Telegram Bot service was not running${NC}"
    fi
    
    if systemctl is-enabled --quiet telegram-bot.service 2>/dev/null; then
        systemctl disable telegram-bot.service
        echo -e "${GREEN}✓ Telegram Bot service disabled${NC}"
    fi
    
    if [ -f /etc/systemd/system/telegram-bot.service ]; then
        rm -f /etc/systemd/system/telegram-bot.service
        echo -e "${GREEN}✓ Telegram Bot service file removed${NC}"
    fi
fi

# 3. ری‌لود systemd
systemctl daemon-reload
echo -e "${GREEN}✓ Systemd reloaded${NC}"

# 4. حذف Nginx configuration
echo -e "${YELLOW}Removing Nginx configuration...${NC}"
if [ -f /etc/nginx/sites-available/forexfactory-api ]; then
    rm -f /etc/nginx/sites-available/forexfactory-api
    echo -e "${GREEN}✓ Nginx site config removed from sites-available${NC}"
fi

if [ -f /etc/nginx/sites-enabled/forexfactory-api ]; then
    rm -f /etc/nginx/sites-enabled/forexfactory-api
    echo -e "${GREEN}✓ Nginx site config removed from sites-enabled${NC}"
fi

# 5. ری‌استارت Nginx (در صورت نصب بودن)
if command -v nginx &> /dev/null; then
    nginx -t 2>/dev/null && systemctl restart nginx || echo -e "${YELLOW}⚠ Nginx configuration test failed, skipping restart${NC}"
    echo -e "${GREEN}✓ Nginx restarted${NC}"
fi

# 6. حذف SSL Certificate (در صورت وجود)
if [ -n "$DOMAIN_NAME" ] && [ -d "/etc/letsencrypt/live/$DOMAIN_NAME" ]; then
    echo -e "${YELLOW}Removing SSL certificates for $DOMAIN_NAME...${NC}"
    if command -v certbot &> /dev/null; then
        certbot delete --cert-name "$DOMAIN_NAME" --non-interactive 2>/dev/null || true
        echo -e "${GREEN}✓ SSL certificates removed${NC}"
    fi
fi

# 7. حذف دایرکتوری پروژه
echo -e "${YELLOW}Removing project directory...${NC}"
if [ -d "$APP_DIR" ]; then
    rm -rf "$APP_DIR"
    echo -e "${GREEN}✓ Project directory removed${NC}"
fi

# 8. حذف وابستگی‌های اختیاری (اختیاری)
echo -e "\n${YELLOW}Do you want to remove Python packages and system dependencies?${NC}"
echo "  This will remove: python3-venv, python3-pip, git, nginx, certbot"
echo "  (Recommended only if no other projects use them)"
read -p "Remove system packages? [y/N]: " REMOVE_PKGS
REMOVE_PKGS=${REMOVE_PKGS:-N}

if [[ "$REMOVE_PKGS" =~ ^[Yy]$ ]]; then
    echo -e "${YELLOW}Removing system packages...${NC}"
    apt remove -y python3-venv python3-pip git nginx certbot python3-certbot-nginx 2>/dev/null || true
    apt autoremove -y
    echo -e "${GREEN}✓ System packages removed${NC}"
fi

echo -e "\n${GREEN}========================================${NC}"
echo -e "${GREEN}    UNINSTALL COMPLETED SUCCESSFULLY${NC}"
echo -e "${GREEN}========================================${NC}"
echo
echo -e "${CYAN}Summary of removed items:${NC}"
echo -e "${GREEN}✓${NC} Flask API service"
if systemctl list-units --full -all | grep -q "telegram-bot.service"; then
    echo -e "${GREEN}✓${NC} Telegram Bot service"
fi
echo -e "${GREEN}✓${NC} Nginx configuration"
if [ -n "$DOMAIN_NAME" ]; then
    echo -e "${GREEN}✓${NC} SSL certificates (if any)"
fi
echo -e "${GREEN}✓${NC} Project files in $APP_DIR"
echo -e "${GREEN}✓${NC} Virtual environment"
echo -e "${GREEN}✓${NC} Environment variables"
if [[ "$REMOVE_PKGS" =~ ^[Yy]$ ]]; then
    echo -e "${GREEN}✓${NC} System packages (python3-venv, python3-pip, git, nginx, certbot)"
fi
echo
echo -e "${CYAN}To verify removal:${NC}"
echo "  systemctl status flask.service  # should show 'not found'"
echo "  systemctl status telegram-bot.service  # should show 'not found'"
echo "  ls -la $APP_DIR  # should show 'No such file or directory'"
echo
