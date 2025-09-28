from flask import Flask, render_template, request, jsonify, make_response
from dotenv import load_dotenv
import os
import requests
import json
from datetime import datetime, timedelta, date
from openai import OpenAI
import uuid
import io
import csv

# Load variables from .env file
load_dotenv()

app = Flask(__name__)

# --- API Key Configuration ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY)

# --- Weather API Configuration ---
WEATHER_API_CLIENT_ID = os.getenv("WEATHER_API_CLIENT_ID")
WEATHER_API_CLIENT_SECRET = os.getenv("WEATHER_API_CLIENT_SECRET")
WEATHER_API_URL = "https://weather.api.dtn.com/v2/conditions/"
WEATHER_API_AUDIENCE = "https://weather.api.dtn.com/conditions"
WEATHER_PARAMETERS = ["airTemp", "precipProb", "totalCloudCover", "windSpeed", "feelsLikeTemp", "uvIndex", "windGust"]

# --- Climatology API Configuration ---
CLIMATOLOGY_API_CLIENT_ID = os.getenv("CLIMATOLOGY_API_CLIENT_ID")
CLIMATOLOGY_API_CLIENT_SECRET = os.getenv("CLIMATOLOGY_API_CLIENT_SECRET")
CLIMATOLOGY_API_URL = "https://climatology.api.dtn.com/v1/daily/ten-year"
CLIMATOLOGY_API_AUDIENCE = "https://climatology.api.dtn.com"
CLIMATOLOGY_PARAMETERS = ["airTempAvg", "airTempStdDev", "airTempMaxAvg", "airTempMinAvg", "precipAmountAvg", "windSpeedAvg", "sunshineDurationAvg"]

# --- In-memory caches ---
token_cache = {} # Will store tokens for different APIs
csv_cache = {}   # To store generated CSV data temporarily

def get_dtn_api_token(audience, client_id, client_secret):
    """Fetches and caches a DTN API token for a specific audience."""
    global token_cache
    cached_token = token_cache.get(audience)
    if cached_token and cached_token["expires_at"] > datetime.utcnow():
        return cached_token["token"]

    url = 'https://api.auth.dtn.com/v1/tokens/authorize'
    payload = json.dumps({
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
        "audience": audience
    })
    headers = {'Accept': 'application/json', 'Content-Type': 'application/json'}
    response = requests.post(url, data=payload, headers=headers)
    response.raise_for_status()
    data = response.json()['data']
    
    token = data['access_token']
    token_cache[audience] = {
        "token": token,
        "expires_at": datetime.utcnow() + timedelta(minutes=55)
    }
    return token

def fetch_weather_data(lat, lon, start_time, end_time, parameters):
    """Fetches data from the real-time/forecast weather API."""
    token = get_dtn_api_token(WEATHER_API_AUDIENCE, WEATHER_API_CLIENT_ID, WEATHER_API_CLIENT_SECRET)
    headers = {"Authorization": f"Bearer {token}"}
    params = {'lat': lat, 'lon': lon, 'startTime': start_time, 'endTime': end_time, 'parameters': ','.join(parameters)}
    response = requests.get(WEATHER_API_URL, headers=headers, params=params)
    response.raise_for_status()
    return response.json()

def fetch_climatology_data(lat, lon, start_date, end_date, parameters):
    """Fetches data from the climatology API."""
    token = get_dtn_api_token(CLIMATOLOGY_API_AUDIENCE, CLIMATOLOGY_API_CLIENT_ID, CLIMATOLOGY_API_CLIENT_SECRET)
    headers = {"Authorization": f"Bearer {token}"}
    params = {'lat': lat, 'lon': lon, 'startDate': start_date, 'endDate': end_date, 'parameters': ','.join(parameters)}
    response = requests.get(CLIMATOLOGY_API_URL, headers=headers, params=params)
    response.raise_for_status()
    return response.json()

def normalize_to_csv(data):
    """Converts weather or climatology JSON data to a normalized CSV string."""
    if not data.get("features"):
        return ""
    # This function assumes both APIs return a similar GeoJSON structure, which is a safe starting point.
    feature = data["features"][0]
    coords = feature["geometry"]["coordinates"]
    properties = feature["properties"]
    output = io.StringIO()
    first_timestamp = next(iter(properties))
    parameter_headers = sorted(properties[first_timestamp].keys())
    headers = ["timestamp", "longitude", "latitude"] + parameter_headers
    writer = csv.DictWriter(output, fieldnames=headers)
    writer.writeheader()
    for timestamp, values in properties.items():
        row = {"timestamp": timestamp, "longitude": coords[0], "latitude": coords[1], **values}
        writer.writerow(row)
    return output.getvalue()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/process_request', methods=['POST'])
