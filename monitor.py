#!/usr/bin/env python3
"""
Sagano Train Booker Telegram Bot
Interactive bot to monitor Sagano Scenic Railway availability.
"""

import os
import sys
import asyncio
import logging
from datetime import datetime, timedelta
from urllib.parse import urlencode
from typing import Set, Dict, List, Optional

from dotenv import load_dotenv
from playwright.async_api import async_playwright
from telegram import Update, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    JobQueue,
)
from telegram.constants import ParseMode

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

load_dotenv()

# Configuration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
# We don't strictly need a fixed CHAT_ID anymore as the bot interacts with users,
# but we can keep it as an admin fallback if needed.
SOURCE = os.getenv("SOURCE", "unknown")

BASE_URL = "https://file.sagano.linktivity.io/seat/51/down"

# Station options
STATIONS = {
    "saga": "Torokko Saga",
    "arashiyama": "Torokko Arashiyama",
    "hozukyo": "Torokko Hozukyo",
    "kameoka": "Torokko Kameoka",
}

# --- Data Structures ---

class UserConfig:
    def __init__(self):
        self.monitored_dates: Set[str] = set()
        self.departure = "Torokko Saga"
        self.arrival = "Torokko Kameoka"
        self.units = 1
        self.check_interval = 1  # minutes
        self.status_every = 60  # minutes (sends a summary every X minutes)
        
        # Runtime state
        self.last_status_time = datetime.min
        self.last_check_time = datetime.min
        self.notified_slots: Set[str] = set()

# ... (skip lines) ...

async def global_check_job(context: ContextTypes.DEFAULT_TYPE):
    """
    Runs every 60 seconds. Iterates through all users and checks their dates.
    """
    if not user_configs:
        return

    # Filter for active users (have dates)
    active_chats = [cid for cid, cfg in user_configs.items() if cfg.monitored_dates]
    
    if not active_chats:
        return

    logger.info(f"Running check cycle for {len(active_chats)} users")

    for chat_id in active_chats:
        config = user_configs[chat_id]
        now = datetime.now()

        # Check if it's time to run for this user
        if (now - config.last_check_time) < timedelta(minutes=config.check_interval):
            continue

        config.last_check_time = now
        
        # Cleanup past dates
        today_str = now.strftime("%Y-%m-%d")
        to_remove = [d for d in config.monitored_dates if d < today_str]
        for d in to_remove:
            config.monitored_dates.remove(d)
            await context.bot.send_message(chat_id, f"📅 Date {d} has passed. Removing from monitor.")
        
        if not config.monitored_dates:
            continue

        # Check each date
        for date in list(config.monitored_dates):
            result = await check_availability(
                date, config.departure, config.arrival, config.units
            )
            
            if result["error"]:
                logger.error(f"Error checking {date} for {chat_id}: {result['error']}")
                continue

            # Notify if new slots
            if result["available"]:
                # Filter slots we already notified
                new_slots = [
                    s for s in result["slots"] 
                    if f"{date}-{s}" not in config.notified_slots
                ]

                if new_slots:
                    url = build_url(date, config.units)
                    msg = (
                        f"🎉 <b>AVAILABLE!</b>\n"
                        f"📅 {date}\n"
                        f"⏰ {', '.join(new_slots)}\n"
                        f"🔗 <a href='{url}'>BOOK NOW</a>"
                    )
                    await context.bot.send_message(chat_id, msg, parse_mode=ParseMode.HTML)
                    
                    # Mark notified
                    for slot in new_slots:
                        config.notified_slots.add(f"{date}-{slot}")

            # (Logic for status update logic can remain similar or be adjusted if needed, 
            # but user didn't ask to change that drastically)
        
        # Send a summary for the user if time is right
        if (now - config.last_status_time) > timedelta(minutes=config.status_every):
            # Compile summary
            summary_lines = []
            for date in config.monitored_dates:
                summary_lines.append(f"Checked {date}: Still monitoring...")
            
            if summary_lines:
                msg = f"⏱ <b>Hourly Check-in</b>\n" + "\n".join(summary_lines)
                await context.bot.send_message(chat_id, msg, parse_mode=ParseMode.HTML)
                config.last_status_time = now

# In-memory storage: chat_id -> UserConfig
# In a real production app, use a database (SQLite/Postgres)
user_configs: Dict[int, UserConfig] = {}

# --- Helper Functions ---

def get_or_create_config(chat_id: int) -> UserConfig:
    if chat_id not in user_configs:
        user_configs[chat_id] = UserConfig()
    return user_configs[chat_id]

