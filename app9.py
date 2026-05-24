import tkinter as tk
from tkinter import ttk, messagebox
import subprocess
import serial.tools.list_ports
import threading
import os
import shutil
import tempfile
import requests
from datetime import datetime
import sys
from shutil import which

# ================== ICON SETTINGS ==================
ICON_FILENAME = "emer.ico"  # make sure emer.ico is bundled with --add-data

def resource_path(relative_path):
    """
    Get absolute path to resource, works for dev and for PyInstaller EXE.
    """
    try:
        base_path = sys._MEIPASS  # PyInstaller temp folder
    except Exception:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)

def set_window_icon(root):
    """
    Set the window icon using emer.ico. Works in .py and in PyInstaller EXE.
    """
    try:
        icon_path = resource_path(ICON_FILENAME)
        if os.path.exists(icon_path):
            if sys.platform.startswith("win"):
                root.iconbitmap(icon_path)  # best on Windows
            else:
                img = tk.PhotoImage(file=icon_path)
                root.iconphoto(True, img)
                root._icon_img = img  # keep reference
    except Exception:
        pass  # ignore icon issues

# ================== API SETTINGS (EDIT THIS) ==================
API_URL = "https://varsystems.site/save_member.php"
ROLLBACK_URL = "https://varsystems.site/delete_member.php"
# ===============================================================

# ================== EMBEDDED ARDUINO SKETCH (WiFi) ============
# ESP32 + WiFi + GPS + SW-420 (digital) + IRs, with placeholders
ARDUINO_SKETCH_TEMPLATE = r"""
#include <TinyGPS++.h>
#include <WiFi.h>
#include <HTTPClient.h>

// WiFi credentials
const char* ssid = "{{WIFI_SSID}}";
const char* password = "{{WIFI_PASSWORD}}";

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
"""
# ===============================================================

# Map user-friendly board names to FQBNs
BOARD_FQBN = {
    "Arduino Uno": "arduino:avr:uno",
    "Arduino Nano": "arduino:avr:nano",
    "ESP32 Dev Module": "esp32:esp32:esp32",  # requires esp32 core installed
}

def log(message):
    """Append text to the log box."""
    log_box.config(state="normal")
    log_box.insert(tk.END, message + "\n")
    log_box.see(tk.END)
    log_box.config(state="disabled")

def clear_log():
    log_box.config(state="normal")
    log_box.delete("1.0", tk.END)
    log_box.config(state="disabled")

def refresh_ports():
    ports = serial.tools.list_ports.comports()
    port_combo['values'] = [p.device for p in ports]
    if ports:
        port_combo.current(0)
    else:
        port_combo.set("")

# ------------- Firmware uploader path handling (BUNDLED) -------------

def get_base_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

def get_arduino_cli_executable():
    """
    Locate the uploader executable:
    1) Inside PyInstaller bundle (sys._MEIPASS)
    2) Next to the EXE / script
    3) System PATH
    """
    exe_name = "arduino-cli.exe" if os.name == "nt" else "arduino-cli"

    if getattr(sys, "frozen", False):
        bundle_dir = getattr(sys, "_MEIPASS", None)
        if bundle_dir:
            candidate = os.path.join(bundle_dir, exe_name)
            if os.path.exists(candidate):
                return candidate

    base_dir = get_base_dir()
    candidate = os.path.join(base_dir, exe_name)
    if os.path.exists(candidate):
        return candidate

    candidate = which("arduino-cli")
    if candidate:
        return candidate

    return None

def run_arduino_cli(cmd, cwd=None):
    """
    Run the firmware uploader tool and stream output in real time,
    but hide the literal name 'arduino-cli' from the GUI log.
    Returns True if exit code == 0, else False.
    """
    cli_path = get_arduino_cli_executable()
    if not cli_path:
        log("Firmware uploader tool not found.")
        log("Please make sure the uploader is bundled or installed.")
        messagebox.showerror(
            "Uploader not found",
            "The firmware uploader tool could not be found.\n"
            "Please ensure it is bundled or installed."
        )
        return False

    full_cmd = cmd[:]
    full_cmd[0] = cli_path

    try:
        creationflags = 0
        if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
            creationflags = subprocess.CREATE_NO_WINDOW  # no extra console

        process = subprocess.Popen(
            full_cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,  # line-buffered
            creationflags=creationflags
        )

        # Realtime reading, but sanitize 'arduino-cli' from the output
        for line in process.stdout:
            if not line:
                continue
            safe_line = (
                line.replace("arduino-cli", "uploader")
                    .replace("Arduino CLI", "uploader")
            )
            log(safe_line.rstrip())

        process.wait()
        return process.returncode == 0

    except FileNotFoundError:
        log("Firmware uploader executable path is invalid.")
        return False
    except Exception as e:
        log(f"Error running firmware uploader: {e}")
        return False

