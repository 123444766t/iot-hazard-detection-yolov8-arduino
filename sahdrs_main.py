"""
=====================================================
SAHDRS v2.3 - Smart Autonomous Hazard Detection 
              & Response System

HYBRID FALL DETECTION:
- YOLOv8 person detection (GPU accelerated)
- MediaPipe pose estimation for body angles
- Multi-signal fall scoring (torso angle + position + ratio)
- Multi-frame confirmation
=====================================================
"""

import os
import cv2
import csv
import math
import serial
import time
import threading
import queue
import requests
import numpy as np
from datetime import datetime
from ultralytics import YOLO
import torch
import mediapipe as mp

# ==== CONFIG ====
SERIAL_PORT  = 'COM4'
BAUD_RATE    = 9600
CAMERA_INDEX = 0

# ==== Telegram ====
BOT_TOKEN = "8655033037:AAHo7N2wK9GkjHNXZf2hjsvsPNwsCAYRiT0"
CHAT_ID   = "6337985324"

# ==== YOLO ====
YOLO_MODEL = "yolov8s.pt"
CONFIDENCE_THRESHOLD = 0.5
INFER_EVERY_N_FRAMES = 1

# ==== Folders ====
SNAPSHOT_DIR = "snapshots"
LOG_DIR = "logs"
os.makedirs(SNAPSHOT_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)
SENSOR_LOG_FILE = os.path.join(LOG_DIR, "sensor_log.csv")
ALERT_LOG_FILE = os.path.join(LOG_DIR, "alerts_log.csv")

# ==== CSV Init ====
def init_csv_files():
    if not os.path.exists(SENSOR_LOG_FILE):
        with open(SENSOR_LOG_FILE, "w", newline="") as f:
            csv.writer(f).writerow(
                ["timestamp", "gas", "flame", "temp_c", "humidity", "distance_cm", "ir"])
    if not os.path.exists(ALERT_LOG_FILE):
        with open(ALERT_LOG_FILE, "w", newline="") as f:
            csv.writer(f).writerow(
                ["timestamp", "alert_type", "message", "snapshot_file"])

init_csv_files()

# ==== Async Sensor Logger ====
sensor_log_buffer = []
sensor_buffer_lock = threading.Lock()

def sensor_log_writer():
    while True:
        time.sleep(5)
        with sensor_buffer_lock:
            if not sensor_log_buffer: continue
            rows = sensor_log_buffer.copy()
            sensor_log_buffer.clear()
        try:
            with open(SENSOR_LOG_FILE, "a", newline="") as f:
                csv.writer(f).writerows(rows)
        except Exception as e:
            print(f"[CSV Err] {e}")

threading.Thread(target=sensor_log_writer, daemon=True).start()

def log_sensor_data(gas, flame, temp, hum, dist, ir):
    with sensor_buffer_lock:
        sensor_log_buffer.append([
            datetime.now().isoformat(timespec='seconds'),
            gas, flame, temp, hum, dist, ir])

def log_alert(alert_type, message, snapshot_file=""):
    try:
        with open(ALERT_LOG_FILE, "a", newline="") as f:
            csv.writer(f).writerow([
                datetime.now().isoformat(timespec='seconds'),
                alert_type, message, snapshot_file])
    except Exception as e:
        print(f"[Alert Log Err] {e}")

# ==== Arduino ====
try:
    arduino = serial.Serial()
    arduino.port = SERIAL_PORT
    arduino.baudrate = BAUD_RATE
    arduino.timeout = 1
    arduino.dtr = False
    arduino.rts = False
    arduino.open()
    time.sleep(2)
    arduino.reset_input_buffer()
    arduino.reset_output_buffer()
    print(f"[✓] Connected to Arduino on {SERIAL_PORT}")
except Exception as e:
    print(f"[X] Serial connection failed: {e}")
    arduino = None

# ==== Shared State ====
latest_frame = None
frame_lock = threading.Lock()

sensor_state = {
    "gas": "0", "flame": "1", "temp": "0", "hum": "0",
    "dist": "0", "ir": "1",
    "gas_alert": False, "fire_alert": False, "temp_alert": False,
    "prox_alert": False, "motion_alert": False,
    "person_count": 0, "fall_detected": False,
    "torso_angle": 0
}

# ==== Async Telegram ====
telegram_queue = queue.Queue()

