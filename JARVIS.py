"""
J.A.R.V.I.S. MARK VII — Full functional rebuild
==============================================
- Continuous wake-word ("Jarvis") + Push-to-Talk + Text input
- Dense cinematic HUD closer to the movie reference images
- All system commands working with visible feedback
- Real clickable buttons
"""

import os
import re
import ast
import math
import time
import random
import queue
import asyncio
import operator
import webbrowser
import threading
import xml.etree.ElementTree as ET
import traceback

import requests
import psutil
import edge_tts
import pygame
import speech_recognition as sr
import customtkinter as ctk
import tkinter as tk
from google import genai

try:
    import pyautogui
    HAS_PYAUTOGUI = True
except ImportError:
    HAS_PYAUTOGUI = False

try:
    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
    HAS_PYCAW = True
except ImportError:
    HAS_PYCAW = False

# ==========================================
# CONFIG
# ==========================================
# Prefer environment variable. Fallback to the key you used before so it works out of the box.
GEMINI_KEY = os.environ.get("GEMINI_API_KEY") or ""

try:
    client = genai.Client(api_key=GEMINI_KEY)
except Exception as e:
    print(f"[Gemini init error]: {e}")
    client = None

STATE_COLORS = {
    "standby":    "#00e5ff",
    "listening":  "#39ff14",
    "processing": "#ffb400",
    "speaking":   "#00c8ff",
    "error":      "#ff3b3b",
}

NEWS_FEED = [
    "STARK INDUSTRIES | Quantum Tunneling Data Uplink Stable",
    "MARK VII | Repulsor Calibration Nominal",
    "NETWORK | Encrypted Channel Active",
    "R&D | New Alloy Stress Test Passed",
    "SATCOM | Orbital Uplink: 3 Satellites In Range",
]

ui_queue = queue.Queue()
app = None  # set in main

# ==========================================
# SYSTEM TOOLS
# ==========================================
def set_volume(level: float) -> bool:
    if not HAS_PYCAW:
        return False
    try:
        devices = AudioUtilities.GetSpeakers()
        interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        volume = interface.QueryInterface(IAudioEndpointVolume)
        volume.SetMasterVolumeLevelScalar(max(0.0, min(1.0, level)), None)
        return True
    except Exception as e:
        print(f"[Volume Error]: {e}")
        return False


def get_weather(city: str = "Athens") -> str:
    try:
        r = requests.get(f"https://wttr.in/{city}?format=%C+%t", timeout=5)
        if r.status_code == 200:
            return r.text.strip()
    except Exception:
        pass
    return "Unavailable"


def lock_workstation() -> bool:
    try:
        os.system("rundll32.exe user32.dll,LockWorkStation")
        return True
    except Exception:
        return False


def get_battery_status() -> str:
    try:
        batt = psutil.sensors_battery()
        if batt is None:
            return "AC POWER (desktop)"
        status = "CHARGING" if batt.power_plugged else "ON BATTERY"
        return f"{int(batt.percent)}% ({status})"
    except Exception:
        return "N/A"


def wiki_summary(topic: str) -> str:
    try:
        url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{requests.utils.quote(topic)}"
        r = requests.get(url, timeout=6)
        if r.status_code == 200:
            extract = r.json().get("extract")
            if extract:
                sentences = extract.split(". ")
                return ". ".join(sentences[:2]).rstrip(".") + "."
        return f"I could not find a clear summary on {topic}, sir."
    except Exception:
        return "I could not reach Wikipedia right now, sir."


def get_public_ip() -> str:
    try:
        return requests.get("https://api.ipify.org", timeout=4).text.strip()
    except Exception:
        return "unavailable"


def take_screenshot():
    if not HAS_PYAUTOGUI:
        return None
    try:
        filename = f"screenshot_{time.strftime('%Y%m%d_%H%M%S')}.png"
        pyautogui.screenshot().save(filename)
        return filename
    except Exception as e:
        print(f"[Screenshot]: {e}")
        return None


def switch_window() -> bool:
    if not HAS_PYAUTOGUI:
        return False
    try:
        pyautogui.keyDown("alt")
        pyautogui.press("tab")
        time.sleep(0.3)
        pyautogui.keyUp("alt")
        return True
    except Exception:
        return False


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
    raise ValueError("Unsupported")


def safe_calculate(expression_text: str):
    text = expression_text.lower()
    for word, symbol in _CALC_WORDS.items():
        text = text.replace(word, f" {symbol} ")
    text = re.sub(r"[^0-9\.\+\-\*/\(\)\s]", "", text)
    try:
        tree = ast.parse(text, mode="eval")
        return _safe_eval(tree.body)
    except Exception:
        return None