def process_request():
    user_query = request.json.get('query')
    if not user_query:
        return jsonify({'error': 'No query provided'}), 400

    try:
        # Step 1: API Router - Decide which API to use
        today = date.today()
        forecast_horizon = (today + timedelta(days=15)).isoformat()
        
        router_prompt = f"""
        You are an API routing assistant. Based on the user's query, decide which API to call.
        - Use 'weather' for specific, near-future date requests (within the next 15 days).
        - Use 'climatology' for general questions about typical weather for a time of year, or for dates far in the future.

        User Query: "{user_query}"
        Today's Date: {today.isoformat()}
        15-Day Forecast Horizon Ends: {forecast_horizon}

        Respond with JSON indicating your choice, for example: {{"api_choice": "weather"}}
        """
        router_response = client.chat.completions.create(
            model="gpt-4o-mini",
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "You are an API router. Your job is to choose between 'weather' and 'climatology'."},
                {"role": "user", "content": router_prompt}
            ]
        )
        api_choice = json.loads(router_response.choices[0].message.content).get("api_choice", "weather")

        # Step 2: Parse parameters and fetch data based on the choice
        if api_choice == "climatology":
            # Logic for Climatology API
            parsing_prompt = f"""
            Based on the user's query: '{user_query}', determine the location and date range.
            - Dates should be in MM-DD format.
            - Select up to three relevant parameters from: {', '.join(CLIMATOLOGY_PARAMETERS)}.
            Respond with JSON: {{"latitude": float, "longitude": float, "startDate": "MM-DD", "endDate": "MM-DD", "parameters": [...]}}
            """
            model_name = "Climatology"
        else:
            # Logic for Weather API (default)
            parsing_prompt = f"""
            Based on the user's query: '{user_query}' and today being {today.isoformat()}, determine the location and date range.
            - Dates should be in YYYY-MM-DDTHH:MM:SSZ format.
            - Select up to three relevant parameters from: {', '.join(WEATHER_PARAMETERS)}.
            Respond with JSON: {{"latitude": float, "longitude": float, "startTime": "YYYY-MM-DDTHH:MM:SSZ", "endTime": "YYYY-MM-DDTHH:MM:SSZ", "parameters": [...]}}
            """
            model_name = "Weather Forecast"

        # Common parameter parsing call
        param_response = client.chat.completions.create(
            model="gpt-4o-mini",
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": "You extract API parameters from user queries."}, {"role": "user", "content": parsing_prompt}]
        )
        params = json.loads(param_response.choices[0].message.content)

        if api_choice == "climatology":
            weather_data = fetch_climatology_data(params['latitude'], params['longitude'], params['startDate'], params['endDate'], params['parameters'])
        else:
            weather_data = fetch_weather_data(params['latitude'], params['longitude'], params['startTime'], params['endTime'], params['parameters'])

        # Step 3: Generate summary
        summary_prompt = f"""
        You are a helpful weather assistant. A user asked: "{user_query}"
        Based on the following data from the {model_name} model, provide a concise, natural language answer.
        Weather Data: {json.dumps(weather_data)}
        """
        summary_response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": "You provide helpful, natural language weather summaries."}, {"role": "user", "content": summary_prompt}]
        )
        llm_summary = summary_response.choices[0].message.content

        # Step 4: Prepare CSV and cache it
        csv_data = normalize_to_csv(weather_data)
        csv_id = str(uuid.uuid4())
        csv_cache[csv_id] = csv_data

        # Step 5: Return all data to the frontend
        return jsonify({'weather_data': weather_data, 'llm_summary': llm_summary, 'csv_id': csv_id})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/download_csv/<csv_id>')
def download_csv(csv_id):
    csv_data = csv_cache.get(csv_id)
    if not csv_data:
        return "CSV data not found or expired.", 404
    response = make_response(csv_data)
    response.headers["Content-Disposition"] = "attachment; filename=weather_data.csv"
    response.headers["Content-Type"] = "text/csv"
    return response

if __name__ == '__main__':
    app.run(debug=True)