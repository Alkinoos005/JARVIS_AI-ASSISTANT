"""
J.A.R.V.I.S. MARK VII — Full functional rebuild
==============================================
- Continuous wake-word ("Jarvis") + Push-to-Talk + Text input
- Dense cinematic HUD closer to the movie reference images
- All system commands working with visible feedback
- Real clickable buttons
- Local SearXNG web search
- Adaptive context panel: the screen changes to show what JARVIS is doing
  (weather report / headlines / search results), then reverts to standby —
  the "screen adapts like the movie" behavior.
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
import uuid
from collections import deque
from typing import Optional

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

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False

# The PyPI package was renamed from `duckduckgo_search` to `ddgs` in 2025.
try:
    from ddgs import DDGS
    HAS_DDGS = True
except ImportError:
    try:
        from duckduckgo_search import DDGS
        HAS_DDGS = True
    except ImportError:
        HAS_DDGS = False

# Coqui XTTS for real voice cloning from your jarvis_voice sample
HAS_XTTS = False
xtts_model = None
try:
    from TTS.api import TTS as CoquiTTS
    HAS_XTTS = True
except ImportError:
    pass

# sounddevice = reliable continuous audio for clap detection
try:
    import sounddevice as sd
    import numpy as np
    HAS_SOUNDDEVICE = True
except ImportError:
    HAS_SOUNDDEVICE = False

# Path to your voice sample (put the mp3 next to this script)
VOICE_SAMPLE_CANDIDATES = [
    "jarvis_voice_sample.mp3",
    "jarvis_voice.mp3",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "jarvis_voice_sample.mp3"),
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "jarvis_voice.mp3"),
]
VOICE_SAMPLE = next((p for p in VOICE_SAMPLE_CANDIDATES if os.path.exists(p)), None)

# Shared flag: clap detector sets this, jarvis_loop reacts
clap_event = threading.Event()

# ==========================================
# CONFIG
# ==========================================
# Prefer environment variable. Fallback to the key you used before so it works out of the box.
GEMINI_KEY = os.environ.get("GEMINI_API_KEY") or " "

try:
    client = genai.Client(api_key=GEMINI_KEY)
except Exception as e:
    print(f"[Gemini init error]: {e}")
    client = None

# Your local SearXNG instance.
# No settings.yml access needed anymore — search_web() below scrapes the normal
# HTML results page instead of requiring the JSON API, and falls back to
# DuckDuckGo (via the `ddgs` package) if SearXNG doesn't return anything.
SEARXNG_URL = os.environ.get("SEARXNG_URL", "http://localhost:8080")

STATE_COLORS = {
    "standby":    "#00e5ff",
    "listening":  "#39ff14",
    "processing": "#ffb400",
    "speaking":   "#00c8ff",
    "error":      "#ff3b3b",
}

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


def search_searxng_html(query: str, limit: int = 5):
    """Scrape SearXNG's normal HTML results page (no JSON API / settings.yml access needed).
    SearXNG's markup varies a bit by theme/version, so this tries a couple of
    selector patterns before giving up."""
    if not HAS_BS4:
        print("[SearXNG-HTML] BeautifulSoup not installed — run: pip install beautifulsoup4")
        return []
    try:
        r = requests.get(
            f"{SEARXNG_URL.rstrip('/')}/search",
            params={"q": query},
            headers={"User-Agent": "Mozilla/5.0 (JarvisAssistant)"},
            timeout=8,
        )
        if r.status_code != 200:
            print(f"[SearXNG-HTML] HTTP {r.status_code}")
            return []

        soup = BeautifulSoup(r.text, "html.parser")
        results = []

        # Standard SearXNG theme: each result is an <article class="result ...">
        articles = soup.select("article.result") or soup.select("div.result")
        for art in articles[:limit]:
            title_tag = art.select_one("h3 a") or art.find("a")
            if not title_tag:
                continue
            title = title_tag.get_text(strip=True) or "(untitled)"
            url = title_tag.get("href", "")
            content_tag = art.select_one("p.content") or art.select_one(".content") or art.find("p")
            content = content_tag.get_text(strip=True) if content_tag else ""
            if url:
                results.append({"title": title, "url": url, "content": content})

        return results[:limit]
    except requests.exceptions.ConnectionError:
        print(f"[SearXNG-HTML] Could not connect to {SEARXNG_URL} — is SearXNG running?")
        return []
    except Exception as e:
        print(f"[SearXNG-HTML Error]: {e}")
        return []


def search_ddgs(query: str, limit: int = 5):
    """DuckDuckGo search via the `ddgs` package — no local service required at all."""
    if not HAS_DDGS:
        print("[DDGS] Not installed — run: pip install ddgs")
        return []
    try:
        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=limit):
                results.append({
                    "title": r.get("title", "") or "(untitled)",
                    "url": r.get("href", "") or r.get("url", ""),
                    "content": (r.get("body", "") or "").strip(),
                })
        return results
    except Exception as e:
        print(f"[DDGS Error]: {e}")
        return []


def search_web(query: str, limit: int = 5):
    """Try local SearXNG first (fast, private), fall back to DuckDuckGo if that
    comes back empty or SearXNG isn't reachable. Returns (results, source_name)."""
    results = search_searxng_html(query, limit)
    if results:
        return results, "SearXNG"
    results = search_ddgs(query, limit)
    if results:
        return results, "DuckDuckGo"
    return [], None


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

    # Weather — also pushes to the adaptive context screen
    if "weather" in cmd:
        info = get_weather("Athens")
        speak_jarvis(f"The current weather is {info}, sir.")
        ui_queue.put(("WEATHER", f"ATHENS\n{info}"))
        ui_queue.put(("SCREEN", ("WEATHER REPORT", [f"ATHENS, GREECE", info, "", f"Updated {time.strftime('%H:%M:%S')}"])))
        return True

    # Battery
    if "battery" in cmd or "power level" in cmd or "power status" in cmd:
        speak_jarvis(f"Power status: {get_battery_status()}, sir.")
        return True

    # Web search — tries local SearXNG (HTML scrape, no API access needed),
    # falls back to DuckDuckGo (ddgs) automatically. Also drives the adaptive
    # context screen.
    if cmd.startswith("search for") or cmd.startswith("search "):
        query = cmd.replace("search for", "").replace("search", "", 1).strip()
        if not query:
            speak_jarvis("What would you like me to search for, sir?")
            return True
        speak_jarvis(f"Searching for {query}, sir.")
        results, source = search_web(query)
        if results:
            top = results[0]
            snippet = top["content"][:160] if top["content"] else "No description available."
            speak_jarvis(f"Top result from {source}: {top['title']}. {snippet}")
            lines = []
            for i, r in enumerate(results, 1):
                lines.append(f"{i}. {r['title']}")
                lines.append(f"   {r['url']}")
            ui_queue.put(("SCREEN", (f"SEARCH ({source}): {query}", lines)))
            ui_queue.put(("LOG", f"{source} '{query}' → {len(results)} results"))
        else:
            speak_jarvis("I couldn't get any results, sir. Both SearXNG and DuckDuckGo "
                         "search failed — check SearXNG is running, or that ddgs is installed.")
            ui_queue.put(("SCREEN", ("SEARCH FAILED", [
                f"Query: {query}",
                f"SearXNG at {SEARXNG_URL} — unreachable or no results",
                "DuckDuckGo (ddgs) — unreachable or not installed",
            ])))
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
    if "calculate" in cmd or ("what is" in cmd and any(c.isdigit() for c in cmd)):
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

    # News — also drives the adaptive context screen
    if "news" in cmd or "headlines" in cmd:
        headlines = fetch_news(5)
        if headlines:
            speak_jarvis("Here are today's top headlines, sir.")
            for title in headlines:
                speak_jarvis(title)
                ui_queue.put(("LOG", f"NEWS: {title}"))
            ui_queue.put(("SCREEN", ("TOP HEADLINES", headlines)))
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
            ui_queue.put(("SCREEN", ("RECENT NOTES", notes)))
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
# VOICE — XTTS clone of your sample + edge-tts fallback
# ==========================================
def _init_xtts():
    """Lazy-load the XTTS model once (first call downloads ~2GB if needed)."""
    global xtts_model
    if xtts_model is not None:
        return xtts_model
    if not HAS_XTTS or not VOICE_SAMPLE:
        return None
    try:
        print("[XTTS] Loading Coqui XTTS v2 model (first run may take a minute)...")
        # cpu=True works everywhere; set gpu=True if you have CUDA
        xtts_model = CoquiTTS(model_name="tts_models/multilingual/multi-dataset/xtts_v2", progress_bar=False)
        print(f"[XTTS] Ready — cloning from: {VOICE_SAMPLE}")
        return xtts_model
    except Exception as e:
        print(f"[XTTS] Failed to load model: {e}")
        return None


