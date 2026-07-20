"""
SAHDRS Dashboard - Web UI with live data
Run this alongside sahdrs_main.py
Open browser to: http://<your-ip>:5000
"""

from flask import Flask, render_template, Response, jsonify
import cv2
import time
import socket

app = Flask(__name__)

# Import shared state from main script
# (This works because both scripts share the same Python process if you import properly,
# but for simplicity we'll re-import the live data via a shared file/socket)

# Easier approach: read CSV log and shared state files
import os
import csv

LOG_DIR = "logs"
SENSOR_LOG_FILE = os.path.join(LOG_DIR, "sensor_log.csv")
ALERT_LOG_FILE = os.path.join(LOG_DIR, "alerts_log.csv")

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "localhost"

@app.route('/')
def index():
    return render_template('dashboard.html')

@app.route('/api/sensors')
def api_sensors():
    """Return latest sensor reading."""
    if not os.path.exists(SENSOR_LOG_FILE):
        return jsonify({})
    
    with open(SENSOR_LOG_FILE, "r") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        if not rows:
            return jsonify({})
        return jsonify(rows[-1])

@app.route('/api/history')
def api_history():
    """Return last 50 sensor readings for charts."""
    if not os.path.exists(SENSOR_LOG_FILE):
        return jsonify([])
    
    with open(SENSOR_LOG_FILE, "r") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        return jsonify(rows[-50:])

@app.route('/api/alerts')
def api_alerts():
    """Return last 20 alerts."""
    if not os.path.exists(ALERT_LOG_FILE):
        return jsonify([])
    
    with open(ALERT_LOG_FILE, "r") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        return jsonify(rows[-20:][::-1])  # newest first

if __name__ == '__main__':
    ip = get_local_ip()
    print(f"\n🌐 SAHDRS Dashboard")
    print(f"📱 Open on this PC:     http://localhost:5000")
    print(f"📱 Open on phone/tablet: http://{ip}:5000")
    print(f"   (Make sure devices are on the same WiFi network)\n")
    app.run(host='0.0.0.0', port=5000, debug=False)