def get_next_device_id_and_save_member(fname, mname, lname, car_type):
    """
    Calls your PHP API to save member and returns the new device_id as string.
    """
    try:
        payload = {
            "fname": fname,
            "mname": mname,
            "lname": lname,
            "car_type": car_type
        }
        resp = requests.post(API_URL, data=payload, timeout=10)
        resp.raise_for_status()

        data = resp.json()
        if data.get("status") != "success":
            msg = data.get("message", "Unknown error from server.")
            raise RuntimeError("Server error: " + msg)

        device_id = data.get("device_id")
        if device_id is None:
            raise RuntimeError("Server did not return device_id.")
        return str(device_id)

    except Exception as e:
        raise RuntimeError("Failed to get device_id from API: %s" % e)

def rollback_member(device_id):
    """
    Calls a rollback PHP API to delete the member row by device_id.
    """
    try:
        log(f"Rolling back member with Device ID: {device_id}...")
        payload = {"device_id": device_id}
        resp = requests.post(ROLLBACK_URL, data=payload, timeout=10)
        resp.raise_for_status()
        log(f"Rollback response: {resp.text.strip()}")
    except Exception as e:
        log(f"ROLLBACK ERROR: {e}")

def do_upload(board_name, port, device_id, wifi_ssid, wifi_password):
    """
    Compile & upload using the embedded WiFi sketch.
    """
    fqbn = BOARD_FQBN.get(board_name)
    if not fqbn:
        messagebox.showerror("Error", "Unknown board type selected.")
        return False

    log("=== Starting upload ===")
    log(f"Board: {board_name} ({fqbn})")
    log(f"Port: {port}")
    log(f"Device ID: {device_id}")
    log(f"WiFi SSID: {wifi_ssid}")

    # Create temp project folder
    tmp_dir = tempfile.mkdtemp(prefix="arduino_upload_")
    project_name = "firmware"
    tmp_sketch_dir = os.path.join(tmp_dir, project_name)

    try:
        os.makedirs(tmp_sketch_dir, exist_ok=True)

        # Create the .ino from the embedded template
        ino_path = os.path.join(tmp_sketch_dir, f"{project_name}.ino")
        content = ARDUINO_SKETCH_TEMPLATE.replace("{{DEVICE_ID}}", device_id)
        content = content.replace("{{WIFI_SSID}}", wifi_ssid)
        content = content.replace("{{WIFI_PASSWORD}}", wifi_password)
        with open(ino_path, "w", encoding="utf-8") as f:
            f.write(content)
        log("Generating Code...")

        # Compile
        log("Compiling sketch...")
        success = run_arduino_cli(
            ["arduino-cli", "compile", "--fqbn", fqbn, tmp_sketch_dir],
            cwd=tmp_sketch_dir
        )
        if not success:
            log("Compilation failed.")
            messagebox.showerror("Upload Failed", "Compilation failed. See log for details.")
            return False

        # Upload
        log("Uploading Codes to Board...")
        success = run_arduino_cli(
            ["arduino-cli", "upload", "-p", port, "--fqbn", fqbn, tmp_sketch_dir],
            cwd=tmp_sketch_dir
        )
        if not success:
            log("Upload failed.")
            messagebox.showerror("Upload Failed", "Upload failed. See log for details.")
            return False

        log("=== Upload completed successfully! ===")
        messagebox.showinfo("Success", "Saved to server and upload completed successfully!")
        return True

    except Exception as e:
        log(f"ERROR: {e}")
        messagebox.showerror("Error", str(e))
        return False

    finally:
        try:
            shutil.rmtree(tmp_dir)
        except Exception:
            pass

def save_and_upload_thread():
    """
    1) Validate input
    2) Get device_id via API
    3) Compile & upload using embedded WiFi sketch
    4) Rollback DB entry if upload fails
    """
    board_name = board_combo.get().strip()
    port = port_combo.get().strip()

    fname = fname_var.get().strip()
    mname = mname_var.get().strip()
    lname = lname_var.get().strip()
    car_type = car_type_var.get().strip()
    wifi_ssid = wifi_ssid_var.get().strip()
    wifi_password = wifi_password_var.get().strip()

    if not board_name:
        messagebox.showerror("Error", "Please select a board type.")
        return
    if not port:
        messagebox.showerror("Error", "Please select a COM port.")
        return
    if not fname or not lname:
        messagebox.showerror("Error", "Please enter at least First Name and Last Name.")
        return
    if not car_type:
        messagebox.showerror("Error", "Please select a Car Type.")
        return
    if not wifi_ssid:
        messagebox.showerror("Error", "Please enter the WiFi SSID.")
        return
    if not wifi_password:
        messagebox.showerror("Error", "Please enter the WiFi Password.")
        return

    device_id = None

    try:
        log("Saving to server and Generating Device ID...")
        device_id = get_next_device_id_and_save_member(fname, mname, lname, car_type)
        device_id_var.set(device_id)
        log(f"New member saved with Device ID: {device_id}")
    except Exception as e:
        log(f"API ERROR: {e}")
        messagebox.showerror("API Error", f"Failed to save member/device.\n{e}")
        return

    success = do_upload(board_name, port, device_id, wifi_ssid, wifi_password)

    if not success and device_id is not None:
        rollback_member(device_id)

