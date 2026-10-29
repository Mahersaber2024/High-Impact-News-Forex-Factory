import logging
import pathlib
import sys

# Make the project root importable (for bot_settings / api package)
ROOT_DIR = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from flask import Flask, jsonify, request
from datetime import datetime, timedelta
import pytz
from werkzeug.exceptions import HTTPException

import bot_settings as cfg
from api.forexFactoryScrapper import getRecords, getURL, get_start_of_week, ALL_IMPACTS

HOST = cfg.FLASK_HOST
PORT = cfg.FLASK_PORT
DEBUG = cfg.FLASK_DEBUG

# Configure logging to display information in the console
logging.basicConfig(level=logging.INFO)

app = Flask(__name__)

# Cache for storing data
cache = {
    "today": {"data": None, "last_update": None},
    "weekly": {"data": None, "last_update": None, "last_day": None},  # Added last_day for weekly cache
    "tomorrow": {"data": None, "last_update": None},
    "yesterday": {"data": None, "last_update": None}
}
NY = pytz.timezone("America/New_York")

@app.errorhandler(Exception)
def api_error(error):
    if isinstance(error, HTTPException):
        return error
    logging.exception("Calendar source failed")
    return jsonify({"error": "Calendar source unavailable"}), 503

CACHE_DURATION = timedelta(hours=1)  # Cache validity duration for today and tomorrow
DAILY_UPDATE_HOUR = 0  # Start of day (e.g. 00:00) for refreshing weekly data

def _wanted_impacts() -> set[str]:
    """?impact=high,medium,low (or all). No parameter = High only, so the EA keeps getting exactly what it always got."""
    raw = (request.args.get("impact") or "high").lower()
    if raw == "all":
        return set(ALL_IMPACTS)
    wanted = {lvl for lvl in ALL_IMPACTS if lvl.lower() in {p.strip() for p in raw.split(",")}}
    return wanted or {"High"}

def _respond(records):
    wanted = _wanted_impacts()
    return jsonify([r for r in (records or []) if r.get("Impact") in wanted]), 200

def is_cache_valid(last_update, cache_key):
    """Check whether the cached data is still valid."""
    if last_update is None:
        return False
    if cache_key == "weekly":
        # For weekly data, check whether the day has changed
        current_day = datetime.now(NY).date()
        last_day = cache[cache_key].get("last_day")
        if last_day != current_day:
            logging.info(f"Day changed from {last_day} to {current_day}, invalidating weekly cache.")
            return False
        valid = datetime.now(NY) - last_update < timedelta(days=1)
    else:
        if last_update.date() != datetime.now(NY).date():
            return False
        valid = datetime.now(NY) - last_update < CACHE_DURATION
    logging.info(f"Cache valid: {valid}, Last update: {last_update}, Current time: {datetime.now()}")
    return valid

@app.route('/api/forex/today', methods=['GET'])
def today_data():
    today = datetime.now(NY)

    if is_cache_valid(cache["today"]["last_update"], "today"):
        logging.info("Returning cached data for today.")
        return _respond(cache["today"]["data"])

    logging.info("Fetching new data for today.")
    url = getURL(today, 'day')
    record_json = getRecords(url, today, ALL_IMPACTS)
    
    cache["today"] = {"data": record_json, "last_update": datetime.now(NY)}
    
    return _respond(record_json)

@app.route('/api/forex/weekly', methods=['GET'])
def weekly_data():
    today = datetime.now(NY)
    start_of_week = get_start_of_week(today)

    if is_cache_valid(cache["weekly"]["last_update"], "weekly"):
        logging.info("Returning cached data for weekly.")
        return _respond(cache["weekly"]["data"])

    logging.info("Fetching new data for weekly.")
    url = getURL(start_of_week, 'week')
    record_json = getRecords(url, start_of_week, ALL_IMPACTS)

    # Update cache with the current day
    cache["weekly"] = {
        "data": record_json,
        "last_update": datetime.now(NY),
        "last_day": datetime.now(NY).date()
    }

    return _respond(record_json)

@app.route('/api/forex/tomorrow', methods=['GET'])
def tomorrow_data():
    tomorrow = datetime.now(NY) + timedelta(days=1)

    if is_cache_valid(cache["tomorrow"]["last_update"], "tomorrow"):
        logging.info("Returning cached data for tomorrow.")
        return _respond(cache["tomorrow"]["data"])

    logging.info("Fetching new data for tomorrow.")
    url = getURL(tomorrow, 'day')
    record_json = getRecords(url, tomorrow, ALL_IMPACTS)

    cache["tomorrow"] = {"data": record_json, "last_update": datetime.now(NY)}
    
    return _respond(record_json)

@app.route('/api/forex/yesterday', methods=['GET'])
def yesterday_data():
    day = datetime.now(NY) - timedelta(days=1)
    if is_cache_valid(cache["yesterday"]["last_update"], "yesterday"):
        return _respond(cache["yesterday"]["data"])
    records = getRecords(getURL(day, 'day'), day, ALL_IMPACTS)
    cache["yesterday"] = {"data": records, "last_update": datetime.now(NY)}
    return _respond(records)

if __name__ == '__main__':
    app.run(host=HOST, port=PORT, debug=DEBUG)
