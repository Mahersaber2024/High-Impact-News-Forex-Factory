import cloudscraper
import requests  # Added to handle timeout exceptions
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import re
import pandas as pd

# Define month names and their corresponding numbers
month_names = {
    1: "Jan ", 2: "Feb ", 3: "Mar ", 4: "Apr ", 5: "May ",
    6: "Jun ", 7: "Jul ", 8: "Aug ", 9: "Sep ", 10: "Oct ",
    11: "Nov ", 12: "Dec "
}
month_numbers = {v: k for k, v in month_names.items()}

def get_start_of_week(date_object):
    """Calculate the start of the week (Monday) for the given date."""
    # Find the first Monday before or on the given date
    days_to_monday = (date_object.weekday() - 0) % 7  # 0 = Monday
    start_of_week = date_object - timedelta(days=days_to_monday)
    return start_of_week

def getURL(date_object, timeline='day'):
    """Generate URL based on the given date and timeline (daily, weekly)"""
    if timeline == 'week':
        start_of_week = get_start_of_week(date_object)
        date = f'{month_names.get(start_of_week.month, "Jan")}{start_of_week.day}.{start_of_week.year}'
    else:
        date = f'{month_names.get(date_object.month, "Jan")}{date_object.day}.{date_object.year}'
    
    url = f'https://www.forexfactory.com/calendar?{timeline}={date}'
    return url

def getPageHTML(url):  # Gets URL and returns the source HTML
    scraper = cloudscraper.create_scraper()
    cookies = {
        'fftimezone': 'America%2FNew_York',   # Set the timezone to New York
        'fftimezoneoffset': '-5',             # Set the timezone offset from GMT
        'fftimeformat': '1'                   # Set the time format to 24-hour
    }
    
    try:
        # CRITICAL FIX: Added timeout=15 to prevent indefinite hanging
        response = scraper.get(url, cookies=cookies, timeout=15)
        response.raise_for_status()  # Raise an exception for HTTP errors (4xx, 5xx)
        return response.text
    except requests.exceptions.Timeout:
        print(f"ERROR: Request to {url} timed out after 15 seconds.")
        return ""  # Return empty string so BeautifulSoup handles it gracefully
    except requests.exceptions.RequestException as e:
        print(f"ERROR: Failed to fetch {url}. Reason: {e}")
        return ""

def getRecords(url, date_object):
    """Process the page and return records of high-impact events with formatted date."""
    all_records = []  # Store all event data here
    
    # Fetch and parse the HTML page
    pageHTML = getPageHTML(url)
    
    # If pageHTML is empty due to timeout/error, soup will be empty and safely return []
    soup = BeautifulSoup(pageHTML, 'html.parser')
    table = soup.find('table', class_='calendar__table')
    
    if not table:
        return all_records
        
    events = table.find_all('tr', class_='calendar__row')
    current_date = date_object  # Default date
    current_time = None  # Store the last known time for events without time
    
    # Process each event
    for event in events:
        # Find the date element (if available)
        date_cell = event.find('td', class_='calendar__date')
        date_text = date_cell.text.strip() if date_cell else ""
        
        if date_text:
            try:
                # Clean the date text (remove extra spaces or characters)
                date_text = re.sub(r'\s+', ' ', date_text).strip()
                # Parse with format "Tue Nov 12" (without comma)
                parsed_date = datetime.strptime(f"{date_text} {current_date.year}", "%a %b %d %Y")
                current_date = parsed_date
            except ValueError as e:
                # Keep current_date if parsing fails
                continue
                
        # Format the date as "Mon, Jul 14"
        formatted_date = f"{current_date.strftime('%a')}, {current_date.strftime('%b')} {current_date.day}"
        
        # Find the time element and check if it exists
        time_cell = event.find('td', class_='calendar__time')
        time_text = time_cell.text.strip() if time_cell else ""
        
        # Skip only records with "Tentative" time
        if time_text.lower() == "tentative":
            continue
            
        # Extract other information
        curr_cell = event.find('td', class_='calendar__currency')
        curr = curr_cell.text.strip() if curr_cell else "N/A"
        
        # Event name
        name_cell = event.find('td', class_='calendar__event')
        name = name_cell.find('span').text.strip() if name_cell and name_cell.find('span') else "N/A"
        
        # Skip if both currency and event name are missing
        if curr == "N/A" and name == "N/A":
            continue
            
        # Use current_time if time_text is empty
        if not time_text and current_time:
            time_text = current_time
            
        # Previous, forecast, and actual values
        previous_cell = event.find('td', class_='calendar__previous')
        previous = previous_cell.text.strip() if previous_cell else 'unknown'
        
        forecast_cell = event.find('td', class_='calendar__forecast')
        forecast = forecast_cell.text.strip() if forecast_cell else 'unknown'
        
        actual_cell = event.find('td', class_='calendar__actual')
        actual = actual_cell.text.strip() if actual_cell else 'unknown'
        
        # Determine the impact level
        impact_icon = event.find('span', class_='icon icon--ff-impact-red')
        impact = 'High' if impact_icon else 'Low'
        
        # Save the record only if it has valid data
        if impact == 'High' and (curr != "N/A" or name != "N/A"):
            record = {
                'Date': formatted_date,
                'Time': time_text,
                'Currency': curr,
                'Event': name,
                'Forecast': forecast,
                'Actual': actual,
                'Previous': previous,
                'Impact': impact
            }
            all_records.append(record)
            
    return all_records