def _speak_with_xtts(text: str, out_path: str) -> bool:
    """Generate speech with Coqui XTTS using your voice sample. out_path should end in .wav."""
    model = _init_xtts()
    if model is None:
        return False
    try:
        model.tts_to_file(
            text=text,
            file_path=out_path,
            speaker_wav=VOICE_SAMPLE,
            language="en",
        )
        return os.path.exists(out_path)
    except Exception as e:
        print(f"[XTTS speak error]: {e}")
        return False


def speak_jarvis(text: str):
    if not text:
        return
    ui_queue.put(("STATUS", f"JARVIS: {text}"))
    ui_queue.put(("LOG", f"JARVIS: {text}"))
    ui_queue.put(("STATE", "speaking"))

    uid = uuid.uuid4().hex[:10]
    # Prefer wav when using XTTS (higher quality, no re-encode)
    use_xtts = HAS_XTTS and VOICE_SAMPLE is not None
    temp_filename = f"jarvis_voice_{uid}.wav" if use_xtts else f"jarvis_voice_{uid}.mp3"

    generated = False
    try:
        if use_xtts:
            generated = _speak_with_xtts(text, temp_filename)
            if generated:
                ui_queue.put(("LOG", "Voice: XTTS clone"))
            else:
                ui_queue.put(("LOG", "XTTS failed — falling back to edge-tts"))

        if not generated:
            # Fallback: Microsoft neural British voice
            temp_filename = f"jarvis_voice_{uid}.mp3"

            async def _generate_edge():
                communicate = edge_tts.Communicate(
                    text, "en-GB-RyanNeural", rate="-10%", pitch="-6Hz"
                )
                await communicate.save(temp_filename)

            asyncio.run(_generate_edge())
            generated = True
            ui_queue.put(("LOG", "Voice: edge-tts (en-GB-RyanNeural)"))

        if not generated or not os.path.exists(temp_filename):
            raise RuntimeError("No audio file produced")

        if not pygame.mixer.get_init():
            pygame.mixer.init()

        try:
            pygame.mixer.music.stop()
            pygame.mixer.music.unload()
        except Exception:
            pass

        pygame.mixer.music.load(temp_filename)
        pygame.mixer.music.play()

        while pygame.mixer.music.get_busy():
            time.sleep(0.05)

        pygame.mixer.music.stop()
        try:
            pygame.mixer.music.unload()
        except Exception:
            pass

    except Exception as e:
        print(f"[TTS Error]: {e}")
        ui_queue.put(("LOG", f"TTS Error: {e}"))
    finally:
        for ext in (".mp3", ".wav"):
            p = f"jarvis_voice_{uid}{ext}"
            if os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass
        ui_queue.put(("STATE", "standby"))


