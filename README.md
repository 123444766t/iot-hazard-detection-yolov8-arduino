# iot-hazard-detection-yolov8-arduino
# SAHDRS — Smart Autonomous Hazard Detection & Response System

> *"Detecting Danger Before It Strikes"*

SAHDRS is an all-in-one, multi-modal IoT safety system powered by Computer Vision, Machine Learning, and embedded sensors. Designed to replace expensive, single-purpose, reactive hazard systems, SAHDRS unifies 7 distinct hazard detection mechanisms into a single real-time autonomous ecosystem.

---

## 🛠 Project Overview

Traditional safety setups are often isolated (only handling fire OR gas), purely reactive, and lack real-time remote notification systems. SAHDRS bridges this gap by combining embedded hardware sensing with GPU-accelerated computer vision to detect, respond to, and log hazards instantly[cite: 1].

### Key Features
* **7-in-1 Hazard Detection:** Fire, Smoke/LPG, Extreme Heat, Proximity, Intrusion/Motion, Human Falls, and System Faults.
* **Hybrid AI Fall Detection:** Combines YOLOv8 bounding box tracking with MediaPipe Pose landmark estimation for high-precision fall detection.
* **Autonomous Response:** Triggers automatic hardware countermeasures (buzzer alarms, fan activation) via relay control.
* **Multi-Channel Alerts:** Real-time Telegram notifications with photo snapshots, dynamic web dashboard, and local CSV logging.
* **Zero-Lag Architecture:** Async Telegram queue, multi-frame alert confirmation, and 30-second smart cooldowns prevent alert spamming and video stutter.

---

## 🏗 System Architecture

SAHDRS operates across a 3-layer architecture with full two-way USB serial communication between the microcontroller and the edge processing unit:


                          LAYER 1: SENSORS                           
       (Gas, Flame, Temperature/Humidity, Distance, Motion)          



                           PROCESSING HUB                             
     Arduino Uno R3 <==== USB Serial Link ====> Python Backend (3.12)    
     (Data Collection & I/O)                    (YOLOv8 + MediaPipe Pose)



                   LAYER 3: ALERTS & OUTPUTS                   
      (Telegram Bot, Flask Web UI, Local CSV, Buzzer, Relay Fan)      


---

## ⚡ Hardware & Electronics Design

The hardware subsystem relies on 9 components running entirely off the Arduino Uno's power delivery using direct jumper-wire connections and custom twist splitters—eliminating the need for a breadboard[cite: 1].

| Component | Function | Connection / Interface |
| :--- | :--- | :--- |
| **Arduino Uno R3** | Main Microcontroller | USB Serial to PC[cite: 1] |
| **MQ-2 Sensor** | Smoke / LPG / Methane Detection | Analog Input[cite: 1] |
| **Flame Sensor** | IR Flame Detection | Digital Input[cite: 1] |
| **DHT11 Sensor** | Ambient Temperature & Humidity | Digital Input[cite: 1] |
| **HC-SR04** | Ultrasonic Proximity Sensing | Trigger/Echo Pins[cite: 1] |
| **IR Motion Sensor** | Movement / Intrusion Detection | Digital Input[cite: 1] |
| **1-Channel Relay** | High-Power Control | Output to 5V DC Fan[cite: 1] |
| **5V DC Fan** | Autonomous Exhaust / Cooling | Controlled via Relay[cite: 1] |
| **Active Buzzer** | Multi-Pattern Audible Alarms | Digital PWM Output[cite: 1] |
| **Webcam** | Real-Time Video Feed | USB to Host PC[cite: 1] |

---

## 💻 Tech Stack

* **Languages:** Python 3.12, C++ (Arduino Wiring)[cite: 1]
* **Computer Vision & ML:** YOLOv8 (Ultralytics), MediaPipe Pose, PyTorch (CUDA Accelerated)[cite: 1]
* **Backend Framework:** Flask, PySerial, Python Threading & Queue[cite: 1]
* **Frontend Dashboard:** HTML5, CSS3, JavaScript, Chart.js[cite: 1]
* **Cloud & Messaging:** Telegram Bot API, Requests Library[cite: 1]

---

## 🤖 Hybrid AI Pipeline (Fall Detection)

To eliminate false positives, fall detection is processed through a 4-stage hybrid engine[cite: 1]:

1. **Frame Capture:** Live camera feed captured via OpenCV at 30+ FPS[cite: 1].
2. **Object Detection:** YOLOv8 identifies human bounding boxes and confidence scores[cite: 1].
3. **Pose Analysis:** MediaPipe estimates body landmarks to compute torso angles and aspect ratios[cite: 1].
4. **Multi-Signal Engine:** Evaluates torso angle against vertical thresholds across an 8-frame temporal window before triggering an alarm[cite: 1].

---

## 🚨 Response Priority Levels

SAHDRS categorizes incidents using a 3-tier priority response matrix[cite: 1]:

| Priority Level | Trigger Event | Autonomous Action | Notification |
| :--- | :--- | :--- | :--- |
| **HIGH (Level 3)** | Fire Detected / Fall Detected | Fast Beep Pattern + Exhaust Fan ON | Immediate Telegram Photo + Dashboard Alert[cite: 1] |
| **MED (Level 2)** | Gas Leak / High Temp | Steady Beep Pattern | Telegram Alert + Dashboard Alert[cite: 1] |
| **LOW (Level 1)** | Motion / Proximity | Gentle Chirp Pattern | Live Dashboard Update[cite: 1] |
| **OFF (Level 0)** | Normal State | Silent Continuous Monitoring | Real-Time Telemetry Logging[cite: 1] |

---

## 📊 Performance Metrics

* **Detection Speed:** ~15–20 ms / frame (GPU accelerated via CUDA)[cite: 1]
* **Video Throughput:** 30+ FPS continuous live stream[cite: 1]
* **Alert Delivery:** < 3 seconds from hazard detection to Telegram notification[cite: 1]
* **False Positive Rate:** < 5% due to hybrid multi-frame verification[cite: 1]

---

## 🚀 Getting Started

### 1. Hardware Setup
1. Upload the provided `.ino` sketch in `hardware/` to your Arduino Uno R3[cite: 1].
2. Connect all sensors according to the pin configuration defined in the sketch[cite: 1].

### 2. Software Installation
```bash
# Clone the repository
git clone [https://github.com/YOUR_USERNAME/sahdrs-iot-safety-system.git](https://github.com/YOUR_USERNAME/sahdrs-iot-safety-system.git)
cd sahdrs-iot-safety-system

# Create and activate a virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```
#create .env file in root directory
->TELEGRAM_BOT_TOKEN=your_bot_token_here
->TELEGRAM_CHAT_ID=your_chat_id_here
->SERIAL_PORT=COM3  # Adjust based on your system (e.g., /dev/ttyUSB0 on Linux)
->BAUD_RATE=9600

#Run the system
python main.py
Open your browser and navigate to http://localhost:5000 to view the live dashboard


##Lead Developer & System Architect: Goutham A