def geocode_place(place: str):
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


def fetch_news(limit: int = 5):
    try:
        r = requests.get("https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en", timeout=6)
        root = ET.fromstring(r.content)
        return [item.find("title").text for item in root.iter("item") if item.find("title") is not None][:limit]
    except Exception:
        return []


NOTES_FILE = "jarvis_notes.txt"


def add_note(text: str):
    with open(NOTES_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{time.strftime('%Y-%m-%d %H:%M')}] {text}\n")


def read_notes(limit: int = 3):
    if not os.path.exists(NOTES_FILE):
        return []
    with open(NOTES_FILE, "r", encoding="utf-8") as f:
        lines = [l.strip() for l in f if l.strip()]
    return lines[-limit:]


# ==========================================
# COMMAND ROUTER
# ==========================================
def execute_system_command(command: str) -> bool:
    cmd = command.lower().strip()
    ui_queue.put(("LOG", f"Processing command: {command}"))

    # Apps
    if "youtube" in cmd:
        speak_jarvis("Opening YouTube, sir.")
        webbrowser.open("https://www.youtube.com")
        return True
    if "google" in cmd or "browser" in cmd:
        speak_jarvis("Opening the browser, sir.")
        webbrowser.open("https://www.google.com")
        return True
    if "spotify" in cmd:
        speak_jarvis("Opening Spotify, sir.")
        webbrowser.open("https://open.spotify.com")
        return True
    if "vscode" in cmd or ("open" in cmd and "code" in cmd):
        speak_jarvis("Launching Visual Studio Code, sir.")
        os.system("code")
        return True
    if "calculator" in cmd:
        speak_jarvis("Opening the calculator, sir.")
        os.system("calc")
        return True
    if "lock" in cmd:
        speak_jarvis("Locking the workstation, sir.")
        lock_workstation()
        return True

    # Volume
    if "mute" in cmd or "volume zero" in cmd or "volume 0" in cmd:
        ok = set_volume(0.0)
        speak_jarvis("Audio muted, sir." if ok else "I could not control the volume, sir.")
        return True
    if "volume max" in cmd or "volume 100" in cmd:
        ok = set_volume(1.0)
        speak_jarvis("Volume set to maximum, sir." if ok else "I could not control the volume, sir.")
        return True
    if "volume medium" in cmd or "volume 50" in cmd or "volume fifty" in cmd:
        ok = set_volume(0.5)
        speak_jarvis("Volume set to fifty percent, sir." if ok else "I could not control the volume, sir.")
        return True

    # Weather
    if "weather" in cmd:
        info = get_weather("Athens")
        speak_jarvis(f"The current weather is {info}, sir.")
        ui_queue.put(("WEATHER", f"ATHENS\n{info}"))
        return True

    # Battery
    if "battery" in cmd or "power level" in cmd or "power status" in cmd:
        speak_jarvis(f"Power status: {get_battery_status()}, sir.")
        return True

    # Wikipedia
    if "tell me about" in cmd or "wikipedia" in cmd:
        topic = cmd.split("about", 1)[-1].strip() if "about" in cmd else cmd.replace("wikipedia", "").strip()
        if not topic:
            speak_jarvis("About what, sir?")
            return True
        speak_jarvis(wiki_summary(topic))
        return True

    # IP
    if "ip address" in cmd or "my ip" in cmd:
        speak_jarvis(f"Your public IP address is {get_public_ip()}, sir.")
        return True

    # Screenshot
    if "screenshot" in cmd or "capture the screen" in cmd or "take a screenshot" in cmd:
        filename = take_screenshot()
        if filename:
            speak_jarvis(f"Screenshot saved as {filename}, sir.")
            ui_queue.put(("LOG", f"Saved: {filename}"))
        else:
            speak_jarvis("I could not capture the screen, sir.")
        return True

    # Switch window
    if "switch window" in cmd or "alt tab" in cmd or "switch the window" in cmd:
        speak_jarvis("Switching windows, sir.")
        switch_window()
        return True

    # Calculator
    if "calculate" in cmd or "what is" in cmd and any(c.isdigit() for c in cmd):
        expr = cmd.replace("calculate", "").replace("what is", "")
        result = safe_calculate(expr)
        if result is not None:
            speak_jarvis(f"That comes to {result}, sir.")
        else:
            speak_jarvis("I could not parse that calculation, sir.")
        return True

    # Location
    if cmd.startswith("where is") or "where is" in cmd:
        place = cmd.split("where is", 1)[-1].strip()
        if not place:
            speak_jarvis("Where is what, sir?")
            return True
        geo = geocode_place(place)
        here = get_current_location()
        if geo and here:
            lat, lon, name = geo
            hlat, hlon, hcity = here
            dist = haversine_km(hlat, hlon, lat, lon)
            speak_jarvis(f"{place} is roughly {dist:.0f} kilometers from {hcity}, sir.")
        else:
            speak_jarvis(f"I could not locate {place}, sir.")
        return True

    # News
    if "news" in cmd or "headlines" in cmd:
        headlines = fetch_news(5)
        if headlines:
            speak_jarvis("Here are today's top headlines, sir.")
            for title in headlines:
                speak_jarvis(title)
                ui_queue.put(("LOG", f"NEWS: {title}"))
        else:
            speak_jarvis("I could not reach the news feed right now, sir.")
        return True

    # Notes
    if "make a note" in cmd or "remember this" in cmd or "write this down" in cmd or "take a note" in cmd:
        speak_jarvis("What would you like me to note down, sir?")
        note_text = listen_once(timeout=6, phrase_limit=10)
        if note_text:
            add_note(note_text)
            speak_jarvis("Noted, sir.")
            ui_queue.put(("LOG", f"NOTE SAVED: {note_text}"))
        else:
            speak_jarvis("I did not catch that, sir.")
        return True

    if "read my notes" in cmd or "read notes" in cmd or "show notes" in cmd:
        notes = read_notes(3)
        if notes:
            speak_jarvis("Here are your most recent notes, sir.")
            for n in notes:
                speak_jarvis(n)
        else:
            speak_jarvis("You do not have any notes yet, sir.")
        return True

    # Jokes
    if "joke" in cmd:
        jokes = [
            "Why do programmers prefer dark mode? Because light attracts bugs, sir.",
            "I would tell you a UDP joke, but you might not get it, sir.",
            "There are only 10 types of people, sir — those who understand binary and those who do not.",
            "Why did the AI go to therapy? It had too many deep learning issues, sir.",
        ]
        speak_jarvis(random.choice(jokes))
        return True

    # Time
    if "what time" in cmd or "current time" in cmd:
        speak_jarvis(f"The time is {time.strftime('%H:%M')}, sir.")
        return True

    # Date
    if "what date" in cmd or "what day" in cmd:
        speak_jarvis(f"Today is {time.strftime('%A, %d %B %Y')}, sir.")
        return True

    return False


