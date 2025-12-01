# Sagano Train Booker

Monitor the Sagano Scenic Railway booking page and get Telegram notifications when seats become available.

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
# Single check (test mode)
python monitor.py --test --dates 2025-12-02

# Continuous monitoring
python monitor.py --dates 2025-12-02

# Multiple dates
python monitor.py --dates 2025-12-02 2025-12-03 2025-12-04

# Custom options
python monitor.py --dates 2025-12-02 \
  --departure "Torokko Saga" \
  --arrival "Torokko Kameoka" \
  --units 4 \
  --interval 60 \
  --status-every 10
```

### 5. Run in Background

```bash
# Using nohup
nohup python -u monitor.py --dates 2025-12-02 > monitor.log 2>&1 &

# Using tmux
tmux new-session -d -s sagano 'cd ~/sagano-train-booker && source .venv/bin/activate && python monitor.py --dates 2025-12-02'

# View logs
tail -f monitor.log

# Stop
pkill -f "monitor.py"
```

## Options

| Flag | Default | Description |
|------|---------|-------------|
| `--dates` | Required | Dates to monitor (YYYY-MM-DD) |
| `--departure` | Torokko Saga | Departure station |
| `--arrival` | Torokko Kameoka | Arrival station |
| `--units` | 1 | Number of seats |
| `--interval` | 60 | Seconds between checks |
| `--status-every` | 10 | Send status update every N checks |
| `--test` | - | Single check mode |
| `--test-telegram` | - | Test Telegram notification |

### Stations

- Torokko Saga
- Torokko Arashiyama
- Torokko Hozukyo
- Torokko Kameoka

## Docker

```bash
docker build -t sagano-monitor .
docker run -d --name sagano \
  -e TELEGRAM_BOT_TOKEN=your_token \
  -e TELEGRAM_CHAT_ID=your_chat_id \
  -e SOURCE=docker \
  sagano-monitor --dates 2025-12-02
```

## GitHub Actions (Free)

The repo includes a GitHub Actions workflow. Note: GitHub's cron is best-effort and typically runs every 15-30 minutes (not guaranteed).

1. Fork this repo
2. Go to Settings → Secrets → Actions
3. Add `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`
4. Edit `.github/workflows/monitor.yml` to set your dates
5. Enable the workflow in Actions tab

For more reliable monitoring, run locally or on a VPS.

## How It Works

1. Uses Playwright to load the booking page
2. Selects departure/arrival stations
3. Checks each train slot for the `seatIconClose` SVG class (indicates sold out)
4. Sends Telegram notification when available slots are found
5. Repeats every N seconds

## Troubleshooting

**No notifications received?**
- Check your bot token and chat ID are correct
- Run `python monitor.py --test-telegram` to test
- Make sure you've messaged your bot at least once

**All slots showing as unavailable?**
- The site may have changed its HTML structure
- Check `latest_check.png` screenshot for debugging
- Open an issue with details

## License

MIT