def telegram_worker():
    while True:
        try:
            task = telegram_queue.get()
            if task is None: break
            task_type = task['type']
            message = task['message']
            
            if task_type == 'text':
                try:
                    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
                    requests.post(url, data={"chat_id": CHAT_ID, "text": message}, timeout=5)
                    print(f"[📲 Telegram] {message}")
                except Exception as e:
                    print(f"[Telegram Err] {e}")
            elif task_type == 'photo':
                frame = task.get('frame')
                if frame is None:
                    with frame_lock:
                        if latest_frame is not None:
                            frame = latest_frame.copy()
                if frame is None: continue
                try:
                    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
                    annotated = frame.copy()
                    h, w, _ = annotated.shape
                    cv2.rectangle(annotated, (0, 0), (w, 60), (0, 0, 0), -1)
                    cv2.putText(annotated, "SAHDRS ALERT", (10, 25),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
                    cv2.putText(annotated, timestamp, (10, 50),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
                    filename = os.path.join(SNAPSHOT_DIR, f"alert_{int(time.time())}.jpg")
                    cv2.imwrite(filename, annotated)
                    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
                    with open(filename, 'rb') as photo:
                        requests.post(url, files={'photo': photo},
                                     data={'chat_id': CHAT_ID, 'caption': message},
                                     timeout=10)
                    print(f"[📸 Telegram] {message}")
                except Exception as e:
                    print(f"[Telegram Photo Err] {e}")
        except Exception as e:
            print(f"[Worker Err] {e}")

for _ in range(2):
    threading.Thread(target=telegram_worker, daemon=True).start()

def send_telegram(message):
    telegram_queue.put({'type': 'text', 'message': message})

def send_telegram_photo(message, frame=None):
    if frame is not None:
        frame = frame.copy()
    telegram_queue.put({'type': 'photo', 'message': message, 'frame': frame})
    return None

# ==== Telegram /commands ====
last_update_id = 0

def telegram_poll():
    global last_update_id
    while True:
        try:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
            params = {"offset": last_update_id + 1, "timeout": 10}
            r = requests.get(url, params=params, timeout=15)
            if r.status_code == 200:
                for update in r.json().get("result", []):
                    last_update_id = update["update_id"]
                    msg = update.get("message", {})
                    text = msg.get("text", "")
                    chat_id = msg.get("chat", {}).get("id")
                    if str(chat_id) != CHAT_ID: continue
                    if text == "/status":
                        status_msg = (
                            f"📊 SAHDRS Status\n\n"
                            f"🟡 Gas: {sensor_state['gas']}\n"
                            f"🔥 Flame: {sensor_state['flame']}\n"
                            f"🌡️ Temp: {sensor_state['temp']}°C\n"
                            f"💧 Humidity: {sensor_state['hum']}%\n"
                            f"📏 Distance: {sensor_state['dist']} cm\n"
                            f"🏃 IR: {sensor_state['ir']}\n"
                            f"👥 People: {sensor_state['person_count']}\n"
                            f"📐 Torso angle: {sensor_state['torso_angle']:.0f}°")
                        send_telegram(status_msg)
                    elif text == "/photo":
                        send_telegram_photo("📸 Live snapshot")
                    elif text == "/reset":
                        if arduino: arduino.write(b"RESET\n")
                        send_telegram("✅ System reset")
                    elif text in ("/help", "/start"):
                        send_telegram(
                            "🤖 SAHDRS Bot Commands:\n"
                            "/status - Live sensor readings\n"
                            "/photo - Get live snapshot\n"
                            "/reset - Reset alarm\n"
                            "/help - This menu")
        except Exception as e:
            pass
        time.sleep(2)

threading.Thread(target=telegram_poll, daemon=True).start()

send_telegram("🟢 SAHDRS v2.3 Online — Hybrid YOLO+Pose fall detection!\n\n/help for commands")

def send_to_arduino(msg):
    if arduino:
        arduino.write((msg + "\n").encode())

# ==== Cooldowns ====
last_alerts = {"GAS": 0, "FIRE": 0, "TEMP": 0, "PROXIMITY": 0, "MOTION": 0,
               "FALL": 0, "INTRUSION": 0}
ALERT_COOLDOWN = 30

def alert_with_cooldown(key, message, alert_type):
    now = time.time()
    if now - last_alerts[key] > ALERT_COOLDOWN:
        send_telegram_photo(message)
        log_alert(alert_type, message)
        last_alerts[key] = now

# ==== Arduino Reader ====
def read_arduino():
    while True:
        try:
            if arduino and arduino.in_waiting:
                line = arduino.readline().decode(errors='ignore').strip()
                if line.startswith("DATA"):
                    parts = line.split(",")
                    if len(parts) == 7:
                        _, gas, flame, temp, hum, dist, ir = parts
                        sensor_state.update({"gas": gas, "flame": flame, "temp": temp,
                                             "hum": hum, "dist": dist, "ir": ir})
                        log_sensor_data(gas, flame, temp, hum, dist, ir)
                elif line.startswith("STATUS"):
                    parts = line.split(",")
                    if len(parts) == 6:
                        _, gas_l, fire, ht, prox, mot = parts
                        sensor_state.update({
                            "gas_alert": (gas_l == "1"),
                            "fire_alert": (fire == "1"),
                            "temp_alert": (ht == "1"),
                            "prox_alert": (prox == "1"),
                            "motion_alert": (mot == "1")})
                        if gas_l == "1": alert_with_cooldown("GAS", "🟡 SAHDRS: Gas leak detected!", "GAS")
                        if fire == "1": alert_with_cooldown("FIRE", "🔥 SAHDRS: FIRE detected!", "FIRE")
                        if ht == "1": alert_with_cooldown("TEMP", "🌡️ SAHDRS: High temperature!", "TEMP")
                        if prox == "1": alert_with_cooldown("PROXIMITY", "📏 SAHDRS: Object too close!", "PROXIMITY")
                        if mot == "1": alert_with_cooldown("MOTION", "🏃 SAHDRS: Motion (IR)!", "MOTION")
        except Exception as e:
            print(f"[Serial Err] {e}")
        time.sleep(0.05)

threading.Thread(target=read_arduino, daemon=True).start()

# ==== Threaded Camera ====
class ThreadedCamera:
    def __init__(self, src=0):
        self.cap = cv2.VideoCapture(src, cv2.CAP_DSHOW)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        self.cap.set(cv2.CAP_PROP_FPS, 30)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self.ret, self.frame = self.cap.read()
        self.running = True
        self.lock = threading.Lock()
        threading.Thread(target=self._update, daemon=True).start()
    
    def _update(self):
        while self.running:
            ret, frame = self.cap.read()
            with self.lock:
                self.ret = ret
                self.frame = frame
    
    def read(self):
        with self.lock:
            return self.ret, self.frame.copy() if self.frame is not None else None
    
    def release(self):
        self.running = False
        time.sleep(0.1)
        self.cap.release()

# ==== Load YOLOv8 ====
device = 'cuda' if torch.cuda.is_available() else 'cpu'
print(f"[✓] YOLO running on: {device.upper()}")
if device == 'cuda':
    print(f"[✓] GPU: {torch.cuda.get_device_name(0)}")
    torch.backends.cudnn.benchmark = True

print(f"[↓] Loading YOLOv8 model ({YOLO_MODEL})...")
model = YOLO(YOLO_MODEL)
if device == 'cuda':
    model.to(device)
print("[✓] YOLO loaded")

# Warmup
print("[↻] Warming up GPU...")
dummy = np.zeros((480, 640, 3), dtype=np.uint8)
for _ in range(3):
    model(dummy, classes=[0], conf=0.5, device=device, verbose=False, half=(device=='cuda'))
print("[✓] GPU warmed up")

# ==== MediaPipe Pose ====
print("[↓] Loading MediaPipe Pose...")
mp_pose = mp.solutions.pose
pose_detector = mp_pose.Pose(
    static_image_mode=False,
    model_complexity=1,
    smooth_landmarks=True,
    min_detection_confidence=0.5,
    min_tracking_confidence=0.5
)
mp_drawing = mp.solutions.drawing_utils
print("[✓] MediaPipe Pose loaded")

# ==== HYBRID Fall Detection ====
def calculate_angle(p1, p2):
    """Angle of line p1->p2 from vertical (0° = vertical/upright, 90° = horizontal)."""
    dx = p2[0] - p1[0]
    dy = p2[1] - p1[1]
    angle_rad = math.atan2(abs(dx), abs(dy))
    return math.degrees(angle_rad)

def analyze_pose_for_fall(frame, bbox):
    """
    Use MediaPipe on the person's bounding box to analyze posture.
    Returns: (is_fallen_pose, torso_angle, debug_info)
    """
    x1, y1, x2, y2 = bbox
    # Add padding to bbox for better pose detection
    pad = 20
    h_frame, w_frame = frame.shape[:2]
    x1p = max(0, x1 - pad)
    y1p = max(0, y1 - pad)
    x2p = min(w_frame, x2 + pad)
    y2p = min(h_frame, y2 + pad)
    
    crop = frame[y1p:y2p, x1p:x2p]
    if crop.size == 0:
        return False, 0, "no_crop"
    
    rgb_crop = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
    results = pose_detector.process(rgb_crop)
    
    if not results.pose_landmarks:
        return False, 0, "no_pose"
    
    lm = results.pose_landmarks.landmark
    
    # Key landmarks (normalized 0-1)
    try:
        l_shoulder = lm[mp_pose.PoseLandmark.LEFT_SHOULDER.value]
        r_shoulder = lm[mp_pose.PoseLandmark.RIGHT_SHOULDER.value]
        l_hip = lm[mp_pose.PoseLandmark.LEFT_HIP.value]
        r_hip = lm[mp_pose.PoseLandmark.RIGHT_HIP.value]
        nose = lm[mp_pose.PoseLandmark.NOSE.value]
        
        # Only proceed if landmarks are visible
        if (l_shoulder.visibility < 0.3 or r_shoulder.visibility < 0.3 or
            l_hip.visibility < 0.3 or r_hip.visibility < 0.3):
            return False, 0, "low_visibility"
        
        # Calculate midpoints
        shoulder_mid = ((l_shoulder.x + r_shoulder.x) / 2,
                        (l_shoulder.y + r_shoulder.y) / 2)
        hip_mid = ((l_hip.x + r_hip.x) / 2,
                   (l_hip.y + r_hip.y) / 2)
        
        # Torso angle from vertical (shoulder to hip line)
        # 0° = upright (standing/sitting), 90° = horizontal (lying)
        torso_angle = calculate_angle(shoulder_mid, hip_mid)
        
        # Vertical distance between nose and hip (small when lying)
        nose_hip_vertical = abs(nose.y - hip_mid[1])
        
        # Fall criteria:
        # 1. Torso angle > 50° (closer to horizontal than vertical)
        # 2. OR nose and hip are at similar vertical level (< 15% of crop height)
        is_torso_horizontal = torso_angle > 50
        is_nose_near_hip = nose_hip_vertical < 0.15
        
        is_fallen = is_torso_horizontal or is_nose_near_hip
        
        debug = f"angle={torso_angle:.0f}° nose-hip={nose_hip_vertical:.2f}"
        return is_fallen, torso_angle, debug
        
    except Exception as e:
        return False, 0, f"err:{e}"

def is_fall_likely(bbox, frame_shape, pose_says_fallen):
    """
    Combined decision using YOLO bbox + MediaPipe pose.
    """
    x1, y1, x2, y2 = bbox
    box_w = x2 - x1
    box_h = y2 - y1
    if box_h == 0 or box_w == 0:
        return False
    
    frame_h, frame_w = frame_shape[:2]
    coverage = (box_w * box_h) / (frame_h * frame_w)
    aspect_ratio = box_w / box_h
    
    # If too close or too far, only trust pose
    if coverage > 0.65 or coverage < 0.05:
        return False  # Can't reliably decide
    
    # YOLO signals: bbox is wider than tall
    bbox_says_fallen = aspect_ratio > 1.4
    
    # HYBRID: trust if BOTH agree, OR if pose strongly says yes
    if pose_says_fallen and bbox_says_fallen:
        return True   # Strong confidence
    if pose_says_fallen and aspect_ratio > 1.1:
        return True   # Pose says yes, bbox slightly wider
    if bbox_says_fallen and aspect_ratio > 1.6:
        return True   # bbox very obviously horizontal
    
    return False

# ==== Camera Loop ====
camera = ThreadedCamera(CAMERA_INDEX)
time.sleep(1)

last_fall_time = 0
last_intrusion_time = 0
CAMERA_COOLDOWN = 10
frame_count = 0
fps_time = time.time()
fps_counter = 0
current_fps = 0

fall_frame_counter = 0
FALL_CONFIRM_FRAMES = 8  # ~0.3 sec

print("[✓] Camera started. Press 'q'=quit, 'r'=reset, 's'=snapshot")

def draw_hud(frame, fps):
    h, w, _ = frame.shape
    overlay = frame.copy()
    cv2.rectangle(overlay, (w - 280, 10), (w - 10, 300), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.6, frame, 0.4, 0, frame)
    cv2.putText(frame, "SENSOR STATUS", (w - 270, 35),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)
    items = [
        (f"Gas:    {sensor_state['gas']}",       sensor_state["gas_alert"]),
        (f"Flame:  {sensor_state['flame']}",     sensor_state["fire_alert"]),
        (f"Temp:   {sensor_state['temp']}C",     sensor_state["temp_alert"]),
        (f"Hum:    {sensor_state['hum']}%",      False),
        (f"Dist:   {sensor_state['dist']}cm",    sensor_state["prox_alert"]),
        (f"IR:     {sensor_state['ir']}",        sensor_state["motion_alert"]),
        (f"People: {sensor_state['person_count']}",  sensor_state["person_count"] > 0),
        (f"Torso:  {sensor_state['torso_angle']:.0f}deg", False),
        (f"FPS:    {fps:.1f}",                   False),
    ]
    y = 65
    for text, alert in items:
        color = (0, 0, 255) if alert else (0, 255, 0)
        cv2.putText(frame, text, (w - 265, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
        y += 25

last_results = None

try:
    while True:
        ret, frame = camera.read()
        if not ret or frame is None:
            time.sleep(0.01)
            continue
        
        frame = cv2.flip(frame, 1)
        h, w, _ = frame.shape
        frame_count += 1
        
        fps_counter += 1
        if time.time() - fps_time >= 1.0:
            current_fps = fps_counter / (time.time() - fps_time)
            fps_counter = 0
            fps_time = time.time()
        
        # YOLO inference
        if frame_count % INFER_EVERY_N_FRAMES == 0:
            results = model(frame, classes=[0], conf=CONFIDENCE_THRESHOLD,
                           device=device, verbose=False, half=(device=='cuda'))
            last_results = results
        else:
            results = last_results
        
        person_count = 0
        fall_detected = False
        current_torso_angle = 0
        
        if results:
            for r in results:
                for box in r.boxes:
                    x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().astype(int)
                    conf = float(box.conf[0])
                    person_count += 1
                    
                    # HYBRID: pose analysis on this person
                    pose_fallen, torso_angle, debug_info = analyze_pose_for_fall(
                        frame, (x1, y1, x2, y2))
                    
                    if torso_angle > current_torso_angle:
                        current_torso_angle = torso_angle
                    
                    # Combined decision
                    is_fallen = is_fall_likely((x1, y1, x2, y2), frame.shape, pose_fallen)
                    
                    if is_fallen:
                        fall_detected = True
                        color = (0, 0, 255)
                        label = f"FALLEN? {conf:.2f} | {debug_info}"
                    else:
                        color = (0, 255, 0)
                        label = f"Person {conf:.2f} | {debug_info}"
                    
                    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                    cv2.putText(frame, label, (x1, max(20, y1 - 10)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1)
        
        sensor_state["torso_angle"] = current_torso_angle
        
        # Confirm fall over multiple frames
        if fall_detected:
            fall_frame_counter += 1
        else:
            fall_frame_counter = 0
        
        confirmed_fall = fall_frame_counter >= FALL_CONFIRM_FRAMES
        
        sensor_state["person_count"] = person_count
        sensor_state["fall_detected"] = confirmed_fall
        
        now = time.time()
        
        if confirmed_fall and (now - last_fall_time) > CAMERA_COOLDOWN:
            send_to_arduino("FALL")
            send_telegram_photo("🧍 SAHDRS: Human FALL detected!", frame=frame)
            log_alert("FALL", f"Human fall detected (YOLO+Pose, angle={current_torso_angle:.0f}°)")
            last_fall_time = now
        
        if confirmed_fall:
            cv2.putText(frame, "FALL DETECTED!", (30, 60),
                        cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 3)
        
        if person_count > 0 and (now - last_intrusion_time) > CAMERA_COOLDOWN:
            send_to_arduino("INTRUSION")
            send_telegram_photo(f"🚷 SAHDRS: {person_count} person(s) detected!", frame=frame)
            log_alert("INTRUSION", f"{person_count} person(s) detected (YOLO)")
            last_intrusion_time = now
        
        cv2.putText(frame, "SAHDRS v2.3 - YOLO+Pose Hybrid", (10, 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        cv2.putText(frame, f"Device: {device.upper()} | FPS: {current_fps:.1f}",
                    (10, h - 15), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
        draw_hud(frame, current_fps)
        
        with frame_lock:
            latest_frame = frame.copy()
        
        cv2.imshow("SAHDRS v2.3 - Hybrid", frame)
        
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'): break
        elif key == ord('r'):
            send_to_arduino("RESET")
            send_telegram("✅ SAHDRS: System reset")
        elif key == ord('s'):
            send_telegram_photo("📸 SAHDRS: Manual snapshot")

finally:
    camera.release()
    cv2.destroyAllWindows()
    if arduino:
        arduino.close()
    pose_detector.close()
    with sensor_buffer_lock:
        if sensor_log_buffer:
            with open(SENSOR_LOG_FILE, "a", newline="") as f:
                csv.writer(f).writerows(sensor_log_buffer)
    print("[✓] Shutdown complete")