def build_url(date: str, units: int = 4) -> str:
    params = {
        "lang": "en",
        "date": date,
        "unitsCount": str(units),
        "backUrl": "https://ars-saganokanko.triplabo.jp/activity/en/LINKTIVITY-YRBTL",
        "redirectUrl": "https://ars-saganokanko.triplabo.jp/booking/pay",
        "currentStep": "station",
    }
    return f"{BASE_URL}?{urlencode(params)}"

# --- Core Logic (Async Playwright) ---

async def check_availability(
    date: str,
    departure: str,
    arrival: str,
    units: int
) -> dict:
    """Check availability for a single date using async Playwright."""
    result = {
        "date": date,
        "available": False,
        "slots": [],  # List[str] of available times
        "all_slots": [], # List of dicts with full info
        "error": None,
    }

    url = build_url(date, units)
    logger.info(f"Checking {date} ({departure}->{arrival})...")

    async with async_playwright() as p:
        try:
            browser = await p.chromium.launch(headless=True)
            # Create context with English locale
            context = await browser.new_context(locale="en-US")
            page = await context.new_page()
            
            try:
                await page.goto(url, wait_until="networkidle", timeout=30000)
                # Small buffer for dynamic content
                await page.wait_for_timeout(2000)

                # Select departure station
                # Note: The text might vary if the site language defaults to JP, 
                # but we set locale=en-US and URL param lang=en.
                await page.locator("text=Please select the departure station").first.click()
                await page.wait_for_timeout(500)
                await page.locator(f'[role="option"]:has-text("{departure}")').click()
                await page.wait_for_timeout(500)

                # Select arrival station
                await page.locator("text=Please select the arrival station").first.click()
                await page.wait_for_timeout(500)
                await page.locator(f'[role="option"]:has-text("{arrival}")').click()
                await page.wait_for_timeout(1500) # Wait for table load

                # Take screenshot for debugging if needed (overwrite)
                # await page.screenshot(path="latest_check.png", full_page=True)

                # Parse results
                # Look for train cards
                import re
                time_pattern = re.compile(r'(\d{2}:\d{2})')
                
                # Get all train info cards
                train_cards = await page.locator('div:has-text("Sagano")').all()
                
                seen_trains = set()
                
                # The page structure is complex, usually a card per train.
                # simpler approach: iterate all cards found
                for card in train_cards:
                    text = await card.inner_text()
                    times = time_pattern.findall(text)
                    train_match = re.search(r'Sagano \d+', text)

                    if len(times) >= 2 and train_match:
                        dep_time = times[0]
                        train_name = train_match.group()

                        if train_name in seen_trains:
                            continue
                        seen_trains.add(train_name)

                        # Check availability icon
                        # seatIconClose exists => Sold Out
                        has_close = await card.locator('svg[class*="seatIconClose"]').count() > 0
                        is_available = not has_close

                        slot_info = {
                            "time": dep_time,
                            "train": train_name,
                            "available": is_available,
                        }
                        result["all_slots"].append(slot_info)

                        if is_available:
                            result["available"] = True
                            result["slots"].append(f"{dep_time} ({train_name})")

            except Exception as e:
                logger.error(f"Page interaction error: {e}")
                result["error"] = str(e)
            finally:
                await browser.close()

        except Exception as e:
            logger.error(f"Browser launch error: {e}")
            result["error"] = str(e)

    return result