def start_save_and_upload():
    t = threading.Thread(target=save_and_upload_thread, daemon=True)
    t.start()

def reload_clear_fields():
    fname_var.set("")
    mname_var.set("")
    lname_var.set("")
    car_type_var.set("")
    device_id_var.set("")
    wifi_ssid_var.set("")
    wifi_password_var.set("")
    car_type_combo.set("")
    clear_log()
    log("Fields cleared.")

# ----------------- GUI SETUP -----------------

root = tk.Tk()
root.title("CapSU Pilar - Vehicle Device Uploader (WiFi)")

# Set custom window icon
set_window_icon(root)

main_frame = ttk.Frame(root, padding=10)
main_frame.grid(row=0, column=0, sticky="nsew")

root.columnconfigure(0, weight=1)
root.rowconfigure(0, weight=1)

# Board selection
ttk.Label(main_frame, text="Board Type:").grid(row=0, column=0, sticky="w")
board_combo = ttk.Combobox(main_frame, values=list(BOARD_FQBN.keys()), state="readonly", width=25)
board_combo.grid(row=0, column=1, sticky="we", padx=5, pady=2)
board_combo.current(2)  # default to ESP32 Dev Module

# Port selection
ttk.Label(main_frame, text="COM Port:").grid(row=1, column=0, sticky="w")
port_combo = ttk.Combobox(main_frame, state="readonly", width=25)
port_combo.grid(row=1, column=1, sticky="we", padx=5, pady=2)
ttk.Button(main_frame, text="Refresh Ports", command=refresh_ports).grid(row=1, column=2, padx=5, pady=2)

# Separator
ttk.Separator(main_frame, orient="horizontal").grid(row=2, column=0, columnspan=3, sticky="ew", pady=8)

# Member info
ttk.Label(main_frame, text="First Name:").grid(row=3, column=0, sticky="w")
fname_var = tk.StringVar()
ttk.Entry(main_frame, textvariable=fname_var, width=25).grid(row=3, column=1, sticky="we", padx=5, pady=2)

ttk.Label(main_frame, text="Middle Name:").grid(row=4, column=0, sticky="w")
mname_var = tk.StringVar()
ttk.Entry(main_frame, textvariable=mname_var, width=25).grid(row=4, column=1, sticky="we", padx=5, pady=2)

ttk.Label(main_frame, text="Last Name:").grid(row=5, column=0, sticky="w")
lname_var = tk.StringVar()
ttk.Entry(main_frame, textvariable=lname_var, width=25).grid(row=5, column=1, sticky="we", padx=5, pady=2)

ttk.Label(main_frame, text="Car Type:").grid(row=6, column=0, sticky="w")
car_type_var = tk.StringVar()
car_type_combo = ttk.Combobox(main_frame, textvariable=car_type_var,
                              values=["Sedan", "SUV", "PUV"], state="readonly", width=22)
car_type_combo.grid(row=6, column=1, sticky="we", padx=5, pady=2)

# Device ID (auto-generated)
ttk.Label(main_frame, text="Device ID (auto):").grid(row=7, column=0, sticky="w")
device_id_var = tk.StringVar()
device_id_entry = ttk.Entry(main_frame, textvariable=device_id_var, width=15, state="readonly")
device_id_entry.grid(row=7, column=1, sticky="w", padx=5, pady=2)

# Separator
ttk.Separator(main_frame, orient="horizontal").grid(row=8, column=0, columnspan=3, sticky="ew", pady=8)

# WiFi credentials
ttk.Label(main_frame, text="WiFi SSID:").grid(row=9, column=0, sticky="w")
wifi_ssid_var = tk.StringVar()
ttk.Entry(main_frame, textvariable=wifi_ssid_var, width=25).grid(row=9, column=1, sticky="we", padx=5, pady=2)

ttk.Label(main_frame, text="WiFi Password:").grid(row=10, column=0, sticky="w")
wifi_password_var = tk.StringVar()
ttk.Entry(main_frame, textvariable=wifi_password_var, width=25, show="*").grid(row=10, column=1, sticky="we", padx=5, pady=2)

# Buttons row: Save & Upload + Reload
button_frame = ttk.Frame(main_frame)
button_frame.grid(row=11, column=0, columnspan=3, pady=10)

upload_btn = ttk.Button(button_frame, text="Save & Upload", command=start_save_and_upload)
upload_btn.grid(row=0, column=0, padx=5)

reload_btn = ttk.Button(button_frame, text="Reload / Clear", command=reload_clear_fields)
reload_btn.grid(row=0, column=1, padx=5)

# Log box
ttk.Label(main_frame, text="Log:").grid(row=12, column=0, sticky="nw")
log_box = tk.Text(main_frame, height=15, width=80, state="disabled")
log_box.grid(row=12, column=0, columnspan=3, sticky="nsew", pady=5)

main_frame.columnconfigure(1, weight=1)
main_frame.rowconfigure(12, weight=1)

# Initial ports refresh
refresh_ports()

root.mainloop()
