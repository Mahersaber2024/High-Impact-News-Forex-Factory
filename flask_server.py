import logging
import os
from flask import Flask, jsonify
from datetime import datetime, timedelta
from forexFactoryScrapper import getRecords, getURL, get_start_of_week

PORT = int(os.getenv("FLASK_PORT", "45869"))
DEBUG = os.getenv("FLASK_DEBUG", "false").lower() == "true"

# Configure logging to display information in the console
logging.basicConfig(level=logging.INFO)

app = Flask(__name__)

# Cache for storing data
cache = {
    "today": {"data": None, "last_update": None},
    "weekly": {"data": None, "last_update": None, "last_day": None},  # Added last_day for weekly cache
    "tomorrow": {"data": None, "last_update": None}
}

CACHE_DURATION = timedelta(hours=1)  # Cache validity duration for today and tomorrow
DAILY_UPDATE_HOUR = 0  # Start of day (e.g. 00:00) for refreshing weekly data

def is_cache_valid(last_update, cache_key):
    """Check whether the cached data is still valid."""
    if last_update is None:
        return False
    if cache_key == "weekly":
        # For weekly data, check whether the day has changed
        current_day = datetime.now().date()
        last_day = cache[cache_key].get("last_day")
        if last_day != current_day:
            logging.info(f"Day changed from {last_day} to {current_day}, invalidating weekly cache.")
            return False
        valid = datetime.now() - last_update < timedelta(days=1)  # Valid until the end of the day
    else:
        valid = datetime.now() - last_update < CACHE_DURATION
    logging.info(f"Cache valid: {valid}, Last update: {last_update}, Current time: {datetime.now()}")
    return valid

@app.route('/api/forex/today', methods=['GET'])
def today_data():
    today = datetime.now()

    if is_cache_valid(cache["today"]["last_update"], "today"):
        logging.info("Returning cached data for today.")
        return jsonify(cache["today"]["data"]), 200

    logging.info("Fetching new data for today.")
    url = getURL(today, 'day')
    record_json = getRecords(url, today)
    
    cache["today"] = {"data": record_json, "last_update": datetime.now()}
    
    return jsonify(record_json), 200

@app.route('/api/forex/weekly', methods=['GET'])
def weekly_data():
    today = datetime.now()
    start_of_week = get_start_of_week(today)

    if is_cache_valid(cache["weekly"]["last_update"], "weekly"):
        logging.info("Returning cached data for weekly.")
        return jsonify(cache["weekly"]["data"]), 200

    logging.info("Fetching new data for weekly.")
    url = getURL(start_of_week, 'week')
    record_json = getRecords(url, start_of_week)

    # Update cache with the current day
    cache["weekly"] = {
        "data": record_json,
        "last_update": datetime.now(),
        "last_day": datetime.now().date()
    }

    return jsonify(record_json), 200

@app.route('/api/forex/tomorrow', methods=['GET'])
def tomorrow_data():
    tomorrow = datetime.now() + timedelta(days=1)

    if is_cache_valid(cache["tomorrow"]["last_update"], "tomorrow"):
        logging.info("Returning cached data for tomorrow.")
        return jsonify(cache["tomorrow"]["data"]), 200

    logging.info("Fetching new data for tomorrow.")
    url = getURL(tomorrow, 'day')
    record_json = getRecords(url, tomorrow)

    cache["tomorrow"] = {"data": record_json, "last_update": datetime.now()}
    
    return jsonify(record_json), 200

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=PORT, debug=DEBUG)
