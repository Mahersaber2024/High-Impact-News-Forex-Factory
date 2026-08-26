# ForexFactory Flask API + Telegram Bot

A lightweight Flask API for ForexFactory high-impact news, with optional Telegram bot support and optional domain-based HTTPS access for external clients such as MetaTrader 5.

Sponsor: [@HeySoloATM](https://t.me/HeySoloATM)

## Features

- Flask API for ForexFactory economic calendar data
- Optional Telegram bot
- Public API access through server IP
- Optional domain setup with Nginx reverse proxy
- Optional HTTPS with Let's Encrypt and Certbot
- Interactive installer with systemd service setup
- Flask API and Telegram bot can run on **separate servers**; the bot admin can switch which Flask API the bot uses at runtime, without reinstalling

## Files

- `flask_server.py` → Flask API
- `telegram_bot.py` → Optional Telegram bot
- `forexFactoryScrapper.py` → Scraper logic
- `requirements.txt` → Python dependencies
- `install.sh` → Interactive installer
- `.env` → Runtime configuration

## Quick Install

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/Mahersaber2024/High-Impact-News-Forex-Factory/main/install.sh)
```

## Installer Prompts

The installer supports three modes:

1. **Flask only** — runs just the Flask API on this server (no bot). Use this on the server that hosts the data, e.g. `iran.heysolo.ir`.
2. **Flask + Telegram Bot** — both run together on the same server.
3. **Telegram Bot only** — runs just the bot on this server, and points it at a Flask API running on a *different* server. Use this when the bot server and the Flask API server are separate machines.

Depending on the mode chosen, it asks for:

- Flask port (modes 1 and 2)
- Optional domain name for HTTPS, e.g. `iran.heysolo.ir` (modes 1 and 2)
- SSL email address if a domain is provided (modes 1 and 2)
- Telegram bot token (modes 2 and 3)
- Telegram admin chat ID (modes 2 and 3)
- The remote Flask API base URL, e.g. `https://iran.heysolo.ir/api/forex` (mode 3 only)
- Whether to send a restart notification to users (modes 2 and 3)

If you press Enter on the domain question, domain setup is skipped.

## API Endpoints

- `/api/forex/today`
- `/api/forex/tomorrow`
- `/api/forex/weekly`

Example:

```bash
curl http://127.0.0.1:45869/api/forex/today
```

## API Access Modes

### Local access

```text
http://127.0.0.1:45869/api/forex/today
```

### Public access by server IP

If Nginx is installed and running on port 80, the API can be accessed from outside the server using:

```text
http://YOUR_SERVER_IP/api/forex/today
```

Example:

```text
http://185.28.119.231/api/forex/today
```

### Public access by domain

If you provide a domain during installation and its DNS points to your server, the installer configures Nginx and tries to obtain an SSL certificate automatically.

Example:

```text
https://news.example.com/api/forex/today
```

## MetaTrader 5

If you are using direct server IP access:

```mql5
input string NewsURL = "http://YOUR_SERVER_IP";
```

If you are using a domain with HTTPS:

```mql5
input string NewsURL = "https://news.example.com";
```

Then your EA can request:

```text
/api/forex/today
```

## Services

The installer creates these systemd services (depending on the mode chosen):

- `flask.service`
- `telegram-bot.service` only if bot mode is enabled

Check service status:

```bash
sudo systemctl status flask.service
sudo systemctl status telegram-bot.service
```

Restart services:

```bash
sudo systemctl restart flask.service
sudo systemctl restart telegram-bot.service
```

View logs:

```bash
sudo journalctl -u flask.service -n 100 --no-pager
sudo journalctl -u telegram-bot.service -n 100 --no-pager
```

## Running Flask and the Bot on Separate Servers

You don't have to run the Flask API and the Telegram bot on the same machine. A common setup:

- **Server A (data server)**: run the installer, choose mode **1) Flask only**, and give it the domain `iran.heysolo.ir`. This exposes:

```text
https://iran.heysolo.ir/api/forex/today
https://iran.heysolo.ir/api/forex/tomorrow
https://iran.heysolo.ir/api/forex/weekly
```

