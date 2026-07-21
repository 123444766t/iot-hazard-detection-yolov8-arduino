/*
  =====================================================
  SAHDRS - Smart Autonomous Hazard Detection 
           & Response System
  
  Final Complete Version
  
  Components:
  - MQ-2 Gas Sensor      (A0)
  - Flame Sensor         (D2)
  - DHT11 Temp/Humidity  (D4)
  - Ultrasonic HC-SR04   (D5 TRIG, D6 ECHO)
  - Relay Module         (D7)
  - Buzzer Module        (D8)  [Active-LOW]
  - IR Sensor            (D9)
  - DC Fan               (via Relay)
  
  Communication:
  - Serial (USB) ↔ Python (camera, Telegram)
  
  Alert Levels:
  - Level 3 (HIGH):   Fire / High Temp → fast beeps + fan
  - Level 2 (MEDIUM): Gas / Camera Alert → steady beeps
  - Level 1 (LOW):    Proximity / Motion → gentle chirps
  - Level 0 (OFF):    No hazard → silent
  =====================================================
*/

#include <DHT.h>

// ==== Pin Definitions ====
#define MQ2_PIN     A0   // Gas sensor (analog)
#define FLAME_PIN   2    // Flame sensor (digital)
#define DHT_PIN     4    // DHT11 temperature & humidity
#define TRIG_PIN    5    // Ultrasonic trigger
#define ECHO_PIN    6    // Ultrasonic echo
#define RELAY_PIN   7    // Relay (fan control)
#define BUZZER_PIN  8    // Buzzer
#define IR_PIN      9    // IR motion sensor

// ==== Buzzer Polarity ====
// Set to true if buzzer beeps on LOW (silent on HIGH)
// Set to false if buzzer beeps on HIGH (silent on LOW)
#define BUZZER_ACTIVE_LOW true

// ==== DHT Setup ====
#define DHT_TYPE DHT11
DHT dht(DHT_PIN, DHT_TYPE);

// ==== Thresholds (adjust if needed) ====
const int   GAS_THRESHOLD       = 500;   // MQ-2 analog reading
const float TEMP_THRESHOLD      = 40.0;  // °C
const int   PROXIMITY_THRESHOLD = 20;    // cm

// ==== State Variables ====
bool alarmState = false;            // Camera alarm trigger from Python
unsigned long lastReadTime = 0;
const unsigned long READ_INTERVAL = 1000;

// ==== Buzzer Control ====
unsigned long lastBuzzerToggle = 0;
bool buzzerCurrentlyOn = false;
int activeAlertLevel = 0;  // 0=off, 1=low, 2=medium, 3=high

// =====================================================
// Buzzer Helper Functions (handles active-LOW polarity)
// =====================================================
void buzzerOn() {
  pinMode(BUZZER_PIN, OUTPUT);
  digitalWrite(BUZZER_PIN, BUZZER_ACTIVE_LOW ? LOW : HIGH);
}

void buzzerOff() {
  // Set as INPUT to fully disconnect (eliminates leakage ticking)
  pinMode(BUZZER_PIN, INPUT);
}

// =====================================================
// SETUP
// =====================================================
void setup() {
  Serial.begin(9600);

  pinMode(FLAME_PIN, INPUT);
  pinMode(RELAY_PIN, OUTPUT);
  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);
  pinMode(IR_PIN, INPUT);

  buzzerOff();                       // Start silent
  digitalWrite(RELAY_PIN, HIGH);     // Active-LOW relay → OFF

  dht.begin();
  
  // Boot confirmation: 2 short beeps
  buzzerOn();  delay(120);
  buzzerOff(); delay(120);
  buzzerOn();  delay(120);
  buzzerOff();
  
  Serial.println("SAHDRS Initialized");
  delay(2000);  // Brief stabilization for sensors
}