# ==========================================
# VOICE
# ==========================================
async def _generate_speech(text: str):
    communicate = edge_tts.Communicate(text, "en-GB-RyanNeural", rate="-10%", pitch="-6Hz")
    await communicate.save("jarvis_voice.mp3")


def speak_jarvis(text: str):
    if not text:
        return
    ui_queue.put(("STATUS", f"JARVIS: {text}"))
    ui_queue.put(("LOG", f"JARVIS: {text}"))
    ui_queue.put(("STATE", "speaking"))

    try:
        asyncio.run(_generate_speech(text))
        if not pygame.mixer.get_init():
            pygame.mixer.init()
        pygame.mixer.music.load("jarvis_voice.mp3")
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            time.sleep(0.05)
    except Exception as e:
        print(f"[TTS Error]: {e}")
        ui_queue.put(("LOG", f"TTS Error: {e}"))
    finally:
        try:
            if os.path.exists("jarvis_voice.mp3"):
                os.remove("jarvis_voice.mp3")
        except Exception:
            pass
        ui_queue.put(("STATE", "standby"))


def listen_once(timeout: int = 4, phrase_limit: int = 6) -> str | None:
    ui_queue.put(("STATE", "listening"))
    ui_queue.put(("STATUS", "LISTENING..."))
    recognizer = sr.Recognizer()
    try:
        with sr.Microphone() as source:
            recognizer.adjust_for_ambient_noise(source, duration=0.25)
            audio = recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase_limit)
            ui_queue.put(("STATE", "processing"))
            ui_queue.put(("STATUS", "PROCESSING..."))
            text = recognizer.recognize_google(audio, language="en-US")
            return text
    except sr.WaitTimeoutError:
        ui_queue.put(("LOG", "Listening timed out."))
        return None
    except sr.UnknownValueError:
        ui_queue.put(("LOG", "Could not understand audio."))
        return None
    except Exception as e:
        ui_queue.put(("LOG", f"Mic error: {e}"))
        return None
    finally:
        ui_queue.put(("STATE", "standby"))


