#!/usr/bin/env python3
"""
HiveOS Mining Price Controller
================================
Automatically stops/starts your HiveOS miner based on Norwegian spot electricity prices.
Uses hvakosterstrommen.no for free live price data and the HiveOS REST API v2 for control.

SETUP:
  pip install requests

USAGE:
  python3 mining_price_controller.py

  Edit the CONFIG section below before running.
"""

import requests
import time
import logging
from datetime import datetime, timezone

# CONFIG 


# HiveOS API credentials
# Get your Personal Access Token from: https://the.hiveos.farm/ → Account → API
HIVEOS_API_TOKEN = "YOUR_HIVEOS_API_TOKEN_HERE"

# Your Farm ID and Worker ID )
FARM_ID    = 12345   
WORKER_ID  = 67890  

# Norwegian price zone: Eastern Norway
PRICE_ZONE = "NO1"

# Price threshold in øre/kWh (NOK per kWh × 100)
# Mining stops when the current price is ABOVE this value.
# Mining starts again whn the price drops BACK BELOW it.
PRICE_THRESHOLD_ORE = 50.0

# How often it checks the price, in seconds.
CHECK_INTERVAL_SECONDS = 300



HIVEOS_API_BASE = "https://api2.hiveos.farm/api/v2"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


#  Electricity price 

def get_current_price_ore(zone: str) -> float:
    """
    Fetch the current hour's spot price from hvakosterstrommen.no.
    Returns the price in øre/kWh (NOK × 100).
    """
    now = datetime.now(tz=timezone.utc)
    url = (
        f"https://www.hvakosterstrommen.no/api/v1/prices/"
        f"{now.year}/{now.month:02d}-{now.day:02d}_{zone}.json"
    )
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    prices = resp.json()  

    current_hour = now.hour
    for entry in prices:
        # time_start is ISO 8601, e.g. "2024-03-23T12:00:00+01:00"
        start = datetime.fromisoformat(entry["time_start"])
        if start.astimezone(timezone.utc).hour == current_hour:
            # NOK_per_kWh → øre/kWh
            return entry["NOK_per_kWh"] * 100

    
    return prices[-1]["NOK_per_kWh"] * 100


# HiveOS control 

def hiveos_headers() -> dict:
    return {
        "Authorization": f"Bearer {HIVEOS_API_TOKEN}",
        "Content-Type": "application/json",
    }


def get_worker_status() -> dict | None:
    """Return the worker info dict or None on error."""
    url = f"{HIVEOS_API_BASE}/farms/{FARM_ID}/workers/{WORKER_ID}"
    try:
        resp = requests.get(url, headers=hiveos_headers(), timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        log.error("Failed to get worker status: %s", exc)
        return None


def is_miner_running() -> bool | None:
    """Returns True if miner is active, False if stopped, None on API error."""
    worker = get_worker_status()
    if worker is None:
        return None
    # miners_summary is a list; if empty or all stopped, miner is not running
    miners = worker.get("miners_summary", [])
    return any(m.get("is_running", False) for m in miners)


def send_miner_action(action: str) -> bool:
    """
    Send a miner action to the worker via HiveOS API.
    action: "miner_start" | "miner_stop"
    Returns True on success.
    """
    url = f"{HIVEOS_API_BASE}/farms/{FARM_ID}/workers/{WORKER_ID}/command"
    payload = {"command": action}
    try:
        resp = requests.post(url, json=payload, headers=hiveos_headers(), timeout=15)
        resp.raise_for_status()
        log.info("HiveOS command '%s' sent successfully.", action)
        return True
    except requests.HTTPError as exc:
        log.error("HiveOS API error sending '%s': %s — %s", action, exc, exc.response.text)
        return False
    except Exception as exc:
        log.error("Unexpected error sending '%s': %s", action, exc)
        return False


def stop_miner():
    log.warning("Stopping miner (price too high).")
    send_miner_action("miner_stop")


def start_miner():
    log.info("Starting miner (price back in range).")
    send_miner_action("miner_start")


# Main loop

def main():
    log.info("=" * 60)
    log.info("HiveOS Mining Price Controller started")
    log.info("  Zone       : %s (Kongsvinger / Eastern Norway)", PRICE_ZONE)
    log.info("  Threshold  : %.1f øre/kWh", PRICE_THRESHOLD_ORE)
    log.info("  Farm ID    : %d  |  Worker ID: %d", FARM_ID, WORKER_ID)
    log.info("  Interval   : %d seconds", CHECK_INTERVAL_SECONDS)
    log.info("=" * 60)

    # Track the last action we took so we don't spam the API
    last_action: str | None = None  # "stopped" | "started"

    while True:
        try:
            price = get_current_price_ore(PRICE_ZONE)
            log.info(
                "Current price: %.2f øre/kWh  (threshold: %.1f øre/kWh)",
                price,
                PRICE_THRESHOLD_ORE,
            )

            if price > PRICE_THRESHOLD_ORE:
                if last_action != "stopped":
                    stop_miner()
                    last_action = "stopped"
                else:
                    log.info("Miner already stopped — no action needed.")
            else:
                if last_action != "started":
                    start_miner()
                    last_action = "started"
                else:
                    log.info("Miner already running — no action needed.")

        except requests.RequestException as exc:
            log.error("Network error fetching price: %s (will retry)", exc)
        except Exception as exc:
            log.exception("Unexpected error in main loop: %s", exc)

        time.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
