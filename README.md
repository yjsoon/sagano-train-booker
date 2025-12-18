# Sagano Train Booker Telegram Bot Maker

Monitor the [Sagano Scenic Railway](https://www.sagano-kanko.co.jp/en/) booking page and get Telegram notifications when seats become available. Seats often open up the day before travel, as cancellations are penalty-free until then.

## Quick Start

### 1. Create a Telegram Bot

1. Open Telegram and message [@BotFather](https://t.me/BotFather)
2. Send `/newbot` and follow the prompts
3. Copy the **API token** (looks like `123456789:ABCdefGHI...`)
4. Message your new bot and send any text (e.g., "hello")
5. Visit `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
6. Find your **Chat ID** in the response: `"chat":{"id":123456789}`

### 2. Clone and Setup

```bash
git clone https://github.com/yjsoon/sagano-train-booker.git
cd sagano-train-booker

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

### 3. Configure

```bash
cp .env.example .env
```

Edit `.env`:
```
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
SOURCE=my-computer
```

### 4. Run

```bash
python monitor.py
```

The bot is now fully interactive! Open your Telegram chat and use these commands:

- `/start` - Start and see instructions
- `/monitor <date>` - Start monitoring a date (e.g., `/monitor 2025-12-05`)
- `/list` - See observed dates
- `/config` - View and change settings (seats, stations, interval)
- `/stop` - Stop monitoring

### Configuration Defaults
- **Seats**: 1 passenger (change with `/config seats=2`)
- **Route**: Torokko Saga → Torokko Kameoka (change with `/config dep=... arr=...`)
- **Interval**: Checks every 1 minute (change with `/config interval=5`)

### 5. Run in Background

```bash
# Using nohup
nohup python -u monitor.py > monitor.log 2>&1 &
```

## Options

All configuration is done via Telegram commands now. No command-line arguments are needed.

## Docker

```bash
docker build -t sagano-monitor .
docker run -d --name sagano \
  -e TELEGRAM_BOT_TOKEN=your_token \
  -e SOURCE=docker \
  sagano-monitor
```

## GitHub Actions

The repo includes a GitHub Actions workflow that can run the script periodically, though the interactive bot mode is designed to run continuously on a server/computer.

## How It Works

1.  **Interactive Bot**: Listen for user commands via Telegram.
2.  **Job Queue**: Periodically checks availability for all monitored dates.
3.  **Smart Validation**: Prevents monitoring dates too far in the future (>1 month).
4.  **Notifications**: Alerts you instantly when a seat is found.

## Troubleshooting

**No notifications received?**
- Check your bot token is correct in `.env`.
- Make sure you've sent `/start` to the bot.

**All slots showing as unavailable?**
- The site may have changed its HTML structure.
- Check logs for errors.

## License

MIT
