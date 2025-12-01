#!/usr/bin/env python3
"""Monitor Sagano train booking page for available slots."""

import os
import sys
import time
import requests
from datetime import datetime
from playwright.sync_api import sync_playwright
from dotenv import load_dotenv

# Unbuffered output
sys.stdout.reconfigure(line_buffering=True)

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
SOURCE = os.getenv("SOURCE", "unknown")

BASE_URL = "https://file.sagano.linktivity.io/seat/51/down"
CHECK_INTERVAL = 60  # seconds between checks

# Station options
STATIONS = {
    "saga": "Torokko Saga",
    "arashiyama": "Torokko Arashiyama",
    "hozukyo": "Torokko Hozukyo",
    "kameoka": "Torokko Kameoka",
}


def build_url(date: str, units: int = 4) -> str:
    """Build the booking URL for a specific date."""
    from urllib.parse import urlencode
    params = {
        "lang": "en",
        "date": date,
        "unitsCount": str(units),
        "backUrl": "https://ars-saganokanko.triplabo.jp/activity/en/LINKTIVITY-YRBTL",
        "redirectUrl": "https://ars-saganokanko.triplabo.jp/booking/pay",
        "currentStep": "station",
    }
    return f"{BASE_URL}?{urlencode(params)}"


def send_telegram(message: str) -> bool:
    """Send a Telegram notification."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram credentials not configured")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
    }

    try:
        resp = requests.post(url, json=payload, timeout=10)
        if not resp.ok:
            print(f"Telegram error: {resp.text}")
        return resp.ok
    except Exception as e:
        print(f"Telegram error: {e}")
        return False


def check_availability(
    date: str,
    departure: str = "Torokko Saga",
    arrival: str = "Torokko Kameoka",
    units: int = 4,
) -> dict:
    """Check the booking page for available slots using Playwright."""
    result = {
        "available": False,
        "slots": [],
        "all_slots": [],
        "error": None,
    }

    url = build_url(date, units)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(2000)

            # Select departure station
            dep_dropdown = page.locator("text=Please select the departure station").first
            dep_dropdown.click()
            page.wait_for_timeout(500)
            page.locator(f'[role="option"]:has-text("{departure}")').click()
            page.wait_for_timeout(500)

            # Select arrival station
            arr_dropdown = page.locator("text=Please select the arrival station").first
            arr_dropdown.click()
            page.wait_for_timeout(500)
            page.locator(f'[role="option"]:has-text("{arrival}")').click()
            page.wait_for_timeout(1500)

            # Take screenshot for debugging
            page.screenshot(path="latest_check.png", full_page=True)

            # Find all train slot cards
            # Looking for elements that contain time patterns and availability info
            content = page.content()

            # Look for train cards - they contain departure time, train name, and availability
            train_cards = page.locator('[class*="card"], [class*="train"], [class*="slot"]').all()

            # Alternative: find all clickable elements with time patterns
            import re
            time_pattern = re.compile(r'(\d{2}:\d{2})')

            # Get all elements that look like train slots
            all_elements = page.locator("div").all()

            for elem in all_elements:
                try:
                    text = elem.inner_text()
                    # Check if this looks like a train slot (has times)
                    times = time_pattern.findall(text)
                    if len(times) >= 2 and "Sagano" in text:
                        # This is a train slot
                        dep_time = times[0]
                        is_unavailable = "Empty seat" in text or "✗" in text or "×" in text

                        # Extract train name
                        train_match = re.search(r'Sagano \d+', text)
                        train_name = train_match.group() if train_match else "Unknown"

                        slot_info = {
                            "time": dep_time,
                            "train": train_name,
                            "available": not is_unavailable,
                        }

                        # Avoid duplicates
                        if slot_info not in result["all_slots"]:
                            result["all_slots"].append(slot_info)

                            if not is_unavailable:
                                result["available"] = True
                                result["slots"].append(f"{dep_time} ({train_name})")
                except:
                    continue

            browser.close()

    except Exception as e:
        result["error"] = str(e)

    return result


def monitor(
    dates: list[str],
    departure: str = "Torokko Saga",
    arrival: str = "Torokko Kameoka",
    units: int = 4,
    interval: int = CHECK_INTERVAL,
    status_every: int = 10,
):
    """Continuously monitor the booking page."""
    print(f"Starting monitor for dates: {dates}")
    print(f"Route: {departure} → {arrival}")
    print(f"Units: {units}")
    print(f"Check interval: {interval} seconds")
    print(f"Status update every: {status_every} checks")
    print("-" * 50)

    # Send startup notification
    send_telegram(
        f"🚂 <b>Sagano Monitor Started</b>\n\n"
        f"📅 Dates: {', '.join(dates)}\n"
        f"🛤 Route: {departure} → {arrival}\n"
        f"👥 Seats: {units}\n\n"
        f"📍 Source: {SOURCE}"
    )

    notified_slots = set()  # Track what we've already notified about
    check_count = 0

    while True:
        check_count += 1
        for date in dates:
            timestamp = datetime.now().strftime("%H:%M:%S")

            print(f"[{timestamp}] Checking {date}...", end=" ")
            result = check_availability(date, departure, arrival, units)

            if result["error"]:
                print(f"❌ Error: {result['error']}")
                continue

            # Show all slots status
            slot_summary = []
            for slot in result["all_slots"]:
                status = "✅" if slot["available"] else "❌"
                slot_summary.append(f"{slot['time']}{status}")

            print(f"Slots: {', '.join(slot_summary) or 'None found'}")

            url = build_url(date, units)

            if result["available"]:
                # Check for new available slots we haven't notified about
                new_slots = [s for s in result["slots"] if f"{date}-{s}" not in notified_slots]

                if new_slots:
                    msg = (
                        f"🎉 <b>SAGANO TRAIN AVAILABLE!</b>\n\n"
                        f"📅 Date: {date}\n"
                        f"🛤 Route: {departure} → {arrival}\n"
                        f"🕐 Available: {', '.join(new_slots)}\n\n"
                        f"🔗 <a href='{url}'>BOOK NOW</a>\n\n"
                        f"📍 Source: {SOURCE}"
                    )
                    send_telegram(msg)
                    print(f"  📱 Notified about: {new_slots}")

                    # Mark as notified
                    for slot in new_slots:
                        notified_slots.add(f"{date}-{slot}")

            # Send periodic status update
            elif check_count % status_every == 0:
                times = ", ".join(s["time"] for s in result["all_slots"])
                msg = (
                    f"📊 <b>Status Update</b>\n\n"
                    f"📅 Date: {date}\n"
                    f"🕐 Checked: {times}\n"
                    f"All sold out for {units} seats.\n\n"
                    f"🔗 <a href='{url}'>Check anyway</a>\n\n"
                    f"📍 Source: {SOURCE}"
                )
                send_telegram(msg)
                print(f"  📱 Sent status update (check #{check_count})")

        print("-" * 50)
        time.sleep(interval)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Monitor Sagano train booking")
    parser.add_argument(
        "--dates",
        nargs="+",
        default=["2025-12-02"],
        help="Dates to monitor (YYYY-MM-DD format)",
    )
    parser.add_argument(
        "--departure",
        default="Torokko Saga",
        choices=list(STATIONS.values()),
        help="Departure station",
    )
    parser.add_argument(
        "--arrival",
        default="Torokko Kameoka",
        choices=list(STATIONS.values()),
        help="Arrival station",
    )
    parser.add_argument(
        "--units",
        type=int,
        default=4,
        help="Number of seats/units",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=CHECK_INTERVAL,
        help="Seconds between checks",
    )
    parser.add_argument(
        "--status-every",
        type=int,
        default=10,
        help="Send status update every N checks (default: 10 = every 10 min)",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Run a single check and exit",
    )
    parser.add_argument(
        "--test-telegram",
        action="store_true",
        help="Send a test Telegram message",
    )

    args = parser.parse_args()

    if args.test_telegram:
        print("Sending test Telegram message...")
        success = send_telegram("🧪 Test notification from Sagano Train Monitor")
        print(f"Success: {success}")
    elif args.test:
        # Single check mode - used by GitHub Actions
        for date in args.dates:
            print(f"Checking {date}...")
            print(f"Route: {args.departure} → {args.arrival}")
            print(f"Units: {args.units}")
            result = check_availability(date, args.departure, args.arrival, args.units)

            # Show all slots status
            for slot in result["all_slots"]:
                status = "✅ AVAILABLE" if slot["available"] else "❌"
                print(f"  {slot['time']} ({slot['train']}): {status}")

            if result["error"]:
                print(f"Error: {result['error']}")

            # Send notification
            url = build_url(date, args.units)
            if result["available"]:
                msg = (
                    f"🎉 <b>SAGANO TRAIN AVAILABLE!</b>\n\n"
                    f"📅 Date: {date}\n"
                    f"🛤 Route: {args.departure} → {args.arrival}\n"
                    f"🕐 Available: {', '.join(result['slots'])}\n\n"
                    f"🔗 <a href='{url}'>BOOK NOW</a>\n\n"
                    f"📍 Source: {SOURCE}"
                )
            else:
                slot_summary = ", ".join(f"{s['time']}" for s in result["all_slots"])
                msg = (
                    f"😔 <b>No availability</b>\n\n"
                    f"📅 Date: {date}\n"
                    f"🕐 Checked: {slot_summary}\n"
                    f"All sold out for {args.units} seats.\n\n"
                    f"🔗 <a href='{url}'>Check anyway</a>\n\n"
                    f"📍 Source: {SOURCE}"
                )
            send_telegram(msg)
            print("📱 Telegram notification sent!")
    else:
        monitor(args.dates, args.departure, args.arrival, args.units, args.interval, args.status_every)