// =====================================================
// MAIN LOOP
// =====================================================
void loop() {
  // ===== Read All Sensors Every 1 Second =====
  if (millis() - lastReadTime >= READ_INTERVAL) {
    lastReadTime = millis();

    int   gasValue   = analogRead(MQ2_PIN);
    int   flameState = digitalRead(FLAME_PIN);
    float temp       = dht.readTemperature();
    float humidity   = dht.readHumidity();
    long  distance   = readUltrasonic();
    int   irState    = digitalRead(IR_PIN);

    if (isnan(temp))     temp = 0;
    if (isnan(humidity)) humidity = 0;

    // Send sensor data to Python (CSV format)
    Serial.print("DATA,");
    Serial.print(gasValue);   Serial.print(",");
    Serial.print(flameState); Serial.print(",");
    Serial.print(temp);       Serial.print(",");
    Serial.print(humidity);   Serial.print(",");
    Serial.print(distance);   Serial.print(",");
    Serial.println(irState);

    // ===== Hazard Detection =====
    bool gasLeak    = (gasValue > GAS_THRESHOLD);
    bool fire       = (flameState == LOW);
    bool highTemp   = (temp > TEMP_THRESHOLD && temp < 80);
    bool proximity  = (distance > 0 && distance < PROXIMITY_THRESHOLD);
    bool motion     = (irState == LOW);

    // ===== Determine Alert Level (Priority) =====
    int newLevel = 0;
    
    if (fire || highTemp) {
      newLevel = 3;
      activateFan(true);
    } 
    else if (gasLeak || alarmState) {
      newLevel = 2;
      activateFan(false);
    }
    else if (proximity || motion) {
      newLevel = 1;
      activateFan(false);
    } 
    else {
      newLevel = 0;
      activateFan(false);
    }

    // Reset buzzer cycle when alert level changes
    if (newLevel != activeAlertLevel) {
      activeAlertLevel = newLevel;
      lastBuzzerToggle = millis();
      buzzerCurrentlyOn = false;
      buzzerOff();
    }

    // Send hazard status to Python
    Serial.print("STATUS,");
    Serial.print(gasLeak);   Serial.print(",");
    Serial.print(fire);      Serial.print(",");
    Serial.print(highTemp);  Serial.print(",");
    Serial.print(proximity); Serial.print(",");
    Serial.println(motion);
  }

  // ===== Run Buzzer Pattern (non-blocking) =====
  controlBuzzer();

  // ===== Listen for Python Commands =====
  if (Serial.available()) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();

    if (cmd == "FALL" || cmd == "INTRUSION") {
      alarmState = true;
      Serial.print("ALERT_RECEIVED: ");
      Serial.println(cmd);
    }
    else if (cmd == "RESET") {
      alarmState = false;
      activeAlertLevel = 0;
      buzzerCurrentlyOn = false;
      buzzerOff();
      activateFan(false);
      Serial.println("System Reset");
    }
  }
}

// =====================================================
// Helper Functions
// =====================================================

long readUltrasonic() {
  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(2);
  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);
  
  long duration = pulseIn(ECHO_PIN, HIGH, 30000);
  if (duration == 0) return -1;  // No echo (out of range)
  return duration * 0.034 / 2;   // Convert to cm
}

void activateFan(bool on) {
  // Active-LOW relay: LOW = ON, HIGH = OFF
  digitalWrite(RELAY_PIN, on ? LOW : HIGH);
}

void controlBuzzer() {
  unsigned long now = millis();
  unsigned long onTime, offTime;
  
  // Level 0: Silent
  if (activeAlertLevel == 0) {
    buzzerOff();
    buzzerCurrentlyOn = false;
    return;
  }
  
  // Set timing based on alert level
  switch (activeAlertLevel) {
    case 1:  // LOW: gentle chirp every 2 sec
      onTime  = 100;
      offTime = 1900;
      break;
      
    case 2:  // MEDIUM: steady alarm beeps
      onTime  = 500;
      offTime = 500;
      break;
      
    case 3:  // HIGH: urgent rapid alarm
      onTime  = 200;
      offTime = 150;
      break;
      
    default:
      buzzerOff();
      return;
  }
  
  // Toggle buzzer based on timing
  if (buzzerCurrentlyOn) {
    if (now - lastBuzzerToggle >= onTime) {
      buzzerOff();
      buzzerCurrentlyOn = false;
      lastBuzzerToggle = now;
    }
  } else {
    if (now - lastBuzzerToggle >= offTime) {
      buzzerOn();
      buzzerCurrentlyOn = true;
      lastBuzzerToggle = now;
    }
  }
}