def process_command(command_text: str):
    if not command_text or not command_text.strip():
        return

    ui_queue.put(("USER", f"You: {command_text}"))
    ui_queue.put(("LOG", f"You: {command_text}"))
    cmd = command_text.lower().strip()

    if any(w in cmd for w in ("exit", "quit", "shutdown", "goodbye", "shut down")):
        speak_jarvis("Shutting down systems. Have a good day, sir.")
        ui_queue.put(("QUIT", None))
        return

    ui_queue.put(("STATE", "processing"))

    if execute_system_command(command_text):
        return

    # Gemini fallback
    if client is None:
        speak_jarvis("Gemini is not available, sir. Please check the API key.")
        return

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=command_text,
            config={
                "system_instruction": (
                    "You are JARVIS, Tony Stark's loyal AI assistant. "
                    "Speak in a polite, calm, slightly monotone British gentleman voice. "
                    "Be helpful, concise and witty. Keep answers to 1-2 short sentences. "
                    "Always address the user as sir."
                )
            },
        )
        if response and getattr(response, "text", None):
            speak_jarvis(response.text.strip())
        else:
            speak_jarvis("I have nothing useful to add, sir.")
    except Exception as e:
        print(f"[Gemini Error]: {e}")
        traceback.print_exc()
        ui_queue.put(("STATE", "error"))
        speak_jarvis("I encountered a temporary glitch with the language model, sir.")


# ==========================================
# CONTINUOUS WAKE-WORD LOOP
# ==========================================
def jarvis_loop():
    time.sleep(1.5)  # let UI finish loading
    speak_jarvis("Systems online. Say Jarvis to activate, or type a command below.")
    ui_queue.put(("STATUS", "STANDBY — Say 'Jarvis' or type a command"))
    ui_queue.put(("STATE", "standby"))

    recognizer = sr.Recognizer()

    while True:
        try:
            with sr.Microphone() as source:
                recognizer.adjust_for_ambient_noise(source, duration=0.2)
                try:
                    audio = recognizer.listen(source, timeout=3, phrase_time_limit=4)
                    text = recognizer.recognize_google(audio, language="en-US")
                except (sr.WaitTimeoutError, sr.UnknownValueError):
                    continue
                except Exception:
                    time.sleep(0.3)
                    continue

            if text and "jarvis" in text.lower():
                speak_jarvis("At your service, sir.")
                user_command = listen_once(timeout=5, phrase_limit=8)
                if user_command:
                    process_command(user_command)
                ui_queue.put(("STATUS", "STANDBY — Say 'Jarvis' or type a command"))
                ui_queue.put(("STATE", "standby"))

        except Exception as e:
            print(f"[Wake loop]: {e}")
            time.sleep(1)