def listen_once(timeout: int = 6, phrase_limit: int = 12) -> Optional[str]:
    """Listen for a full command. Longer limits for natural conversation / coding help."""
    ui_queue.put(("STATE", "listening"))
    ui_queue.put(("STATUS", "LISTENING... Speak now"))
    recognizer = sr.Recognizer()
    recognizer.energy_threshold = 300
    recognizer.dynamic_energy_threshold = True
    try:
        with sr.Microphone() as source:
            recognizer.adjust_for_ambient_noise(source, duration=0.4)
            audio = recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase_limit)
            ui_queue.put(("STATE", "processing"))
            ui_queue.put(("STATUS", "PROCESSING..."))
            text = recognizer.recognize_google(audio, language="en-US")
            return text
    except sr.WaitTimeoutError:
        ui_queue.put(("LOG", "Listening timed out — try again or type the command."))
        return None
    except sr.UnknownValueError:
        ui_queue.put(("LOG", "Could not understand audio. Please repeat."))
        return None
    except OSError as e:
        ui_queue.put(("LOG", f"MIC ERROR: no working microphone found ({e})"))
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
                    "You are JARVIS, Tony Stark's loyal AI assistant from Iron Man. "
                    "Speak in a polite, calm, slightly monotone British gentleman voice. "
                    "Be helpful, precise and witty. Always address the user as sir. "
                    "For simple questions keep answers to 1-3 short sentences. "
                    "For coding, writing, explanations or technical help you may give longer, "
                    "clear, well-structured answers. Prefer practical, correct solutions."
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
# ==========================================
# DOUBLE-CLAP DETECTOR (sounddevice stream)
# ==========================================
class DoubleClapDetector:
    """
    Listens continuously on the mic. When two sharp volume peaks arrive
    0.15–0.55 s apart, sets clap_event so jarvis_loop can react.
    """

    def __init__(self, threshold_multiplier: float = 4.0, min_threshold: float = 0.08):
        self.threshold_multiplier = threshold_multiplier
        self.min_threshold = min_threshold
        self.threshold = 0.15  # will be calibrated
        self.last_peak_time = 0.0
        self.calibrated = False
        self._samples = []
        self._running = False

    def _calibrate(self, block):
        """Collect ~1.5 s of ambient noise and set threshold above it."""
        rms = float(np.sqrt(np.mean(block ** 2)))
        self._samples.append(rms)
        if len(self._samples) >= 30:  # ~1.5 s at blocksize 2048 / 16k
            ambient = float(np.mean(self._samples))
            self.threshold = max(self.min_threshold, ambient * self.threshold_multiplier)
            self.calibrated = True
            ui_queue.put(("LOG", f"Clap calibrated — ambient={ambient:.4f}  threshold={self.threshold:.4f}"))
            ui_queue.put(("LOG", "Double-clap ready. Clap twice to activate."))

    def _callback(self, indata, frames, time_info, status):
        if status:
            return
        block = indata[:, 0] if indata.ndim > 1 else indata
        block = block.astype(np.float32)

        if not self.calibrated:
            self._calibrate(block)
            return

        rms = float(np.sqrt(np.mean(block ** 2)))
        now = time.time()

        if rms >= self.threshold:
            # Debounce: ignore peaks closer than 80 ms (same clap ringing)
            if now - self.last_peak_time < 0.08:
                return
            gap = now - self.last_peak_time
            if 0.15 <= gap <= 0.55:
                # Valid double clap
                ui_queue.put(("LOG", f">> DOUBLE CLAP (RMS={rms:.3f})"))
                clap_event.set()
                self.last_peak_time = 0.0
            else:
                self.last_peak_time = now

    def start(self):
        if not HAS_SOUNDDEVICE:
            ui_queue.put(("LOG", "sounddevice not installed — clap detection disabled. pip install sounddevice"))
            return
        self._running = True

        def _run():
            try:
                with sd.InputStream(
                    samplerate=16000,
                    channels=1,
                    dtype="float32",
                    blocksize=2048,
                    callback=self._callback,
                ):
                    ui_queue.put(("LOG", "Clap detector stream started. Stay quiet 1.5s for calibration..."))
                    while self._running:
                        time.sleep(0.2)
            except Exception as e:
                ui_queue.put(("LOG", f"Clap detector error: {e}"))

        threading.Thread(target=_run, daemon=True).start()

    def stop(self):
        self._running = False


