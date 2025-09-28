from flask import Flask, render_template, request, jsonify
import os
import requests
import json
from datetime import datetime, timedelta, date
from openai import OpenAI

app = Flask(__name__)

# --- API Key Configuration ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "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")
client = OpenAI(api_key=OPENAI_API_KEY)

# --- Weather API Configuration ---
WEATHER_API_CLIENT_ID = os.getenv("WEATHER_API_CLIENT_ID", "Nv9sG40T9qR2uxaOABSYyt5MATtgCBwE")
WEATHER_API_CLIENT_SECRET = os.getenv("WEATHER_API_CLIENT_SECRET", "4M_9P-lm78JvJJ9suV-p3b2oJatPYj5DWdp7P1hbRVM2H5epEsf6gpOWFNt2_U1X")
WEATHER_API_URL = "https://weather.api.dtn.com/v2/conditions/"

# --- In-memory token cache ---
token_cache = {"token": None, "expires_at": None}

WEATHER_PARAMETERS = [
    "airTemp","precipProb","totalCloudCover","windSpeed","feelsLikeTemp","uvIndex","windGust"
]

def get_weather_api_token():
    """Fetches and caches the weather API token."""
    global token_cache
    if token_cache["token"] and token_cache["expires_at"] > datetime.utcnow():
        return token_cache["token"]
    url = 'https://api.auth.dtn.com/v1/tokens/authorize'
    payload = json.dumps({
        "grant_type": "client_credentials",
        "client_id": WEATHER_API_CLIENT_ID,
        "client_secret": WEATHER_API_CLIENT_SECRET,
        "audience": "https://weather.api.dtn.com/conditions"
    })
    headers = {'Accept': 'application/json', 'Content-Type': 'application/json'}
    response = requests.post(url, data=payload, headers=headers)
    response.raise_for_status()
    data = response.json()['data']
    token_cache["token"] = data['access_token']
    token_cache["expires_at"] = datetime.utcnow() + timedelta(minutes=55)
    return token_cache["token"]

def fetch_weather_data(lat, lon, start_time, end_time, parameters):
    """Fetches weather data from the DTN API."""
    token = get_weather_api_token()
    headers = {"Authorization": f"Bearer {token}"}
    params = {'lat': lat, 'lon': lon, 'startTime': start_time, 'endTime': end_time, 'parameters': ','.join(parameters)}
    response = requests.get(WEATHER_API_URL, headers=headers, params=params)
    response.raise_for_status()
    return response.json()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/process_request', methods=['POST'])
def process_request():
    user_query = request.json.get('query')
    if not user_query:
        return jsonify({'error': 'No query provided'}), 400

    try:
        # Step 1: Interpret the user's request for API parameters
        current_date_iso = date.today().isoformat()
        parsing_prompt = f"""
        Given the user's request: '{user_query}' and that today's date is {current_date_iso}, determine the following:
        1. The geographical location (latitude and longitude).
        2. The time frame (startTime and endTime in ISO 8601 format).
        3. The relevant weather parameters from this list: {', '.join(WEATHER_PARAMETERS)}

        Provide the output in a structured JSON format with keys: "latitude", "longitude", "startTime", "endTime", "parameters".
        """
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "You are an assistant that structures user requests for a weather API."},
                {"role": "user", "content": parsing_prompt}
            ]
        )
        interpreted_request = json.loads(response.choices[0].message.content)

        # Step 2: Fetch data from the weather API
        weather_data = fetch_weather_data(
            lat=interpreted_request['latitude'],
            lon=interpreted_request['longitude'],
            start_time=interpreted_request['startTime'],
            end_time=interpreted_request['endTime'],
            parameters=interpreted_request['parameters']
        )

        # Step 3: Generate a natural language summary
        summary_prompt = f"""
        You are a helpful weather assistant. A user asked: "{user_query}"
        Based on the following weather data, provide a concise, natural language answer.
        Interpret the data to give a helpful recommendation (e.g., "The best time to run would be in the morning...").
        Do not mention the JSON data structure.
        Weather Data: {json.dumps(weather_data)}
        """
        summary_response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You provide helpful, natural language weather summaries."},
                {"role": "user", "content": summary_prompt}
            ]
        )
        llm_summary = summary_response.choices[0].message.content

        # Step 4: Return all data to the frontend
        return jsonify({
            'weather_data': weather_data,
            'llm_summary': llm_summary
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)