# ==========================================
# HUD — denser, closer to movie references
# ==========================================
class AdvancedJarvisHUD(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("J.A.R.V.I.S.  //  MARK VII  //  STARK INDUSTRIES")
        self.geometry("1450x860")
        self.configure(fg_color="#01040a")
        ctk.set_appearance_mode("dark")

        self.state_name = "standby"
        self.state_color = STATE_COLORS["standby"]
        self.reactor_angle = 0.0
        self.pulse_t = 0.0
        self.mic_bars = [3] * 14
        self.log_lines = []
        self.news_index = 0
        self.net_prev = psutil.net_io_counters()

        self._build_ui()
        self.after(40, self._animate)
        self.after(1000, self._update_telemetry)
        self.after(4000, self._rotate_news)
        self.after(40, self._process_ui_queue)

        # Load weather
        threading.Thread(target=self._load_weather, daemon=True).start()

    def _build_ui(self):
        # ===== TOP BAR =====
        top = ctk.CTkFrame(self, fg_color="#030b16", border_color="#00e5ff", border_width=1, height=52)
        top.pack(fill="x", padx=10, pady=(10, 4))
        top.pack_propagate(False)

        ctk.CTkLabel(top, text="STARK INDUSTRIES", font=("Consolas", 11, "bold"),
                     text_color="#007a99").pack(side="left", padx=(16, 6), pady=12)
        ctk.CTkLabel(top, text="//  J.A.R.V.I.S. MARK VII HUD", font=("Consolas", 16, "bold"),
                     text_color="#00e5ff").pack(side="left", padx=4)

        self.state_pill = ctk.CTkLabel(top, text="● STANDBY", font=("Consolas", 12, "bold"),
                                        text_color=STATE_COLORS["standby"])
        self.state_pill.pack(side="right", padx=16)

        self.date_label = ctk.CTkLabel(top, text="", font=("Consolas", 11), text_color="#5ba8c4")
        self.date_label.pack(side="right", padx=10)
        self.time_label = ctk.CTkLabel(top, text="00:00:00", font=("Consolas", 15, "bold"),
                                        text_color="#00d2ff")
        self.time_label.pack(side="right", padx=10)

        # ===== MAIN BODY =====
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=10, pady=4)

        # --- LEFT COLUMN ---
        left = ctk.CTkFrame(body, fg_color="#030b16", border_color="#00e5ff", border_width=1, width=290)
        left.pack(side="left", fill="y", padx=(0, 6))
        left.pack_propagate(False)

        self._section(left, "SYSTEM TELEMETRY")
        self.gauge_canvas = tk.Canvas(left, width=260, height=255, bg="#030b16", highlightthickness=0)
        self.gauge_canvas.pack(pady=4)

        self._section(left, "ENVIRONMENT")
        self.weather_label = ctk.CTkLabel(left, text="Loading weather...", font=("Consolas", 12),
                                           text_color="#7fd8ff", wraplength=250, justify="left")
        self.weather_label.pack(pady=4, padx=10)

        self._section(left, "AUDIO INPUT")
        self.mic_canvas = tk.Canvas(left, width=250, height=50, bg="#030b16", highlightthickness=0)
        self.mic_canvas.pack(pady=4)

        # Quick protocol buttons (LEFT)
        self._section(left, "QUICK PROTOCOLS")
        btn_frame = ctk.CTkFrame(left, fg_color="transparent")
        btn_frame.pack(fill="x", padx=8, pady=4)

        btn_cfg = dict(fg_color="#061525", hover_color="#0c2a45", border_color="#00e5ff",
                       border_width=1, text_color="#7fd8ff", font=("Consolas", 10, "bold"),
                       height=30, corner_radius=4)

        row1 = ctk.CTkFrame(btn_frame, fg_color="transparent")
        row1.pack(fill="x", pady=2)
        ctk.CTkButton(row1, text="LOCK", width=80, command=self._btn_lock, **btn_cfg).pack(side="left", padx=2)
        ctk.CTkButton(row1, text="VOL 50%", width=80, command=self._btn_vol, **btn_cfg).pack(side="left", padx=2)
        ctk.CTkButton(row1, text="BATTERY", width=80, command=self._btn_batt, **btn_cfg).pack(side="left", padx=2)

        row2 = ctk.CTkFrame(btn_frame, fg_color="transparent")
        row2.pack(fill="x", pady=2)
        ctk.CTkButton(row2, text="NEWS", width=80, command=self._btn_news, **btn_cfg).pack(side="left", padx=2)
        ctk.CTkButton(row2, text="WEATHER", width=80, command=self._btn_weather, **btn_cfg).pack(side="left", padx=2)
        ctk.CTkButton(row2, text="SCREEN", width=80, command=self._btn_screen, **btn_cfg).pack(side="left", padx=2)

        # --- CENTER ---
        center = ctk.CTkFrame(body, fg_color="#030b16", border_color="#00e5ff", border_width=1)
        center.pack(side="left", fill="both", expand=True, padx=3)

        self.reactor_canvas = tk.Canvas(center, width=280, height=280, bg="#030b16", highlightthickness=0)
        self.reactor_canvas.pack(pady=(12, 2))
        self._draw_static_reactor()

        self.status_label = ctk.CTkLabel(center, text="INITIALIZING SYSTEMS...",
                                          font=("Consolas", 13, "bold"), text_color="#00e5ff",
                                          wraplength=520)
        self.status_label.pack(pady=2)

        self.user_label = ctk.CTkLabel(center, text="", font=("Consolas", 12, "italic"),
                                        text_color="#cceeff", wraplength=520)
        self.user_label.pack(pady=1)

        self._section(center, "SYSTEM LOG")
        self.console = ctk.CTkTextbox(center, fg_color="#01060e", text_color="#66e0ff",
                                       font=("Consolas", 11), border_color="#00aacc",
                                       border_width=1, height=150)
        self.console.pack(fill="both", expand=True, padx=14, pady=(0, 8))
        self.console.configure(state="disabled")

        # --- RIGHT ---
        right = ctk.CTkFrame(body, fg_color="#030b16", border_color="#00e5ff", border_width=1, width=300)
        right.pack(side="right", fill="y", padx=(6, 0))
        right.pack_propagate(False)

        self._section(right, "MARK VII  //  SUIT STATUS")
        self.suit_canvas = tk.Canvas(right, width=270, height=290, bg="#030b16", highlightthickness=0)
        self.suit_canvas.pack(pady=4)

        self.armor_label = ctk.CTkLabel(right, text="ARMOR INTEGRITY  98%",
                                         font=("Consolas", 12, "bold"), text_color="#00e5ff")
        self.armor_label.pack(pady=4)

        self._section(right, "NETWORK FEED")
        self.news_label = ctk.CTkLabel(right, text=NEWS_FEED[0], font=("Consolas", 11),
                                        text_color="#7fd8ff", wraplength=260, justify="left")
        self.news_label.pack(pady=6, padx=10)

        # ===== BOTTOM COMMAND BAR =====
        bottom = ctk.CTkFrame(self, fg_color="#030b16", border_color="#00e5ff", border_width=1, height=56)
        bottom.pack(fill="x", padx=10, pady=(4, 10))
        bottom.pack_propagate(False)

        self.cmd_entry = ctk.CTkEntry(
            bottom, placeholder_text="Type command and press Enter  |  or say 'Jarvis' then your command...",
            fg_color="#01060e", text_color="#00e5ff", border_color="#00e5ff",
            font=("Consolas", 13), height=34
        )
        self.cmd_entry.pack(side="left", fill="x", expand=True, padx=(10, 6), pady=10)
        self.cmd_entry.bind("<Return>", self._on_text)

        send_cfg = dict(fg_color="#061525", hover_color="#00c8ff", border_color="#00e5ff",
                        border_width=1, text_color="#7fd8ff", font=("Consolas", 11, "bold"),
                        height=34, corner_radius=4)

        ctk.CTkButton(bottom, text="SEND", width=70, command=self._on_text, **send_cfg).pack(side="left", padx=3, pady=10)
        ctk.CTkButton(bottom, text="🎤  TALK", width=90, command=self._on_ptt,
                      fg_color="#0a2a1a", hover_color="#39ff14", border_color="#39ff14",
                      border_width=1, text_color="#aaffcc", font=("Consolas", 11, "bold"),
                      height=34).pack(side="left", padx=6, pady=10)

    def _section(self, parent, title):
        ctk.CTkLabel(parent, text=f"[ {title} ]", font=("Consolas", 11, "bold"),
                     text_color="#00e5ff").pack(pady=(10, 2))

    # ---------- Buttons ----------
    def _btn_lock(self):
        self.log(">> SECURITY LOCK ENGAGED")
        threading.Thread(target=lock_workstation, daemon=True).start()

    def _btn_vol(self):
        self.log(">> VOLUME → 50%")
        threading.Thread(target=lambda: (set_volume(0.5), speak_jarvis("Volume set to fifty percent, sir.")), daemon=True).start()

    def _btn_batt(self):
        status = get_battery_status()
        self.log(f">> POWER: {status}")
        threading.Thread(target=lambda: speak_jarvis(f"Power status: {status}, sir."), daemon=True).start()

    def _btn_news(self):
        self.log(">> FETCHING HEADLINES...")
        def _f():
            headlines = fetch_news(4)
            if headlines:
                for h in headlines:
                    ui_queue.put(("LOG", f"NEWS: {h}"))
                speak_jarvis("Headlines retrieved, sir.")
            else:
                ui_queue.put(("LOG", "News feed unavailable."))
                speak_jarvis("I could not reach the news feed, sir.")
        threading.Thread(target=_f, daemon=True).start()

    def _btn_weather(self):
        def _w():
            w = get_weather("Athens")
            ui_queue.put(("WEATHER", f"ATHENS\n{w}"))
            ui_queue.put(("LOG", f"Weather: {w}"))
            speak_jarvis(f"Current weather is {w}, sir.")
        threading.Thread(target=_w, daemon=True).start()

    def _btn_screen(self):
        def _s():
            fn = take_screenshot()
            if fn:
                ui_queue.put(("LOG", f"Screenshot saved: {fn}"))
                speak_jarvis(f"Screenshot saved as {fn}, sir.")
            else:
                ui_queue.put(("LOG", "Screenshot failed (pyautogui missing?)."))
                speak_jarvis("Screenshot failed, sir.")
        threading.Thread(target=_s, daemon=True).start()

    def _on_text(self, event=None):
        text = self.cmd_entry.get().strip()
        if not text:
            return
        self.cmd_entry.delete(0, "end")
        self.log(f"TEXT CMD → {text}")
        threading.Thread(target=process_command, args=(text,), daemon=True).start()

    def _on_ptt(self):
        def _listen():
            self.log(">> PUSH-TO-TALK ACTIVE")
            text = listen_once()
            if text:
                process_command(text)
            else:
                ui_queue.put(("LOG", "No speech detected."))
                ui_queue.put(("STATE", "standby"))
        threading.Thread(target=_listen, daemon=True).start()

    def _load_weather(self):
        w = get_weather("Athens")
        ui_queue.put(("WEATHER", f"ATHENS, GREECE\n{w}"))

    # ---------- Drawing ----------
    def _draw_static_reactor(self):
        c = self.reactor_canvas
        c.create_oval(6, 6, 274, 274, outline="#012230", width=1)
        c.create_oval(22, 22, 258, 258, outline="#003a4f", width=1, dash=(3, 5))
        c.create_oval(48, 48, 232, 232, outline="#012230", width=1)
        cx = cy = 140
        for i in range(48):
            ang = math.radians(i * 7.5)
            x0 = cx + 130 * math.cos(ang)
            y0 = cy + 130 * math.sin(ang)
            x1 = cx + 120 * math.cos(ang)
            y1 = cy + 120 * math.sin(ang)
            c.create_line(x0, y0, x1, y1, fill="#012230")

    def _draw_gauge(self, cx, cy, r, pct, color, label, value, tag, sub=None):
        self.gauge_canvas.delete(tag)
        pct = max(0.0, min(100.0, pct))
        self.gauge_canvas.create_arc(cx-r, cy-r, cx+r, cy+r, start=225, extent=-270,
                                      style="arc", outline="#0a2030", width=9, tags=tag)
        self.gauge_canvas.create_arc(cx-r, cy-r, cx+r, cy+r, start=225, extent=-270*(pct/100),
                                      style="arc", outline=color, width=9, tags=tag)
        fs = 12 if len(value) <= 5 else 10
        self.gauge_canvas.create_text(cx, cy - (7 if sub else 3), text=value,
                                       fill=color, font=("Consolas", fs, "bold"), tags=tag)
        if sub:
            self.gauge_canvas.create_text(cx, cy + 8, text=sub, fill=color,
                                           font=("Consolas", 8), tags=tag)
        self.gauge_canvas.create_text(cx, cy + 22, text=label, fill="#4a7a90",
                                       font=("Consolas", 9), tags=tag)

    def _draw_suit(self, color):
        c = self.suit_canvas
        c.delete("suit")
        cx = 135
        # head
        c.create_oval(cx-30, 10, cx+30, 72, outline=color, width=2, tags="suit")
        c.create_line(cx-13, 38, cx-4, 38, fill=color, width=3, tags="suit")
        c.create_line(cx+4, 38, cx+13, 38, fill=color, width=3, tags="suit")
        # body
        c.create_line(cx, 72, cx, 95, fill=color, width=2, tags="suit")
        c.create_line(cx, 95, cx-85, 130, fill=color, width=2, tags="suit")
        c.create_line(cx, 95, cx+85, 130, fill=color, width=2, tags="suit")
        c.create_line(cx-85, 130, cx-65, 235, fill=color, width=2, tags="suit")
        c.create_line(cx+85, 130, cx+65, 235, fill=color, width=2, tags="suit")
        c.create_line(cx-65, 235, cx-28, 270, fill=color, width=2, tags="suit")
        c.create_line(cx+65, 235, cx+28, 270, fill=color, width=2, tags="suit")
        c.create_line(cx-28, 270, cx+28, 270, fill=color, width=2, tags="suit")
        # chest reactor
        pulse = 5 + 2.8 * math.sin(self.pulse_t)
        c.create_oval(cx-13-pulse, 138-pulse, cx+13+pulse, 164+pulse,
                      outline=color, width=1, tags="suit")
        c.create_oval(cx-10, 141, cx+10, 161, fill=color, outline="", tags="suit")
        c.create_text(cx, 282, text="SYSTEMS ONLINE", fill=color,
                      font=("Consolas", 10, "bold"), tags="suit")

    def _animate(self):
        color = self.state_color
        c = self.reactor_canvas
        c.delete("rot")
        c.delete("core")

        for i in range(10):
            start = self.reactor_angle + i * 36
            c.create_arc(42, 42, 238, 238, start=start, extent=18,
                         style="arc", outline=color, width=5, tags="rot")
        for i in range(16):
            start = -self.reactor_angle * 1.35 + i * 22.5
            c.create_arc(28, 28, 252, 252, start=start, extent=6,
                         style="arc", outline=color, width=2, tags="rot")

        pulse = 24 + 7 * math.sin(self.pulse_t)
        cx = cy = 140
        c.create_oval(cx-pulse-14, cy-pulse-14, cx+pulse+14, cy+pulse+14,
                      outline=color, width=1, tags="core")
        c.create_oval(cx-pulse, cy-pulse, cx+pulse, cy+pulse, fill=color, outline="", tags="core")
        # triangle core
        c.create_polygon(
            cx, cy - pulse*0.62,
            cx - pulse*0.52, cy + pulse*0.38,
            cx + pulse*0.52, cy + pulse*0.38,
            fill="#01040a", outline="", tags="core"
        )

        self.reactor_angle = (self.reactor_angle + 3.0) % 360
        self.pulse_t += 0.12

        # mic bars
        self.mic_canvas.delete("bars")
        active = self.state_name == "listening"
        w = 250 / len(self.mic_bars)
        for i, h in enumerate(self.mic_bars):
            target = random.randint(6, 42) if active else 3
            self.mic_bars[i] += (target - h) * 0.5
            hh = max(2, self.mic_bars[i])
            x0 = i * w + 2
            self.mic_canvas.create_rectangle(x0, 46-hh, x0+w-3, 46,
                                              fill=STATE_COLORS["listening"] if active else "#0a2030",
                                              outline="", tags="bars")

        self._draw_suit(color)
        self.after(42, self._animate)

    def _update_telemetry(self):
        now = time.localtime()
        self.time_label.configure(text=time.strftime("%H:%M:%S", now))
        self.date_label.configure(text=time.strftime("%d/%m/%Y  %A", now))

        cpu = psutil.cpu_percent()
        ram = psutil.virtual_memory().percent
        net_now = psutil.net_io_counters()
        delta = (net_now.bytes_sent + net_now.bytes_recv) - (self.net_prev.bytes_sent + self.net_prev.bytes_recv)
        self.net_prev = net_now
        kbps = max(0, delta / 1024)
        net_pct = min(100, kbps / 6)

        self._draw_gauge(62, 62, 50, cpu, "#00e5ff", "CPU", f"{cpu:.0f}%", "g1")
        self._draw_gauge(190, 62, 50, ram, "#ffb400" if ram > 85 else "#00e5ff", "RAM", f"{ram:.0f}%", "g2")
        self._draw_gauge(62, 180, 50, net_pct, "#39ff14", "NET", f"{kbps:.0f}", "g3", sub="KB/s")

        bpct, bsub = 100, None
        try:
            b = psutil.sensors_battery()
            if b:
                bpct = b.percent
                bsub = "CHG" if b.power_plugged else "BATT"
        except Exception:
            pass
        self._draw_gauge(190, 180, 50, bpct, "#00e5ff", "PWR", f"{bpct:.0f}%", "g4", sub=bsub)

        self.after(1000, self._update_telemetry)

    def _rotate_news(self):
        self.news_index = (self.news_index + 1) % len(NEWS_FEED)
        self.news_label.configure(text=NEWS_FEED[self.news_index])
        self.after(4500, self._rotate_news)

    def _process_ui_queue(self):
        while not ui_queue.empty():
            try:
                msg, payload = ui_queue.get_nowait()
            except queue.Empty:
                break
            if msg == "LOG":
                self.log(payload)
            elif msg == "STATUS":
                self.status_label.configure(text=payload)
            elif msg == "USER":
                self.user_label.configure(text=payload)
            elif msg == "STATE":
                self.set_state(payload)
            elif msg == "WEATHER":
                self.weather_label.configure(text=payload)
            elif msg == "QUIT":
                self.destroy()
                return
        self.after(40, self._process_ui_queue)

    def set_state(self, name: str):
        if name not in STATE_COLORS:
            name = "standby"
        self.state_name = name
        self.state_color = STATE_COLORS[name]
        self.state_pill.configure(text=f"● {name.upper()}", text_color=self.state_color)

    def log(self, text: str):
        ts = time.strftime("%H:%M:%S")
        self.log_lines.append(f"[{ts}] {text}")
        self.log_lines = self.log_lines[-200:]
        self.console.configure(state="normal")
        self.console.delete("1.0", "end")
        self.console.insert("end", "\n".join(self.log_lines))
        self.console.see("end")
        self.console.configure(state="disabled")


# ==========================================
# MAIN
# ==========================================
if __name__ == "__main__":
    print("=" * 50)
    print("  J.A.R.V.I.S. MARK VII starting...")
    print("=" * 50)
    if not HAS_PYCAW:
        print("[!] pycaw not found → volume control disabled")
    if not HAS_PYAUTOGUI:
        print("[!] pyautogui not found → screenshot/alt-tab disabled")
    print("Tip: Type commands in the bottom bar even if mic fails.")
    print()

    app = AdvancedJarvisHUD()

    # Start continuous wake-word listener
    threading.Thread(target=jarvis_loop, daemon=True).start()

    app.mainloop()