def jarvis_loop():
    """Wake on 'Jarvis' voice OR double-clap, then take a command."""
    time.sleep(1.5)

    try:
        mics = sr.Microphone.list_microphone_names()
        ui_queue.put(("LOG", f"Found {len(mics)} audio input device(s)."))
        if not mics:
            ui_queue.put(("LOG", "WARNING: no microphone detected — use text / push-to-talk."))
    except Exception as e:
        ui_queue.put(("LOG", f"WARNING: could not query microphones ({e})."))

    if not str(GEMINI_KEY).startswith("AIza"):
        ui_queue.put(("LOG", "WARNING: GEMINI_KEY doesn't look like a standard key (should start 'AIzaSy')."))

    # Start continuous clap detector in background
    detector = DoubleClapDetector(threshold_multiplier=3.5, min_threshold=0.06)
    detector.start()

    # Always greet
    speak_jarvis("Welcome home, sir.")
    ui_queue.put(("STATUS", "STANDBY — Say 'Jarvis' or double-clap"))
    ui_queue.put(("STATE", "standby"))

    recognizer = sr.Recognizer()

    def _handle_activation():
        speak_jarvis("At your service, sir.")
        user_command = listen_once(timeout=8, phrase_limit=15)
        if user_command:
            process_command(user_command)
        ui_queue.put(("STATUS", "STANDBY — Say 'Jarvis' or double-clap"))
        ui_queue.put(("STATE", "standby"))

    while True:
        # --- A) Double-clap path (set by sounddevice callback) ---
        if clap_event.is_set():
            clap_event.clear()
            _handle_activation()
            continue

        # --- B) Voice wake-word path ---
        try:
            with sr.Microphone(sample_rate=16000) as source:
                recognizer.adjust_for_ambient_noise(source, duration=0.2)
                try:
                    audio = recognizer.listen(source, timeout=1.5, phrase_time_limit=3)
                except sr.WaitTimeoutError:
                    continue
                except Exception:
                    time.sleep(0.15)
                    continue

            try:
                text = recognizer.recognize_google(audio, language="en-US")
            except (sr.UnknownValueError, sr.RequestError):
                continue
            except Exception:
                continue

            if text and "jarvis" in text.lower():
                _handle_activation()

        except OSError as e:
            ui_queue.put(("LOG", f"MIC ERROR: {e}. Use text / push-to-talk."))
            # Still allow clap events while mic is broken
            time.sleep(2)
        except Exception as e:
            print(f"[Wake loop]: {e}")
            time.sleep(0.5)


