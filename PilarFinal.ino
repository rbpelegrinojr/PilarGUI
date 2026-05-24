#include <TinyGPS++.h>
#include <WiFi.h>
#include <HTTPClient.h>

// WiFi credentials
const char* ssid = "Wifi";
const char* password = "R0d3n_214";

// GPS
HardwareSerial neogps(2);  // TX = GPIO16, RX = GPIO17
TinyGPSPlus gps;

// MH Vibration Sensor
#define VIB_DIGITAL 35
#define VIB_ANALOG  34

// IR Sensors
#define IR1_PIN 32
#define IR2_PIN 33

// Timing
unsigned long previousMillis = 0;
const unsigned long interval = 30000; // send every 30s if triggered

const char* DEVICE_ID = "{{DEVICE_ID}}";
const char* SERVER_URL = "http://helmet.capsupont.com/gpsdata.php";

// Flags
bool vibTriggered = false;

void setup() {
  Serial.begin(115200);
  delay(1000);

  // GPS setup
  neogps.begin(9600, SERIAL_8N1, 16, 17);

  // WiFi setup
  Serial.println("Connecting to WiFi...");
  WiFi.begin(ssid, password);
  
  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 20) {
    delay(500);
    Serial.print(".");
    attempts++;
  }
  
  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\nWiFi connected!");
    Serial.print("IP address: ");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println("\nFailed to connect to WiFi");
  }

  // Vibration sensor setup
  pinMode(VIB_DIGITAL, INPUT);

  // IR sensors setup
  pinMode(IR1_PIN, INPUT);
  pinMode(IR2_PIN, INPUT);

  Serial.println("Setup Complete");
}

void loop() {
  // Check WiFi connection, reconnect if needed
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("WiFi disconnected, attempting to reconnect...");
    WiFi.reconnect();
    delay(5000);
  }

  // Check MH vibration sensor
  if (digitalRead(VIB_DIGITAL) == LOW) {
    vibTriggered = true;
    Serial.print("MH Vibration Detected, Level: ");
    Serial.println(analogRead(VIB_ANALOG));
  }

  // Update GPS data
  while (neogps.available()) gps.encode(neogps.read());

  // Send if vibration is triggered
  unsigned long currentMillis = millis();
  if (vibTriggered && (currentMillis - previousMillis >= interval)) {
    previousMillis = currentMillis;

    // Count IR sensors triggered
    int irCount = 0;
    if (digitalRead(IR1_PIN) == LOW) irCount++;
    if (digitalRead(IR2_PIN) == LOW) irCount++;

    Serial.print("IR sensors triggered: ");
    Serial.println(irCount);

    sendGpsToServer(irCount);

    // Reset triggers
    vibTriggered = false;
  }
}

// === GPS Sending Function via WiFi ===
int sendGpsToServer(int irCount) {
  bool newData = false;

  unsigned long start = millis();
  while (millis() - start < 2000) {
    while (neogps.available()) {
      if (gps.encode(neogps.read())) {
        newData = true;
        break;
      }
    }
  }

  if (newData && gps.location.isValid()) {
    String latitude = String(gps.location.lat(), 6);
    String longitude = String(gps.location.lng(), 6);

    Serial.print("Latitude: "); Serial.println(latitude);
    Serial.print("Longitude: "); Serial.println(longitude);

    if (WiFi.status() == WL_CONNECTED) {
      HTTPClient http;
      
      // Construct the URL with parameters
      String url = String(SERVER_URL) + "?lat=" + latitude +
                   "&lng=" + longitude +
                   "&ir=" + String(irCount) +
                   "&device_id=" + String(DEVICE_ID);

      Serial.print("Sending request to: ");
      Serial.println(url);

      // Start HTTP request
      http.begin(url);
      http.addHeader("Content-Type", "application/x-www-form-urlencoded");
      
      // Send GET request
      int httpResponseCode = http.GET();

      if (httpResponseCode > 0) {
        String response = http.getString();
        Serial.print("HTTP Response code: ");
        Serial.println(httpResponseCode);
        Serial.print("Response: ");
        Serial.println(response);
      } else {
        Serial.print("Error code: ");
        Serial.println(httpResponseCode);
      }
      
      http.end();
    } else {
      Serial.println("WiFi not connected. Cannot send data.");
    }
  } else {
    Serial.println("No valid GPS fix.");
  }

  return 1;
}