import os
import re
import ast
import math
import time
import random
import asyncio
import operator
import webbrowser
import threading
import xml.etree.ElementTree as ET
import requests
import psutil
import pyautogui
import edge_tts
import pygame
import speech_recognition as sr
import customtkinter as ctk
import tkinter as tk
from google import genai

# Για τον έλεγχο έντασης ήχου στα Windows
from comtypes import CLSCTX_ALL
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

# ==========================================
# CONFIGURATION
# ==========================================
# NOTE: don't leave a real key hardcoded when you share/commit this file —
# move it to an environment variable, e.g.:
#   GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_KEY = ""
client = genai.Client(api_key=GEMINI_KEY)

STATE_COLORS = {
    "standby":    "#00e5ff",   # electric blue
    "listening":  "#39ff14",   # green
    "processing": "#ffb400",   # amber
    "speaking":   "#00c8ff",   # bright blue
    "error":      "#ff3b3b",   # red / warning
}

NEWS_FEED = [
    "STARK INDUSTRIES | Latest: Quantum Tunneling Data Uplink Stable",
    "MARK VII | Repulsor Calibration Nominal",
    "NETWORK | Encrypted Channel Active",
    "R&D | New Alloy Stress Test Passed",
    "SATCOM | Orbital Uplink: 3 Satellites In Range",
]

# ==========================================
# SYSTEM COMMANDS & FEATURES
# ==========================================
def set_volume(level):
    """Αλλάζει την ένταση ήχου των Windows (level: 0.0 έως 1.0)"""
    try:
        devices = AudioUtilities.GetSpeakers()
        interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        volume = interface.QueryInterface(IAudioEndpointVolume)
        volume.SetMasterVolumeLevelScalar(level, None)
        return True
    except Exception as e:
        print(f"[Volume Error]: {e}")
        return False


def get_weather(city="Athens"):
    """Παίρνει δωρεάν τα δεδομένα καιρού χωρίς API Key"""
    try:
        url = f"https://wttr.in/{city}?format=%C+%t"
        response = requests.get(url, timeout=3)
        if response.status_code == 200:
            return response.text.strip()
    except Exception:
        pass
    return "N/A"


def lock_workstation():
    try:
        os.system("rundll32.exe user32.dll,LockWorkStation")
        return True
    except Exception as e:
        print(f"[Lock Error]: {e}")
        return False


def get_battery_status():
    try:
        batt = psutil.sensors_battery()
        if batt is None:
            return "AC POWER (no battery)"
        plugged = "CHARGING" if batt.power_plugged else "ON BATTERY"
        return f"{int(batt.percent)}%  ({plugged})"
    except Exception:
        return "N/A"


def wiki_summary(topic):
    """Σύντομη περίληψη από τη Wikipedia (χωρίς API key)."""
    try:
        url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{requests.utils.quote(topic)}"
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            data = r.json()
            extract = data.get("extract")
            if extract:
                # keep it speakable — first 2 sentences
                sentences = extract.split(". ")
                return ". ".join(sentences[:2]).rstrip(".") + "."
        return f"I couldn't find a clear summary on {topic}, sir."
    except Exception:
        return "I couldn't reach Wikipedia right now, sir."


def get_public_ip():
    try:
        return requests.get("https://api.ipify.org", timeout=5).text.strip()
    except Exception:
        return "unavailable"


def take_screenshot():
    try:
        filename = f"screenshot_{time.strftime('%Y%m%d_%H%M%S')}.png"
        img = pyautogui.screenshot()
        img.save(filename)
        return filename
    except Exception as e:
        print(f"[Screenshot Error]: {e}")
        return None


def switch_window():
    try:
        pyautogui.keyDown("alt")
        pyautogui.press("tab")
        time.sleep(0.3)
        pyautogui.keyUp("alt")
        return True
    except Exception as e:
        print(f"[Switch Window Error]: {e}")
        return False


# --- Safe arithmetic calculator (no eval() on raw text) ---
_CALC_WORDS = {
    "plus": "+", "add": "+", "minus": "-", "subtract": "-",
    "times": "*", "multiplied by": "*", "multiply": "*",
    "divided by": "/", "divide": "/", "over": "/",
}
_ALLOWED_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub,
    ast.Mult: operator.mul, ast.Div: operator.truediv,
    ast.USub: operator.neg,
}