# ==========================================
# CINEMATIC HUD — dense Stark-style interface
# ==========================================
class AdvancedJarvisHUD(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("J.A.R.V.I.S.  //  MARK VII  //  STARK INDUSTRIES")
        self.geometry("1560x920")
        self.configure(fg_color="#000308")
        ctk.set_appearance_mode("dark")

        self.state_name = "standby"
        self.state_color = STATE_COLORS["standby"]
        self.reactor_angle = 0.0
        self.pulse_t = 0.0
        self.scan_y = 0
        self.mic_bars = [3] * 16
        self.log_lines = []
        self.news_index = 0
        self.net_prev = psutil.net_io_counters()
        self.up_history = deque([0] * 60, maxlen=60)
        self.down_history = deque([0] * 60, maxlen=60)
        self._context_revert_id = None

        self._build_ui()
        self.after(35, self._animate)
        self.after(1000, self._update_telemetry)
        self.after(35, self._process_ui_queue)
        threading.Thread(target=self._load_weather, daemon=True).start()

    # ---------------- UI BUILD ----------------
    def _build_ui(self):
        # ========== TOP STATUS STRIP (two rows: title row + JARVIS OS badge row) ==========
        top = ctk.CTkFrame(self, fg_color="#020a14", border_color="#00e5ff", border_width=1, height=64)
        top.pack(fill="x", padx=8, pady=(8, 3))
        top.pack_propagate(False)

        title_row = ctk.CTkFrame(top, fg_color="transparent")
        title_row.pack(fill="x", pady=(6, 0))

        ctk.CTkLabel(title_row, text="◈ STARK INDUSTRIES", font=("Consolas", 10, "bold"),
                     text_color="#006680").pack(side="left", padx=(14, 4))
        ctk.CTkLabel(title_row, text="//  J.A.R.V.I.S. MARK VII  //  HUD INTERFACE",
                     font=("Consolas", 15, "bold"), text_color="#00e5ff").pack(side="left", padx=2)

        self.state_pill = ctk.CTkLabel(title_row, text="● STANDBY", font=("Consolas", 11, "bold"),
                                        text_color=STATE_COLORS["standby"])
        self.state_pill.pack(side="right", padx=14)
        self.date_label = ctk.CTkLabel(title_row, text="", font=("Consolas", 10), text_color="#4a90a8")
        self.date_label.pack(side="right", padx=8)
        self.time_label = ctk.CTkLabel(title_row, text="00:00:00", font=("Consolas", 14, "bold"),
                                        text_color="#00d2ff")
        self.time_label.pack(side="right", padx=8)

        # --- JARVIS OS badge row ---
        badge_row = ctk.CTkFrame(top, fg_color="transparent")
        badge_row.pack(fill="x", pady=(2, 4))

        self.badge_canvas = tk.Canvas(badge_row, width=20, height=20, bg="#020a14", highlightthickness=0)
        self.badge_canvas.pack(side="left", padx=(14, 6))
        self.badge_canvas.create_oval(2, 2, 18, 18, outline="#00e5ff", width=2, tags="badge_ring")
        self.badge_canvas.create_oval(7, 7, 13, 13, fill="#00e5ff", outline="", tags="badge_dot")

        ctk.CTkLabel(badge_row, text="JARVIS OS  v1.2.5   //   USER: SIR   //   ACCESS: FULL",
                     font=("Consolas", 10), text_color="#3a8fb0").pack(side="left")

        # ========== MAIN 3-COLUMN BODY ==========
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=8, pady=2)

        # ---- LEFT PANEL ----
        left = ctk.CTkFrame(body, fg_color="#020a14", border_color="#00c8e0", border_width=1, width=300)
        left.pack(side="left", fill="y", padx=(0, 4))
        left.pack_propagate(False)

        self._tech_header(left, "SYSTEM TELEMETRY")
        self.gauge_canvas = tk.Canvas(left, width=280, height=240, bg="#020a14", highlightthickness=0)
        self.gauge_canvas.pack(pady=2)

        self._tech_header(left, "ENVIRONMENTAL")
        self.weather_label = ctk.CTkLabel(left, text="Scanning...", font=("Consolas", 11),
                                           text_color="#7fd8ff", wraplength=270, justify="left")
        self.weather_label.pack(pady=2, padx=8)

        self._tech_header(left, "AUDIO SPECTRUM")
        self.mic_canvas = tk.Canvas(left, width=270, height=46, bg="#020a14", highlightthickness=0)
        self.mic_canvas.pack(pady=2)

        self._tech_header(left, "QUICK PROTOCOLS")
        btn_frame = ctk.CTkFrame(left, fg_color="transparent")
        btn_frame.pack(fill="x", padx=6, pady=3)

        btn_cfg = dict(
            fg_color="#031018", hover_color="#0a2838", border_color="#00e5ff",
            border_width=1, text_color="#7fd8ff", font=("Consolas", 9, "bold"),
            height=28, corner_radius=3
        )
        for row_labels in [
            [("LOCK", self._btn_lock), ("VOL 50%", self._btn_vol), ("BATTERY", self._btn_batt)],
            [("NEWS", self._btn_news), ("WEATHER", self._btn_weather), ("SCREEN", self._btn_screen)],
        ]:
            rf = ctk.CTkFrame(btn_frame, fg_color="transparent")
            rf.pack(fill="x", pady=1)
            for lab, cmd in row_labels:
                ctk.CTkButton(rf, text=lab, width=88, command=cmd, **btn_cfg).pack(side="left", padx=2)

        # Search box (also reachable by typing "search for ..." at the bottom)
        self._tech_header(left, "WEB SEARCH  (SearXNG)")
        search_row = ctk.CTkFrame(left, fg_color="transparent")
        search_row.pack(fill="x", padx=8, pady=(0, 6))
        self.search_entry = ctk.CTkEntry(search_row, placeholder_text="query...", height=26,
                                          fg_color="#01060c", text_color="#00e5ff", border_color="#00aacc",
                                          font=("Consolas", 10))
        self.search_entry.pack(side="left", fill="x", expand=True)
        self.search_entry.bind("<Return>", self._on_search)
        ctk.CTkButton(search_row, text="GO", width=36, command=self._on_search, **btn_cfg).pack(side="left", padx=(4, 0))

        self._tech_header(left, "CORE STATUS")
        self.core_status = ctk.CTkLabel(
            left, text="REACTOR: NOMINAL\nUPLINK: SECURE\nAI CORE: ONLINE",
            font=("Consolas", 10), text_color="#5bc8e0", justify="left"
        )
        self.core_status.pack(pady=4, padx=10, anchor="w")

        # ---- CENTER PANEL ----
        center = ctk.CTkFrame(body, fg_color="#020a14", border_color="#00c8e0", border_width=1)
        center.pack(side="left", fill="both", expand=True, padx=3)

        self.reactor_canvas = tk.Canvas(center, width=320, height=320, bg="#020a14", highlightthickness=0)
        self.reactor_canvas.pack(pady=(8, 0))
        self._draw_static_reactor()

        ctk.CTkLabel(center, text="STARK INDUSTRIES  —  ARC REACTOR: ONLINE",
                     font=("Consolas", 9, "bold"), text_color="#3a8fb0").pack(pady=(2, 0))

        self.status_label = ctk.CTkLabel(
            center, text="SYSTEMS INITIALIZING...",
            font=("Consolas", 12, "bold"), text_color="#00e5ff", wraplength=560
        )
        self.status_label.pack(pady=(4, 0))

        self.user_label = ctk.CTkLabel(
            center, text="", font=("Consolas", 11, "italic"),
            text_color="#a8e6ff", wraplength=560
        )
        self.user_label.pack(pady=0)

        # ---- ADAPTIVE CONTEXT SCREEN ----
        # This is the part of the HUD that changes to show what JARVIS is
        # currently doing (weather / news / search results), then reverts
        # to standby — the "screen adapts to the task" behavior.
        ctx_header = ctk.CTkFrame(center, fg_color="transparent", height=22)
        ctx_header.pack(fill="x", padx=6, pady=(8, 1))
        ctx_header.pack_propagate(False)
        ctk.CTkLabel(ctx_header, text="◆ CONTEXT DISPLAY", font=("Consolas", 10, "bold"),
                     text_color="#00e5ff").pack(side="left")
        self.context_title = ctk.CTkLabel(ctx_header, text="STANDBY", font=("Consolas", 10, "bold"),
                                           text_color="#ffb400")
        self.context_title.pack(side="right")

        self.context_panel = ctk.CTkTextbox(
            center, fg_color="#01060c", text_color="#7fd8ff",
            font=("Consolas", 10), border_color="#0088aa", border_width=1, height=80
        )
        self.context_panel.pack(fill="x", padx=12, pady=(0, 4))
        self.context_panel.insert("end", "Awaiting instructions...")
        self.context_panel.configure(state="disabled")

        self._tech_header(center, "SYSTEM LOG")
        self.console = ctk.CTkTextbox(
            center, fg_color="#01060c", text_color="#5ce0ff",
            font=("Consolas", 10), border_color="#0088aa", border_width=1, height=100
        )
        self.console.pack(fill="both", expand=True, padx=12, pady=(0, 6))
        self.console.configure(state="disabled")

        # ---- RIGHT PANEL ----
        right = ctk.CTkFrame(body, fg_color="#020a14", border_color="#00c8e0", border_width=1, width=310)
        right.pack(side="right", fill="y", padx=(4, 0))
        right.pack_propagate(False)

        self._tech_header(right, "UPLINK TRAFFIC")
        self.up_canvas = tk.Canvas(right, width=280, height=70, bg="#020a14", highlightthickness=0)
        self.up_canvas.pack(pady=2)

        self._tech_header(right, "DOWNLINK TRAFFIC")
        self.down_canvas = tk.Canvas(right, width=280, height=70, bg="#020a14", highlightthickness=0)
        self.down_canvas.pack(pady=2)

        self.armor_label = ctk.CTkLabel(
            right, text="LINK INTEGRITY  ▓▓▓▓▓▓▓▓▓░  96%",
            font=("Consolas", 11, "bold"), text_color="#00e5ff"
        )
        self.armor_label.pack(pady=6)

        self._tech_header(right, "NETWORK FEED")
        self.news_label = ctk.CTkLabel(
            right, text="Awaiting headlines — say 'news' or press NEWS", font=("Consolas", 10),
            text_color="#7fd8ff", wraplength=280, justify="left"
        )
        self.news_label.pack(pady=4, padx=8)

        self._tech_header(right, "DIAGNOSTICS")
        self.diag_label = ctk.CTkLabel(
            right,
            text="REPULSOR  ··· OK\nFLIGHT SYS ··· OK\nTARGETING ··· OK\nAI LINK   ··· SECURE",
            font=("Consolas", 10), text_color="#4ab0c8", justify="left"
        )
        self.diag_label.pack(pady=4, padx=10, anchor="w")

        # ========== BOTTOM COMMAND BAR ==========
        bottom = ctk.CTkFrame(self, fg_color="#020a14", border_color="#00e5ff", border_width=1, height=54)
        bottom.pack(fill="x", padx=8, pady=(3, 8))
        bottom.pack_propagate(False)

        self.cmd_entry = ctk.CTkEntry(
            bottom,
            placeholder_text="▸ Type command  |  or say 'Jarvis' then speak...",
            fg_color="#01060c", text_color="#00e5ff", border_color="#00aacc",
            font=("Consolas", 12), height=32
        )
        self.cmd_entry.pack(side="left", fill="x", expand=True, padx=(10, 5), pady=10)
        self.cmd_entry.bind("<Return>", self._on_text)

        send_cfg = dict(
            fg_color="#031018", hover_color="#00c8ff", border_color="#00e5ff",
            border_width=1, text_color="#7fd8ff", font=("Consolas", 10, "bold"),
            height=32, corner_radius=3
        )
        ctk.CTkButton(bottom, text="SEND", width=68, command=self._on_text, **send_cfg).pack(
            side="left", padx=2, pady=10
        )
        ctk.CTkButton(
            bottom, text="🎤 TALK", width=88, command=self._on_ptt,
            fg_color="#021a10", hover_color="#39ff14", border_color="#39ff14",
            border_width=1, text_color="#aaffcc", font=("Consolas", 10, "bold"), height=32
        ).pack(side="left", padx=6, pady=10)

    def _tech_header(self, parent, title):
        f = ctk.CTkFrame(parent, fg_color="transparent", height=22)
        f.pack(fill="x", padx=6, pady=(8, 1))
        f.pack_propagate(False)
        ctk.CTkLabel(f, text=f"◆ {title}", font=("Consolas", 10, "bold"),
                     text_color="#00e5ff").pack(side="left")

    # ---------- Buttons ----------
    def _btn_lock(self):
        self.log(">> SECURITY LOCK ENGAGED")
        threading.Thread(target=lock_workstation, daemon=True).start()

    def _btn_vol(self):
        self.log(">> VOLUME → 50%")
        threading.Thread(
            target=lambda: (set_volume(0.5), speak_jarvis("Volume set to fifty percent, sir.")),
            daemon=True
        ).start()

    def _btn_batt(self):
        status = get_battery_status()
        self.log(f">> POWER: {status}")
        threading.Thread(target=lambda: speak_jarvis(f"Power status: {status}, sir."), daemon=True).start()

    def _btn_news(self):
        self.log(">> FETCHING HEADLINES...")

        def _f():
            headlines = fetch_news(5)
            if headlines:
                for h in headlines:
                    ui_queue.put(("LOG", f"NEWS: {h}"))
                ui_queue.put(("SCREEN", ("TOP HEADLINES", headlines)))
                speak_jarvis("Headlines retrieved, sir.")
            else:
                ui_queue.put(("LOG", "News feed unavailable."))
                speak_jarvis("I could not reach the news feed, sir.")
        threading.Thread(target=_f, daemon=True).start()

    def _btn_weather(self):
        def _w():
            w = get_weather("Athens")
            ui_queue.put(("WEATHER", f"ATHENS\n{w}"))
            ui_queue.put(("SCREEN", ("WEATHER REPORT", ["ATHENS, GREECE", w, "", f"Updated {time.strftime('%H:%M:%S')}"])))
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
                ui_queue.put(("LOG", "Screenshot failed."))
                speak_jarvis("Screenshot failed, sir.")
        threading.Thread(target=_s, daemon=True).start()

    def _on_search(self, event=None):
        query = self.search_entry.get().strip()
        if not query:
            return
        self.search_entry.delete(0, "end")
        threading.Thread(target=process_command, args=(f"search for {query}",), daemon=True).start()

    def _on_text(self, event=None):
        text = self.cmd_entry.get().strip()
        if not text:
            return
        self.cmd_entry.delete(0, "end")
        self.log(f"TEXT ▸ {text}")
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

    # ---------- Arc Reactor ----------
    def _draw_static_reactor(self):
        c = self.reactor_canvas
        cx = cy = 160
        for r, col, dash in [
            (150, "#011820", None),
            (140, "#022830", (2, 4)),
            (128, "#013040", None),
            (115, "#022838", (3, 5)),
        ]:
            c.create_oval(cx - r, cy - r, cx + r, cy + r, outline=col, width=1, dash=dash)

        for i in range(72):
            ang = math.radians(i * 5)
            inner = 148 if i % 6 == 0 else 152
            outer = 158
            c.create_line(
                cx + inner * math.cos(ang), cy + inner * math.sin(ang),
                cx + outer * math.cos(ang), cy + outer * math.sin(ang),
                fill="#013040" if i % 6 else "#024858"
            )

        for r in (95, 75):
            pts = []
            for k in range(6):
                a = math.radians(60 * k - 30)
                pts.extend([cx + r * math.cos(a), cy + r * math.sin(a)])
            c.create_polygon(pts, outline="#022838", fill="", width=1)

    def _animate(self):
        color = self.state_color
        c = self.reactor_canvas
        c.delete("rot")
        c.delete("core")
        c.delete("scan")
        cx = cy = 160

        for i in range(12):
            start = self.reactor_angle + i * 30
            c.create_arc(cx - 118, cy - 118, cx + 118, cy + 118, start=start, extent=14,
                         style="arc", outline=color, width=4, tags="rot")
        for i in range(18):
            start = -self.reactor_angle * 1.4 + i * 20
            c.create_arc(cx - 135, cy - 135, cx + 135, cy + 135, start=start, extent=5,
                         style="arc", outline=color, width=2, tags="rot")
        for i in range(8):
            start = self.reactor_angle * 0.7 + i * 45
            c.create_arc(cx - 100, cy - 100, cx + 100, cy + 100, start=start, extent=18,
                         style="arc", outline=color, width=2, tags="rot")

        pulse = 28 + 8 * math.sin(self.pulse_t)
        c.create_oval(cx - pulse - 16, cy - pulse - 16, cx + pulse + 16, cy + pulse + 16,
                     outline=color, width=1, tags="core")
        c.create_oval(cx - pulse, cy - pulse, cx + pulse, cy + pulse,
                     fill=color, outline="", tags="core")
        c.create_polygon(
            cx, cy - pulse * 0.65,
            cx - pulse * 0.55, cy + pulse * 0.4,
            cx + pulse * 0.55, cy + pulse * 0.4,
            fill="#000308", outline="", tags="core"
        )
        c.create_oval(cx - 8, cy - 8, cx + 8, cy + 8, fill=color, outline="", tags="core")

        self.scan_y = (self.scan_y + 2) % 300
        sy = 20 + self.scan_y
        c.create_line(30, sy, 290, sy, fill="#00e5ff", width=1, stipple="gray50", tags="scan")

        self.reactor_angle = (self.reactor_angle + 2.6) % 360
        self.pulse_t += 0.11

        # JARVIS OS badge pulse
        badge_pulse = 5 + 2 * math.sin(self.pulse_t)
        self.badge_canvas.delete("badge_dot")
        self.badge_canvas.create_oval(10 - badge_pulse, 10 - badge_pulse, 10 + badge_pulse, 10 + badge_pulse,
                                       fill=color, outline="", tags="badge_dot")

        # Mic spectrum bars
        self.mic_canvas.delete("bars")
        active = self.state_name == "listening"
        w = 270 / len(self.mic_bars)
        for i in range(len(self.mic_bars)):
            target = random.randint(5, 40) if active else 2
            self.mic_bars[i] += (target - self.mic_bars[i]) * 0.48
            h = max(2, self.mic_bars[i])
            x0 = i * w + 1
            self.mic_canvas.create_rectangle(
                x0, 44 - h, x0 + w - 2, 44,
                fill=STATE_COLORS["listening"] if active else "#0a2030",
                outline="", tags="bars"
            )

        self.after(35, self._animate)

    # ---------- Waveform panels (real network traffic) ----------
    def _draw_waveform(self, canvas, data, color):
        canvas.delete("wave")
        w, h = 280, 70
        maxval = max(max(data), 1.0)
        step = w / (len(data) - 1)
        points = []
        for i, v in enumerate(data):
            x = i * step
            y = h - 6 - (v / maxval) * (h - 14)
            points.extend([x, y])
        if len(points) >= 4:
            canvas.create_line(*points, fill=color, width=2, smooth=True, tags="wave")
        # baseline grid
        canvas.create_line(0, h - 4, w, h - 4, fill="#0a2030", tags="wave")

    # ---------- Circular gauges ----------
    def _draw_gauge(self, cx, cy, r, pct, color, label, value, tag, sub=None):
        self.gauge_canvas.delete(tag)
        pct = max(0.0, min(100.0, pct))
        self.gauge_canvas.create_arc(
            cx - r, cy - r, cx + r, cy + r, start=225, extent=-270,
            style="arc", outline="#0a1e2c", width=8, tags=tag
        )
        self.gauge_canvas.create_arc(
            cx - r, cy - r, cx + r, cy + r, start=225, extent=-270 * (pct / 100),
            style="arc", outline=color, width=8, tags=tag
        )
        self.gauge_canvas.create_oval(
            cx - r + 12, cy - r + 12, cx + r - 12, cy + r - 12, outline="#0a2030", width=1, tags=tag
        )
        fs = 11 if len(value) <= 5 else 9
        self.gauge_canvas.create_text(
            cx, cy - (6 if sub else 2), text=value,
            fill=color, font=("Consolas", fs, "bold"), tags=tag
        )
        if sub:
            self.gauge_canvas.create_text(
                cx, cy + 8, text=sub, fill=color, font=("Consolas", 7), tags=tag
            )
        self.gauge_canvas.create_text(
            cx, cy + 20, text=label, fill="#3a7088", font=("Consolas", 8), tags=tag
        )

    def _update_telemetry(self):
        now = time.localtime()
        self.time_label.configure(text=time.strftime("%H:%M:%S", now))
        self.date_label.configure(text=time.strftime("%d/%m/%Y  %A", now))

        cpu = psutil.cpu_percent()
        ram = psutil.virtual_memory().percent
        net_now = psutil.net_io_counters()
        sent_delta = max(0, net_now.bytes_sent - self.net_prev.bytes_sent)
        recv_delta = max(0, net_now.bytes_recv - self.net_prev.bytes_recv)
        self.net_prev = net_now

        up_kbps = sent_delta / 1024
        down_kbps = recv_delta / 1024
        self.up_history.append(up_kbps)
        self.down_history.append(down_kbps)
        self._draw_waveform(self.up_canvas, self.up_history, "#39ff14")
        self._draw_waveform(self.down_canvas, self.down_history, "#00e5ff")

        net_pct = min(100, (up_kbps + down_kbps) / 6)

        self._draw_gauge(68, 58, 48, cpu, "#00e5ff", "CPU", f"{cpu:.0f}%", "g1")
        self._draw_gauge(205, 58, 48, ram, "#ffb400" if ram > 85 else "#00e5ff", "RAM", f"{ram:.0f}%", "g2")
        self._draw_gauge(68, 165, 48, net_pct, "#39ff14", "NET", f"{down_kbps:.0f}", "g3", sub="KB/s")

        bpct, bsub = 100, None
        try:
            b = psutil.sensors_battery()
            if b:
                bpct = b.percent
                bsub = "CHG" if b.power_plugged else "BATT"
        except Exception:
            pass
        self._draw_gauge(205, 165, 48, bpct, "#00e5ff", "PWR", f"{bpct:.0f}%", "g4", sub=bsub)
        self.after(1000, self._update_telemetry)

    # ---------- Adaptive context screen ----------
    def show_context(self, title, lines):
        """Swap the center screen to show what JARVIS is currently doing,
        then auto-revert to standby after a while — the movie-style behavior."""
        self.context_title.configure(text=title, text_color=self.state_color)
        self.context_panel.configure(state="normal")
        self.context_panel.delete("1.0", "end")
        text = "\n".join(lines) if isinstance(lines, (list, tuple)) else str(lines)
        self.context_panel.insert("end", text)
        self.context_panel.configure(state="disabled")

        if self._context_revert_id:
            try:
                self.after_cancel(self._context_revert_id)
            except Exception:
                pass
        self._context_revert_id = self.after(14000, self._revert_context)

        if title.startswith("TOP HEADLINES") and lines:
            self.news_label.configure(text=lines[0])

    def _revert_context(self):
        self.context_title.configure(text="STANDBY", text_color="#ffb400")
        self.context_panel.configure(state="normal")
        self.context_panel.delete("1.0", "end")
        self.context_panel.insert("end", "Awaiting instructions...")
        self.context_panel.configure(state="disabled")
        self._context_revert_id = None

    # ---------- Queue / state / log ----------
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
            elif msg == "SCREEN":
                title, lines = payload
                self.show_context(title, lines)
            elif msg == "QUIT":
                self.destroy()
                return
        self.after(35, self._process_ui_queue)

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
        print("[!] pycaw not found → volume control disabled (pip install pycaw comtypes)")
    if not HAS_PYAUTOGUI:
        print("[!] pyautogui not found → screenshot/alt-tab disabled (pip install pyautogui)")
    if not HAS_BS4:
        print("[!] beautifulsoup4 not found → SearXNG HTML search disabled (pip install beautifulsoup4)")
    if not HAS_DDGS:
        print("[!] ddgs not found → DuckDuckGo fallback search disabled (pip install ddgs)")

    if not HAS_SOUNDDEVICE:
        print("[!] sounddevice not found → double-clap disabled (pip install sounddevice numpy)")
    else:
        print("[i] Double-clap detection: ENABLED (sounddevice)")
    if HAS_XTTS and VOICE_SAMPLE:
        print(f"[i] Voice cloning: Coqui XTTS  |  sample: {VOICE_SAMPLE}")
    elif HAS_XTTS and not VOICE_SAMPLE:
        print("[!] XTTS installed but no voice sample found.")
        print("    Put your mp3 next to this script as: jarvis_voice_sample.mp3")
        print("    Falling back to edge-tts British voice until then.")
    else:
        print("[i] Voice: edge-tts (en-GB-RyanNeural)")
        print("    For cloned voice: pip install TTS  + put jarvis_voice_sample.mp3 next to script")
    print(f"[i] Web search order: SearXNG @ {SEARXNG_URL} (HTML scrape) → DuckDuckGo (ddgs) fallback")
    print("Tip: Type commands in the bottom bar even if mic fails.")
    print()

    app = AdvancedJarvisHUD()
    threading.Thread(target=jarvis_loop, daemon=True).start()
    app.mainloop()