# --- Bot Commands ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a welcome message."""
    chat_id = update.effective_chat.id
    get_or_create_config(chat_id)
    
    msg = (
        "🚂 <b>Sagano Scenic Railway Monitor</b>\n\n"
        "I can help you book tickets by notifying you when seats open up.\n\n"
        "<b>Available Commands:</b>\n"
        "• /monitor <code>YYYY-MM-DD</code> - Start monitoring checks for a specific date.\n"
        "• /stop <code>[YYYY-MM-DD]</code> - Stop monitoring a date (or stop all if no date provided).\n"
        "• /list - See all dates you are currently watching.\n"
        "• /config - View your current settings (interval, route, seats).\n"
        "• <code>/config seats=2</code> - Set number of passengers.\n"
        "• <code>/config dep=arashiyama</code> - Set departure station.\n"
        "• <code>/config arr=kameoka</code> - Set arrival station.\n"
        "• <code>/config interval=30</code> - Set check frequency (in minutes).\n"
        "• /help - Show this guide again.\n\n"
        "<b>Defaults:</b>\n"
        "• 1 passenger\n"
        "• Torokko Saga → Torokko Kameoka\n"
        "• Checks every 1 minute\n\n"
        "<i>I check the website automatically and will alert you the moment a seat appears!</i>"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

async def monitor_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add a date to monitor."""
    chat_id = update.effective_chat.id
    config = get_or_create_config(chat_id)
    
    if not context.args:
        await update.message.reply_text("Usage: /monitor YYYY-MM-DD (e.g., /monitor 2025-12-05)")
        return

    date_str = context.args[0]
    try:
        # Validate date format
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        now = datetime.now()
        
        # Check past dates
        if dt.date() < now.date():
            await update.message.reply_text("❌ That date is in the past!")
            return

        # Check future limit (Sagano tickets open 1 month in advance)
        max_date = now + timedelta(days=32) # Give a small buffer just in case
        if dt > max_date:
            await update.message.reply_text(
                f"⚠️ Too far in the future!\n"
                f"Bookings usually open 1 month in advance.\n"
                f"Please monitor a date before {max_date.strftime('%Y-%m-%d')}."
            )
            return
            
        config.monitored_dates.add(date_str)
        
        # Schedule the job if not already running effectively
        # In this simple design, we have one global ticker that checks everyone's configs,
        # OR we could schedule a job per user. 
        # Simpler: One repeating job that iterates all users.
        
        await update.message.reply_text(f"✅ Added <b>{date_str}</b> to monitor list.", parse_mode=ParseMode.HTML)
        
    except ValueError:
        await update.message.reply_text("❌ Invalid format. Use YYYY-MM-DD.")

async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Stop monitoring a date or all dates."""
    chat_id = update.effective_chat.id
    config = get_or_create_config(chat_id)
    
    if not context.args:
        config.monitored_dates.clear()
        config.notified_slots.clear()
        await update.message.reply_text("🛑 Stopped monitoring ALL dates.")
        return

    date_str = context.args[0]
    if date_str in config.monitored_dates:
        config.monitored_dates.remove(date_str)
        # Clean up notified slots for this date to save memory
        config.notified_slots = {s for s in config.notified_slots if not s.startswith(date_str)}
        await update.message.reply_text(f"🛑 Stopped monitoring {date_str}.")
    else:
        await update.message.reply_text(f"⚠️ You weren't monitoring {date_str}.")

async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List monitored dates."""
    chat_id = update.effective_chat.id
    config = get_or_create_config(chat_id)
    
    if not config.monitored_dates:
        await update.message.reply_text("You are not monitoring any dates.")
        return
        
    dates_list = sorted(list(config.monitored_dates))
    msg = "📅 <b>Monitored Dates:</b>\n" + "\n".join(f"- {d}" for d in dates_list)
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

async def config_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View or update configuration."""
    chat_id = update.effective_chat.id
    config = get_or_create_config(chat_id)
    
    if not context.args:
        msg = (
            "⚙️ <b>Current Configuration:</b>\n\n"
            f"Interval: {config.check_interval}s\n"
            f"Status Update: Every {config.status_every} min\n"
            f"Route: {config.departure} → {config.arrival}\n"
            f"Seats: {config.units}\n\n"
            "<b>Available Stations:</b>\n" +
            ", ".join([f"<code>{s}</code>" for s in STATIONS.keys()]) + "\n\n"
            "<b>How to Change Settings:</b>\n"
            "• <code>/config seats=2</code> (Set number of passengers)\n"
            "• <code>/config dep=arashiyama</code> (Set start station)\n"
            "• <code>/config arr=kameoka</code> (Set end station)\n"
            "• <code>/config interval=30</code> (Set check frequency in minutes)\n\n"
            "<i>You can set multiple at once:</i>\n"
            "<code>/config seats=2 dep=kameoka arr=saga</code>"
        )
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
        return

    # Parse parameters
    for arg in context.args:
        # Interval
        if arg.startswith("interval="):
            try:
                val = int(arg.split("=")[1])
                if val < 1:
                    await update.message.reply_text("⚠️ Interval too low (min 1 minute).")
                    continue
                config.check_interval = val
                await update.message.reply_text(f"✅ Interval set to {val} minutes.")
            except ValueError:
                await update.message.reply_text("❌ Invalid interval check.")

        # Seats / Units
        elif arg.startswith("seats=") or arg.startswith("units="):
            try:
                val = int(arg.split("=")[1])
                if val < 1:
                    await update.message.reply_text("⚠️ Seats must be 1+.")
                    continue
                config.units = val
                await update.message.reply_text(f"✅ Seat count set to {val}.")
            except ValueError:
                await update.message.reply_text("❌ Invalid seat count.")

        # Departure / Arrival inputs handling
        # Simple string matching for stations
        elif arg.startswith("dep=") or arg.startswith("start="):
            query = arg.split("=")[1].lower()
            match = None
            # Scan dict values (full names)
            for key, name in STATIONS.items():
                if query in key or query in name.lower():
                    match = name
                    break
            
            if match:
                config.departure = match
                await update.message.reply_text(f"✅ Departure set to {match}.")
            else:
                formatted_stations = ", ".join(STATIONS.values())
                await update.message.reply_text(f"❌ Station not found. Options: {formatted_stations}")

        elif arg.startswith("arr=") or arg.startswith("end="):
            query = arg.split("=")[1].lower()
            match = None
            for key, name in STATIONS.items():
                if query in key or query in name.lower():
                    match = name
                    break
            
            if match:
                config.arrival = match
                await update.message.reply_text(f"✅ Arrival set to {match}.")
            else:
                formatted_stations = ", ".join(STATIONS.values())
                await update.message.reply_text(f"❌ Station not found. Options: {formatted_stations}")

# --- Job Queue ---

async def global_check_job(context: ContextTypes.DEFAULT_TYPE):
    """
    Runs every X seconds. Iterates through all users and checks their dates.
    To avoid hammering the server, we process sequentially or with limited concurrency.
    """
    if not user_configs:
        return

    # Filter for active users (have dates)
    active_chats = [cid for cid, cfg in user_configs.items() if cfg.monitored_dates]
    
    if not active_chats:
        return

    logger.info(f"Running check cycle for {len(active_chats)} users")

    for chat_id in active_chats:
        config = user_configs[chat_id]
        
        # Cleanup past dates
        today_str = datetime.now().strftime("%Y-%m-%d")
        to_remove = [d for d in config.monitored_dates if d < today_str]
        for d in to_remove:
            config.monitored_dates.remove(d)
            await context.bot.send_message(chat_id, f"📅 Date {d} has passed. Removing from monitor.")
        
        if not config.monitored_dates:
            continue

        # Check each date
        # Note: This is sequential per job run. 
        # If we have many users/dates, this function will take a long time.
        # Ideally, we should spawn individual jobs or limit dates per run.
        # For a personal bot, this is fine.
        for date in list(config.monitored_dates):
            result = await check_availability(
                date, config.departure, config.arrival, config.units
            )
            
            if result["error"]:
                logger.error(f"Error checking {date} for {chat_id}: {result['error']}")
                continue

            # Notify if new slots
            if result["available"]:
                # Filter slots we already notified
                new_slots = [
                    s for s in result["slots"] 
                    if f"{date}-{s}" not in config.notified_slots
                ]

                if new_slots:
                    url = build_url(date, config.units)
                    msg = (
                        f"🎉 <b>AVAILABLE!</b>\n"
                        f"📅 {date}\n"
                        f"⏰ {', '.join(new_slots)}\n"
                        f"🔗 <a href='{url}'>BOOK NOW</a>"
                    )
                    await context.bot.send_message(chat_id, msg, parse_mode=ParseMode.HTML)
                    
                    # Mark notified
                    for slot in new_slots:
                        config.notified_slots.add(f"{date}-{slot}")

            # Periodic status update (e.g. hourly)
            now = datetime.now()
            if (now - config.last_status_time) > timedelta(minutes=config.status_every):
                status_emoji = "✅" if result["available"] else "❌"
                # Only send if we haven't just sent a "success" notification separately?
                # Actually, user wants regular check-ins even if nothing new.
                
                # We update the timestamp once per user cycle, or once per date? 
                # Let's do once per user cycle to avoid spamming multiple dates.
                pass 
        
        # Send a summary for the user if time is right
        now = datetime.now()
        if (now - config.last_status_time) > timedelta(minutes=config.status_every):
            # Compile summary
            summary_lines = []
            for date in config.monitored_dates:
                summary_lines.append(f"Checked {date}: Still monitoring...")
            
            if summary_lines:
                msg = f"⏱ <b>Hourly Check-in</b>\n" + "\n".join(summary_lines)
                await context.bot.send_message(chat_id, msg, parse_mode=ParseMode.HTML)
                config.last_status_time = now


async def post_init(application: Application):
    """Set up the bot's command menu."""
    await application.bot.set_my_commands([
        ("start", "Start bot & show help"),
        ("monitor", "Monitor a date (format: YYYY-MM-DD)"),
        ("stop", "Stop monitoring a date"),
        ("list", "Show currently monitored dates"),
        ("config", "View or change settings"),
        ("help", "Show full help message"),
    ])

def main():
    """Start the bot."""
    if not TELEGRAM_BOT_TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN not found in .env")
        sys.exit(1)

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).build()

    # Commands
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", start_command))
    application.add_handler(CommandHandler("monitor", monitor_command))
    application.add_handler(CommandHandler("stop", stop_command))
    application.add_handler(CommandHandler("list", list_command))
    application.add_handler(CommandHandler("config", config_command))

    # Job Queue
    # Run every 60 seconds.
    # We could optimize this to respect user configured intervals, 
    # but a global tick is easier for a start.
    job_queue = application.job_queue
    job_queue.run_repeating(global_check_job, interval=60, first=10)

    print("Bot started. Press Ctrl+C to stop.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