def _safe_eval(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_OPS:
        return _ALLOWED_OPS[type(node.op)](_safe_eval(node.left), _safe_eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_OPS:
        return _ALLOWED_OPS[type(node.op)](_safe_eval(node.operand))
    raise ValueError("Unsupported expression")


def safe_calculate(expression_text):
    text = expression_text.lower()
    for word, symbol in _CALC_WORDS.items():
        text = text.replace(word, f" {symbol} ")
    text = re.sub(r"[^0-9\.\+\-\*/\(\)\s]", "", text)
    try:
        tree = ast.parse(text, mode="eval")
        result = _safe_eval(tree.body)
        return result
    except Exception:
        return None


def geocode_place(place):
    """OpenStreetMap Nominatim — free, no API key. Requires a descriptive User-Agent."""
    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": place, "format": "json", "limit": 1},
            headers={"User-Agent": "JarvisPersonalAssistant/1.0"},
            timeout=5,
        )
        data = r.json()
        if data:
            return float(data[0]["lat"]), float(data[0]["lon"]), data[0].get("display_name", place)
    except Exception:
        pass
    return None


def get_current_location():
    """Approximate location from public IP — free, no API key."""
    try:
        r = requests.get("https://ipapi.co/json/", timeout=5)
        data = r.json()
        return data.get("latitude"), data.get("longitude"), data.get("city", "your area")
    except Exception:
        return None


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


def fetch_news(limit=5):
    """Google News RSS — free, no API key needed."""
    try:
        r = requests.get("https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en", timeout=5)
        root = ET.fromstring(r.content)
        titles = [item.find("title").text for item in root.iter("item")][:limit]
        return titles
    except Exception:
        return []


NOTES_FILE = "jarvis_notes.txt"


def add_note(text):
    with open(NOTES_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{time.strftime('%Y-%m-%d %H:%M')}] {text}\n")


def read_notes(limit=3):
    if not os.path.exists(NOTES_FILE):
        return []
    with open(NOTES_FILE, "r", encoding="utf-8") as f:
        lines = [l.strip() for l in f.readlines() if l.strip()]
    return lines[-limit:]


def execute_system_command(command):
    cmd = command.lower()

    # --- 1. Web & Applications ---
    if "youtube" in cmd:
        speak_jarvis("Opening YouTube for you, sir.")
        webbrowser.open("https://www.youtube.com")
        return True
    elif "google" in cmd or "browser" in cmd:
        speak_jarvis("Opening the browser, sir.")
        webbrowser.open("https://www.google.com")
        return True
    elif "spotify" in cmd:
        speak_jarvis("Opening Spotify, sir.")
        webbrowser.open("https://open.spotify.com")
        return True
    elif "vscode" in cmd or "code" in cmd:
        speak_jarvis("Launching Visual Studio Code, sir.")
        os.system("code")
        return True
    elif "calculator" in cmd:
        speak_jarvis("Opening the calculator, sir.")
        os.system("calc")
        return True
    elif "lock" in cmd:
        speak_jarvis("Locking the workstation, sir.")
        lock_workstation()
        return True

    # --- 2. Volume Control ---
    elif "mute" in cmd or "volume zero" in cmd:
        if set_volume(0.0):
            speak_jarvis("Audio muted, sir.")
        return True
    elif "volume max" in cmd or "volume 100" in cmd:
        if set_volume(1.0):
            speak_jarvis("Volume set to maximum, sir.")
        return True
    elif "volume medium" in cmd or "volume 50" in cmd:
        if set_volume(0.5):
            speak_jarvis("Volume set to fifty percent, sir.")
        return True

    # --- 3. Weather Forecast ---
    elif "weather" in cmd:
        weather_info = get_weather("Athens")
        speak_jarvis(f"The current weather status is {weather_info}, sir.")
        return True

    # --- 4. Battery ---
    elif "battery" in cmd or "power level" in cmd:
        speak_jarvis(f"Power status: {get_battery_status()}, sir.")
        return True

    # --- 5. Wikipedia / "tell me about X" ---
    elif "tell me about" in cmd or "wikipedia" in cmd:
        topic = cmd.split("about", 1)[-1].strip() if "about" in cmd else cmd.replace("wikipedia", "").strip()
        speak_jarvis(wiki_summary(topic))
        return True

    # --- 6. Public IP ---
    elif "ip address" in cmd:
        speak_jarvis(f"Your public IP address is {get_public_ip()}, sir.")
        return True

    # --- 7. Screenshot ---
    elif "screenshot" in cmd or "capture the screen" in cmd:
        filename = take_screenshot()
        if filename:
            speak_jarvis(f"Screenshot captured and saved as {filename}, sir.")
        else:
            speak_jarvis("I couldn't capture the screen, sir.")
        return True

    # --- 8. Switch window ---
    elif "switch window" in cmd or "switch the window" in cmd or "alt tab" in cmd:
        speak_jarvis("Switching windows, sir.")
        switch_window()
        return True

    # --- 9. Calculator ---
    elif "calculate" in cmd:
        result = safe_calculate(cmd.replace("calculate", ""))
        if result is not None:
            speak_jarvis(f"That comes to {result}, sir.")
        else:
            speak_jarvis("I couldn't parse that calculation, sir.")
        return True

    # --- 10. Location: "where is X" ---
    elif cmd.startswith("where is"):
        place = cmd.replace("where is", "", 1).strip()
        geo = geocode_place(place)
        here = get_current_location()
        if geo and here:
            lat, lon, name = geo
            hlat, hlon, hcity = here
            dist = haversine_km(hlat, hlon, lat, lon)
            speak_jarvis(f"{place} is roughly {dist:.0f} kilometers from {hcity}, sir.")
        else:
            speak_jarvis(f"I couldn't locate {place}, sir.")
        return True

    # --- 11. News headlines ---
    elif "news" in cmd or "headlines" in cmd:
        headlines = fetch_news(5)
        if headlines:
            speak_jarvis("Here are today's top headlines, sir.")
            for title in headlines:
                speak_jarvis(title)
        else:
            speak_jarvis("I couldn't reach the news feed right now, sir.")
        return True

    # --- 12. Notes ---
    elif "make a note" in cmd or "remember this" in cmd or "write this down" in cmd:
        speak_jarvis("What would you like me to note down, sir?")
        note_text = listen_for_audio("LISTENING FOR NOTE...", listening_state=True)
        if note_text:
            add_note(note_text)
            speak_jarvis("Noted, sir.")
        else:
            speak_jarvis("I didn't catch that, sir.")
        return True

    elif "read my notes" in cmd or "read notes" in cmd:
        notes = read_notes(3)
        if notes:
            speak_jarvis("Here are your most recent notes, sir.")
            for n in notes:
                speak_jarvis(n)
        else:
            speak_jarvis("You don't have any notes yet, sir.")
        return True

    # --- 13. Jokes ---
    elif "joke" in cmd:
        jokes = [
            "Why do programmers prefer dark mode? Because light attracts bugs, sir.",
            "I would tell you a UDP joke, but you might not get it, sir.",
            "There are only 10 types of people, sir — those who understand binary and those who don't.",
        ]
        speak_jarvis(random.choice(jokes))
        return True

    return False


# ==========================================
# VOICE SYNTHESIS (Monotone British Tone)
# ==========================================
async def generate_speech(text):
    communicate = edge_tts.Communicate(
        text, "en-GB-RyanNeural", rate="-12%", pitch="-8Hz"
    )
    await communicate.save("jarvis_voice.mp3")


def speak_jarvis(text):
    if hasattr(app, "update_status"):
        app.update_status(f"JARVIS: {text}")
    if hasattr(app, "log"):
        app.log(f"JARVIS: {text}")
    if hasattr(app, "set_state"):
        app.set_state("speaking")

    asyncio.run(generate_speech(text))

    pygame.mixer.init()
    pygame.mixer.music.load("jarvis_voice.mp3")
    pygame.mixer.music.play()
    while pygame.mixer.music.get_busy():
        pygame.time.Clock().tick(10)
    pygame.mixer.quit()

    if os.path.exists("jarvis_voice.mp3"):
        os.remove("jarvis_voice.mp3")

    if hasattr(app, "set_state"):
        app.set_state("standby")


# ==========================================
# SPEECH RECOGNITION (STT)
# ==========================================
def listen_for_audio(prompt_text=None, listening_state=False):
    if prompt_text and hasattr(app, "update_status"):
        app.update_status(prompt_text)
    if listening_state and hasattr(app, "set_state"):
        app.set_state("listening")

    recognizer = sr.Recognizer()
    with sr.Microphone() as source:
        recognizer.adjust_for_ambient_noise(source, duration=0.2)
        try:
            audio = recognizer.listen(source, timeout=3, phrase_time_limit=5)
            if hasattr(app, "set_state"):
                app.set_state("processing")
            text = recognizer.recognize_google(audio, language="en-US")
            return text
        except Exception:
            return None
        finally:
            if listening_state and hasattr(app, "set_state"):
                app.set_state("standby")


# ==========================================
# CORE ASSISTANT LOGIC (Background Thread)
# ==========================================
def jarvis_loop():
    speak_jarvis("Systems initialized. Standing by for your instructions, sir.")
    app.update_status("STANDBY: Say 'Jarvis' to activate...")
    app.set_state("standby")

    while True:
        wake_input = listen_for_audio()

        if wake_input and "jarvis" in wake_input.lower():
            speak_jarvis("At your service, sir.")

            user_command = listen_for_audio("LISTENING FOR COMMAND...", listening_state=True)
            if user_command:
                app.update_user_text(f"You: {user_command}")
                app.log(f"You: {user_command}")
                cmd = user_command.lower()

                if "exit" in cmd or "quit" in cmd:
                    speak_jarvis("Shutting down systems. Have a good day, sir.")
                    app.destroy()
                    break

                app.set_state("processing")

                if not execute_system_command(cmd):
                    try:
                        response = client.models.generate_content(
                            model="gemini-2.5-flash",
                            contents=user_command,
                            config={
                                "system_instruction": (
                                    "You are JARVIS, Tony Starks loyal AI assistant. Speak in an extremely well-spoken, "
                                    "polite, calm, and slightly monotone British gentleman voice. Be helpful, concise, "
                                    "and witty, keeping answers strictly to 1 short sentence. Always address the user as sir."
                                )
                            },
                        )
                        if response and response.text:
                            speak_jarvis(response.text)
                    except Exception:
                        app.set_state("error")
                        speak_jarvis("I seem to have encountered a temporary glitch, sir.")

            app.update_status("STANDBY: Say 'Jarvis' to activate...")
            app.set_state("standby")

        time.sleep(0.1)


# ==========================================
# ADVANCED STARK HUD INTERFACE
# ==========================================
class AdvancedJarvisHUD(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("J.A.R.V.I.S. MARK VII SYSTEM INTERFACE")
        self.geometry("1400x820")
        self.configure(fg_color="#02060d")
        ctk.set_appearance_mode("dark")

        self.state_name = "standby"
        self.state_color = STATE_COLORS["standby"]
        self.reactor_angle = 0
        self.pulse_t = 0.0
        self.mic_bars = [4] * 14
        self.log_lines = []
        self.news_index = 0

        # ---------------- HEADER ----------------
        self.header_frame = ctk.CTkFrame(self, fg_color="#071022", border_color="#00e5ff",
                                          border_width=1, corner_radius=10)
        self.header_frame.pack(fill="x", padx=15, pady=(15, 5))

        ctk.CTkLabel(self.header_frame, text="STARK INDUSTRIES  //  J.A.R.V.I.S. HUD INTERFACE",
                     font=("Consolas", 18, "bold"), text_color="#00e5ff").pack(side="left", padx=20, pady=10)

        self.state_pill = ctk.CTkLabel(self.header_frame, text="● STANDBY", font=("Consolas", 13, "bold"),
                                        text_color=STATE_COLORS["standby"])
        self.state_pill.pack(side="right", padx=20)

        self.date_label = ctk.CTkLabel(self.header_frame, text="--/--/----, ---", font=("Consolas", 13),
                                        text_color="#7fd8ff")
        self.date_label.pack(side="right", padx=20)

        self.time_label = ctk.CTkLabel(self.header_frame, text="00:00:00", font=("Consolas", 16, "bold"),
                                        text_color="#00d2ff")
        self.time_label.pack(side="right", padx=20, pady=10)

        # ---------------- BODY ----------------
        self.body_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.body_frame.pack(fill="both", expand=True, padx=15, pady=5)

        # =========== LEFT PANEL: GAUGES + WEATHER ===========
        self.left_panel = ctk.CTkFrame(self.body_frame, fg_color="#071022", border_color="#00e5ff",
                                        border_width=1, width=300)
        self.left_panel.pack(side="left", fill="y", padx=(0, 10), pady=5)
        self.left_panel.pack_propagate(False)

        ctk.CTkLabel(self.left_panel, text="[ SYSTEM MONITOR ]", font=("Consolas", 14, "bold"),
                     text_color="#00e5ff").pack(pady=(15, 5))

        self.gauge_canvas = tk.Canvas(self.left_panel, width=270, height=270, bg="#071022",
                                       highlightthickness=0)
        self.gauge_canvas.pack(pady=5)

        self.net_prev = psutil.net_io_counters()
        self.net_speed_kbps = 0.0

        ctk.CTkLabel(self.left_panel, text="[ WEATHER ]", font=("Consolas", 13, "bold"),
                     text_color="#00e5ff").pack(pady=(15, 2))
        self.weather_label = ctk.CTkLabel(self.left_panel, text="Fetching...", font=("Consolas", 13),
                                           text_color="#7fd8ff", wraplength=260, justify="left")
        self.weather_label.pack(pady=2)

        ctk.CTkLabel(self.left_panel, text="[ MIC INPUT ]", font=("Consolas", 13, "bold"),
                     text_color="#00e5ff").pack(pady=(20, 5))
        self.mic_canvas = tk.Canvas(self.left_panel, width=260, height=55, bg="#071022",
                                     highlightthickness=0)
        self.mic_canvas.pack(pady=2)

        # =========== CENTER PANEL: REACTOR + LOG + HEX MENU ===========
        self.center_panel = ctk.CTkFrame(self.body_frame, fg_color="#071022", border_color="#00e5ff",
                                          border_width=1)
        self.center_panel.pack(side="left", fill="both", expand=True, pady=5)

        self.canvas = tk.Canvas(self.center_panel, width=280, height=280, bg="#071022",
                                 highlightthickness=0)
        self.canvas.pack(pady=(15, 5))
        self.draw_static_reactor()

        self.status_label = ctk.CTkLabel(self.center_panel, text="INITIALIZING HUD...",
                                          font=("Consolas", 14, "bold"), text_color="#00e5ff", wraplength=520)
        self.status_label.pack(pady=(5, 2))

        self.user_label = ctk.CTkLabel(self.center_panel, text="", font=("Consolas", 13, "italic"),
                                        text_color="#ffffff", wraplength=520)
        self.user_label.pack(pady=2)

        ctk.CTkLabel(self.center_panel, text="[ SYSTEM LOG ]", font=("Consolas", 12, "bold"),
                     text_color="#00e5ff").pack(pady=(10, 2))
        self.console = ctk.CTkTextbox(self.center_panel, fg_color="#050d18", text_color="#66e0ff",
                                       font=("Consolas", 11), border_color="#00e5ff", border_width=1, height=140)
        self.console.pack(fill="both", expand=True, padx=20, pady=(0, 10))
        self.console.configure(state="disabled")

        ctk.CTkLabel(self.center_panel, text="[ QUICK PROTOCOLS ]", font=("Consolas", 12, "bold"),
                     text_color="#00e5ff").pack(pady=(0, 4))
        self.hex_canvas = tk.Canvas(self.center_panel, width=660, height=110, bg="#071022",
                                     highlightthickness=0)
        self.hex_canvas.pack(pady=(0, 10))
        self.build_hex_menu()

        # Bottom status/power bar
        self.status_bar = ctk.CTkLabel(self.center_panel, text="J.A.R.V.I.S. — ONLINE",
                                        font=("Consolas", 12, "bold"), text_color=STATE_COLORS["standby"])
        self.status_bar.pack(pady=(0, 10))

        # =========== RIGHT PANEL: SUIT WIREFRAME + NEWS ===========
        self.right_panel = ctk.CTkFrame(self.body_frame, fg_color="#071022", border_color="#00e5ff",
                                         border_width=1, width=320)
        self.right_panel.pack(side="right", fill="y", padx=(10, 0), pady=5)
        self.right_panel.pack_propagate(False)

        ctk.CTkLabel(self.right_panel, text="[ SYSTEMS ANALYSIS: MARK VII ]", font=("Consolas", 13, "bold"),
                     text_color="#00e5ff").pack(pady=(15, 5))

        self.suit_canvas = tk.Canvas(self.right_panel, width=280, height=320, bg="#071022",
                                      highlightthickness=0)
        self.suit_canvas.pack(pady=5)

        self.armor_label = ctk.CTkLabel(self.right_panel, text="ARMOR INTEGRITY: 98%",
                                         font=("Consolas", 13, "bold"), text_color="#00e5ff")
        self.armor_label.pack(pady=(5, 15))

        ctk.CTkLabel(self.right_panel, text="[ NETWORK FEED ]", font=("Consolas", 13, "bold"),
                     text_color="#00e5ff").pack(pady=(0, 5))
        self.news_label = ctk.CTkLabel(self.right_panel, text=NEWS_FEED[0], font=("Consolas", 11),
                                        text_color="#7fd8ff", wraplength=280, justify="left")
        self.news_label.pack(pady=2, padx=10)

        # Kick off animation loops
        self.update_telemetry()
        self.animate()
        self.rotate_news()

    # ---------------- STATIC REACTOR RINGS ----------------
    def draw_static_reactor(self):
        self.canvas.create_oval(10, 10, 270, 270, outline="#023241", width=1)
        self.canvas.create_oval(30, 30, 250, 250, outline="#004a5f", width=1, dash=(2, 6))
        self.canvas.create_oval(60, 60, 220, 220, outline="#023241", width=1)
        # radial tick marks around outer ring
        cx = cy = 140
        for i in range(36):
            ang = math.radians(i * 10)
            x0 = cx + 132 * math.cos(ang)
            y0 = cy + 132 * math.sin(ang)
            x1 = cx + 122 * math.cos(ang)
            y1 = cy + 122 * math.sin(ang)
            self.canvas.create_line(x0, y0, x1, y1, fill="#023241")

    # ---------------- HEX QUICK MENU ----------------
    def build_hex_menu(self):
        labels = ["DATABASE", "SECURITY", "ENVIRONMENT", "POWER", "COMMS", "NEWS"]
        actions = [self.hex_database, self.hex_security, self.hex_environment,
                   self.hex_power, self.hex_comms, self.hex_news]
        r = 34
        spacing = 108
        start_x = 60
        cy = 40
        self.hex_items = []
        for i, (label, action) in enumerate(zip(labels, actions)):
            cx = start_x + i * spacing
            pts = []
            for k in range(6):
                ang = math.radians(60 * k - 30)
                pts.extend([cx + r * math.cos(ang), cy + r * math.sin(ang)])
            hexid = self.hex_canvas.create_polygon(pts, outline="#00e5ff", fill="#0a1a2c", width=2)
            txtid = self.hex_canvas.create_text(cx, cy + r + 14, text=label, fill="#7fd8ff",
                                                 font=("Consolas", 9, "bold"))
            self.hex_canvas.tag_bind(hexid, "<Button-1>", lambda e, a=action: a())
            self.hex_canvas.tag_bind(hexid, "<Enter>",
                                      lambda e, h=hexid: self.hex_canvas.itemconfig(h, fill="#123048"))
            self.hex_canvas.tag_bind(hexid, "<Leave>",
                                      lambda e, h=hexid: self.hex_canvas.itemconfig(h, fill="#0a1a2c"))
            self.hex_items.append(hexid)

    def hex_database(self):
        self.log("Accessing local database... records synced.")

    def hex_security(self):
        self.log("Security protocol engaged — locking workstation.")
        threading.Thread(target=lock_workstation, daemon=True).start()

    def hex_environment(self):
        self.log("Environmental control: audio levels normalized to 50%.")
        threading.Thread(target=lambda: set_volume(0.5), daemon=True).start()

    def hex_power(self):
        self.log(f"Power diagnostics: {get_battery_status()}")

    def hex_comms(self):
        self.log("Opening comms channel (mail client).")
        webbrowser.open("https://mail.google.com")

    def hex_news(self):
        self.log("Pulling latest headlines...")

        def _fetch():
            headlines = fetch_news(5)
            if headlines:
                for h in headlines:
                    self.log(f"NEWS: {h}")
            else:
                self.log("News feed unavailable.")
        threading.Thread(target=_fetch, daemon=True).start()

    # ---------------- ANIMATION LOOP ----------------
    def animate(self):
        color = self.state_color

        # rotating segmented rings (reactor)
        self.canvas.delete("rotating")
        for i in range(8):
            start = self.reactor_angle + i * 45
            self.canvas.create_arc(50, 50, 230, 230, start=start, extent=24,
                                    style="arc", outline=color, width=5, tags="rotating")
        for i in range(16):
            start = -self.reactor_angle * 1.4 + i * 22.5
            self.canvas.create_arc(35, 35, 245, 245, start=start, extent=7,
                                    style="arc", outline=color, width=2, tags="rotating")

        # pulsing triangular core
        self.canvas.delete("core")
        pulse = 26 + 7 * math.sin(self.pulse_t)
        cx, cy = 140, 140
        self.canvas.create_oval(cx - pulse - 14, cy - pulse - 14, cx + pulse + 14, cy + pulse + 14,
                                 outline=color, width=1, tags="core")
        self.canvas.create_oval(cx - pulse, cy - pulse, cx + pulse, cy + pulse,
                                 fill=color, outline="", tags="core")
        self.canvas.create_polygon(
            cx, cy - pulse * 0.65, cx - pulse * 0.55, cy + pulse * 0.4,
            cx + pulse * 0.55, cy + pulse * 0.4,
            fill="#02060d", outline="", tags="core"
        )
        self.reactor_angle = (self.reactor_angle + 3) % 360
        self.pulse_t += 0.12

        # mic bars
        self.mic_canvas.delete("bars")
        active = self.state_name == "listening"
        width_per_bar = 260 / len(self.mic_bars)
        for i in range(len(self.mic_bars)):
            target = random.randint(6, 46) if active else 4
            self.mic_bars[i] += (target - self.mic_bars[i]) * 0.5
            h = max(2, self.mic_bars[i])
            x0 = i * width_per_bar + 3
            x1 = x0 + width_per_bar - 5
            y1 = 50
            y0 = y1 - h
            bar_color = STATE_COLORS["listening"] if active else "#0d3040"
            self.mic_canvas.create_rectangle(x0, y0, x1, y1, fill=bar_color, outline="", tags="bars")

        # suit wireframe glow pulse tied to state
        self.draw_suit(color)

        self.after(45, self.animate)

    # ---------------- CIRCULAR GAUGES ----------------
    def draw_gauge(self, cx, cy, r, value_pct, color, label, value_text, tag, sub_text=None):
        self.gauge_canvas.delete(tag)
        value_pct = max(0, min(100, value_pct))
        # background arc (270 deg sweep, opening at bottom)
        self.gauge_canvas.create_arc(cx - r, cy - r, cx + r, cy + r, start=225, extent=-270,
                                      style="arc", outline="#0d3040", width=9, tags=tag)
        # foreground value arc
        sweep = -270 * (value_pct / 100)
        self.gauge_canvas.create_arc(cx - r, cy - r, cx + r, cy + r, start=225, extent=sweep,
                                      style="arc", outline=color, width=9, tags=tag)
        # shrink the font automatically if the value text is long, so it never spills
        # out of the dial into a neighboring gauge
        font_size = 13 if len(value_text) <= 4 else (11 if len(value_text) <= 7 else 9)
        value_y = cy - 6 if sub_text else cy - 4
        self.gauge_canvas.create_text(cx, value_y, text=value_text, fill=color,
                                       font=("Consolas", font_size, "bold"), tags=tag)
        if sub_text:
            self.gauge_canvas.create_text(cx, cy + 8, text=sub_text, fill=color,
                                           font=("Consolas", 8, "bold"), tags=tag)
        self.gauge_canvas.create_text(cx, cy + 22, text=label, fill="#5b8fa8",
                                       font=("Consolas", 9), tags=tag)

    # ---------------- SUIT WIREFRAME ----------------
    def draw_suit(self, color):
        c = self.suit_canvas
        c.delete("suit")
        cx = 140
        # head
        c.create_oval(cx - 32, 15, cx + 32, 80, outline=color, width=2, tags="suit")
        c.create_line(cx - 14, 42, cx - 4, 42, fill=color, width=3, tags="suit")  # eye L
        c.create_line(cx + 4, 42, cx + 14, 42, fill=color, width=3, tags="suit")  # eye R
        # neck
        c.create_line(cx, 80, cx, 100, fill=color, width=2, tags="suit")
        # shoulders / torso outline
        c.create_line(cx, 100, cx - 90, 140, fill=color, width=2, tags="suit")
        c.create_line(cx, 100, cx + 90, 140, fill=color, width=2, tags="suit")
        c.create_line(cx - 90, 140, cx - 70, 250, fill=color, width=2, tags="suit")
        c.create_line(cx + 90, 140, cx + 70, 250, fill=color, width=2, tags="suit")
        c.create_line(cx - 70, 250, cx - 30, 290, fill=color, width=2, tags="suit")
        c.create_line(cx + 70, 250, cx + 30, 290, fill=color, width=2, tags="suit")
        c.create_line(cx - 30, 290, cx + 30, 290, fill=color, width=2, tags="suit")
        # chest panel lines (pecs)
        c.create_line(cx, 100, cx - 35, 175, fill=color, width=1, tags="suit")
        c.create_line(cx, 100, cx + 35, 175, fill=color, width=1, tags="suit")
        c.create_line(cx - 35, 175, cx, 210, fill=color, width=1, tags="suit")
        c.create_line(cx + 35, 175, cx, 210, fill=color, width=1, tags="suit")
        # chest arc-reactor glow
        pulse = 6 + 3 * math.sin(self.pulse_t)
        c.create_oval(cx - 14 - pulse, 150 - pulse, cx + 14 + pulse, 178 + pulse,
                      outline=color, width=1, tags="suit")
        c.create_oval(cx - 10, 154, cx + 10, 174, fill=color, outline="", tags="suit")
        c.create_text(cx, 305, text="ONLINE", fill=color, font=("Consolas", 10, "bold"), tags="suit")

    # ---------------- TELEMETRY ----------------
    def update_telemetry(self):
        now = time.localtime()
        self.time_label.configure(text=time.strftime("%H:%M:%S", now))
        self.date_label.configure(text=time.strftime("%d/%m/%Y, %A", now))

        cpu = psutil.cpu_percent()
        ram = psutil.virtual_memory().percent

        net_now = psutil.net_io_counters()
        bytes_delta = (net_now.bytes_sent + net_now.bytes_recv) - (self.net_prev.bytes_sent + self.net_prev.bytes_recv)
        self.net_prev = net_now
        self.net_speed_kbps = (bytes_delta / 1024)  # per ~1s tick
        net_pct = min(100, self.net_speed_kbps / 5)  # scale for the dial (5 MB/s ~= full)

        self.draw_gauge(65, 65, 55, cpu, "#00e5ff", "CPU", f"{cpu:.0f}%", "gauge_cpu")
        self.draw_gauge(200, 65, 55, ram, "#ffb400" if ram > 85 else "#00e5ff", "RAM", f"{ram:.0f}%", "gauge_ram")
        self.draw_gauge(65, 205, 55, net_pct, "#39ff14", "NET",
                         f"{self.net_speed_kbps:.0f}", "gauge_net", sub_text="KB/s")

        batt_pct = 100
        charging = None
        try:
            b = psutil.sensors_battery()
            if b:
                batt_pct = b.percent
                charging = "CHG" if b.power_plugged else "BATT"
        except Exception:
            pass
        self.draw_gauge(200, 205, 55, batt_pct, "#00e5ff", "BATTERY",
                         f"{batt_pct:.0f}%", "gauge_batt", sub_text=charging)

        self.after(1000, self.update_telemetry)

    def rotate_news(self):
        self.news_index = (self.news_index + 1) % len(NEWS_FEED)
        self.news_label.configure(text=NEWS_FEED[self.news_index])
        self.after(4000, self.rotate_news)

    # ---------------- STATE / LOG HOOKS ----------------
    def set_state(self, state_name):
        if state_name not in STATE_COLORS:
            state_name = "standby"
        self.state_name = state_name
        self.state_color = STATE_COLORS[state_name]
        self.state_pill.configure(text=f"● {state_name.upper()}", text_color=self.state_color)
        self.status_bar.configure(text=f"J.A.R.V.I.S. — {state_name.upper()}", text_color=self.state_color)

    def update_status(self, text):
        self.status_label.configure(text=text)

    def update_user_text(self, text):
        self.user_label.configure(text=text)

    def log(self, text):
        timestamp = time.strftime("%H:%M:%S")
        self.log_lines.append(f"[{timestamp}] {text}")
        self.log_lines = self.log_lines[-200:]
        self.console.configure(state="normal")
        self.console.delete("1.0", "end")
        self.console.insert("end", "\n".join(self.log_lines))
        self.console.see("end")
        self.console.configure(state="disabled")


# ==========================================
# MAIN EXECUTION
# ==========================================
if __name__ == "__main__":
    app = AdvancedJarvisHUD()
    threading.Thread(target=jarvis_loop, daemon=True).start()

    def load_weather_bg():
        w = get_weather("Athens")
        app.weather_label.configure(text=f"ATHENS, GREECE\n{w}")
    threading.Thread(target=load_weather_bg, daemon=True).start()

    app.mainloop()