- **Server B (bot server)**: run the installer, choose mode **3) Telegram Bot only**, and when asked for the remote Flask API base URL, enter:

```text
https://iran.heysolo.ir/api/forex
```

Server B only installs Python, the venv, and the `telegram-bot.service` — no Flask, no Nginx.

### Letting the admin switch Flask servers from inside the bot

Once the bot is running, the Telegram user whose chat ID matches `ADMIN_CHAT_ID` can change which Flask API the bot talks to at any time, straight from a button menu — no redeploy, no restart needed.

Just send `/admin` in the bot and everything is done with buttons:

- **🔀 Switch server** — shows all saved servers, tap one to make it active instantly
- **➕ Add server** — bot asks for `name https://url`, you reply with one message and it's saved
- **🗑 Delete server** — tap a saved server to remove it

There's also a standalone `/myid` command that shows your chat ID, useful the first time you're setting `ADMIN_CHAT_ID`.

The active URL is stored in the bot's local SQLite database (`forexbot.db`), so it survives bot restarts, and it overrides the `API_BASE_URL` value from `.env` once set. Only the configured `ADMIN_CHAT_ID` can use these commands; everyone else is ignored.

This is useful if you run several Flask servers (e.g. one in Iran, one elsewhere) and want to fail over or switch between them without touching the server.

## Domain Setup Later

If you skip the domain during installation, you can add it later.

### 1. Point DNS to your server

Create an `A` record for your domain or subdomain and point it to your server IP.

Example:

- `news.example.com` → `185.28.119.231`

### 2. Install Nginx and Certbot

```bash
sudo apt update
sudo apt install -y nginx certbot python3-certbot-nginx
```

### 3. Create Nginx config

Replace `news.example.com` with your real domain and `45869` with your Flask port if different.

```bash
sudo tee /etc/nginx/sites-available/forexfactory-api > /dev/null <<'EOF'
server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name news.example.com;

    ssl_certificate /etc/letsencrypt/live/news.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/news.example.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:45869;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
EOF
```

Enable it:

```bash
sudo ln -sf /etc/nginx/sites-available/forexfactory-api /etc/nginx/sites-enabled/forexfactory-api
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl restart nginx
```

### 4. Get SSL certificate

If the certificate is not created yet, run:

```bash
sudo certbot --nginx -d news.example.com
```

After successful issuance, your API should be available at:

```text
https://news.example.com/api/forex/today
```

### 5. Optional: update `.env`

If you want to store the public base URL in the app config:

```bash
sudo nano /opt/forexfactory-api/.env
```

Set:

```env
PUBLIC_BASE_URL=https://news.example.com
```

Then restart Flask:

```bash
sudo systemctl restart flask.service
```

## Troubleshooting

### Flask is not starting

Check logs:

```bash
sudo journalctl -u flask.service -n 100 --no-pager
```

### Telegram bot is running but news is not received

Make sure Flask is active first, because the bot depends on the API.

### HTTPS does not open

Check these items:

- Domain DNS is pointed to the correct server IP
- Port 443 is open
- Nginx is listening on 443
- No other service is using port 443
- SSL certificate files exist in `/etc/letsencrypt/live/news.example.com/`

Then test again:

```bash
sudo ss -tlnp | grep ':443'
curl -I https://news.example.com/api/forex/today
```

## Uninstall

To completely remove the application and all installed services:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/Mahersaber2024/High-Impact-News-Forex-Factory/main/uninstall.sh)
```

The uninstall script will:

- Remove `flask.service`
- Remove `telegram-bot.service` (if installed)
- Remove Nginx configuration
- Remove project files and virtual environment
- Optionally remove Nginx, Certbot, Git and Python packages

After removal, verify:

```bash
systemctl status flask.service
systemctl status telegram-bot.service
```

Expected output:

```text
Unit flask.service could not be found.
Unit telegram-bot.service could not be found.
```

## Notes

- This setup uses HTTPS only on port 443.
- Do not paste Markdown links inside Nginx config. Use plain text only.
- If you do not need the Telegram bot, choose Flask only during install.
- If Flask runs on a different server than the bot, choose Telegram Bot only during install and point it at the remote API URL — see "Running Flask and the Bot on Separate Servers" above.
