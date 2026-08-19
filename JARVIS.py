import os
import math
import time
import random
import asyncio
import webbrowser
import threading
import requests
import psutil
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
GEMINI_KEY = " "
client = genai.Client(api_key=GEMINI_KEY)

# Colors used by both backend state changes and the HUD
STATE_COLORS = {
    "standby":    "#00f0ff",   # cyan
    "listening":  "#39ff14",   # green
    "processing": "#ffaa00",   # amber
    "speaking":   "#00aaff",   # blue
    "error":      "#ff3b3b",   # red
}

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

                # Εκτέλεση τοπικής εντολής συστήματος
                if not execute_system_command(cmd):
                    # Gemini AI για γενικές ερωτήσεις
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
        self.geometry("1200x720")
        self.configure(fg_color="#02060d")
        ctk.set_appearance_mode("dark")

        self.state_name = "standby"
        self.state_color = STATE_COLORS["standby"]
        self.reactor_angle = 0
        self.pulse_t = 0.0
        self.mic_bars = [4] * 12
        self.log_lines = []

        # ---------------- HEADER ----------------
        self.header_frame = ctk.CTkFrame(self, fg_color="#071022", border_color="#00f0ff",
                                          border_width=1, corner_radius=10)
        self.header_frame.pack(fill="x", padx=15, pady=(15, 5))

        self.title_label = ctk.CTkLabel(
            self.header_frame, text="STARK INDUSTRIES  //  J.A.R.V.I.S. HUD INTERFACE",
            font=("Consolas", 18, "bold"), text_color="#00f0ff"
        )
        self.title_label.pack(side="left", padx=20, pady=10)

        self.state_pill = ctk.CTkLabel(
            self.header_frame, text="● STANDBY", font=("Consolas", 13, "bold"),
            text_color=STATE_COLORS["standby"]
        )
        self.state_pill.pack(side="right", padx=20)

        self.time_label = ctk.CTkLabel(
            self.header_frame, text="00:00:00",
            font=("Consolas", 16, "bold"), text_color="#00d2ff"
        )
        self.time_label.pack(side="right", padx=20, pady=10)

        # ---------------- BODY ----------------
        self.body_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.body_frame.pack(fill="both", expand=True, padx=15, pady=5)

        # LEFT PANEL: SYSTEM DIAGNOSTICS
        self.left_panel = ctk.CTkFrame(self.body_frame, fg_color="#071022", border_color="#00f0ff",
                                        border_width=1, width=290)
        self.left_panel.pack(side="left", fill="y", padx=(0, 10), pady=5)
        self.left_panel.pack_propagate(False)

        ctk.CTkLabel(self.left_panel, text="[ SYSTEM MONITOR ]", font=("Consolas", 14, "bold"),
                     text_color="#00f0ff").pack(pady=15)

        self.cpu_label = ctk.CTkLabel(self.left_panel, text="CPU USAGE: 0%", font=("Consolas", 12),
                                       text_color="#a0e0ff")
        self.cpu_label.pack(anchor="w", padx=20, pady=5)
        self.cpu_bar = ctk.CTkProgressBar(self.left_panel, progress_color="#00f0ff", fg_color="#0d1b30")
        self.cpu_bar.pack(fill="x", padx=20, pady=(0, 15))

        self.ram_label = ctk.CTkLabel(self.left_panel, text="RAM USAGE: 0%", font=("Consolas", 12),
                                       text_color="#a0e0ff")
        self.ram_label.pack(anchor="w", padx=20, pady=5)
        self.ram_bar = ctk.CTkProgressBar(self.left_panel, progress_color="#00f0ff", fg_color="#0d1b30")
        self.ram_bar.pack(fill="x", padx=20, pady=(0, 15))

        self.net_label = ctk.CTkLabel(self.left_panel, text="NET ACTIVITY", font=("Consolas", 12),
                                       text_color="#a0e0ff")
        self.net_label.pack(anchor="w", padx=20, pady=5)
        self.net_bar = ctk.CTkProgressBar(self.left_panel, progress_color="#39ff14", fg_color="#0d1b30")
        self.net_bar.pack(fill="x", padx=20, pady=(0, 15))
        self.net_bar.set(0)

        self.weather_label = ctk.CTkLabel(self.left_panel, text="WEATHER: Fetching...",
                                           font=("Consolas", 12), text_color="#00d2ff", wraplength=240,
                                           justify="left")
        self.weather_label.pack(anchor="w", padx=20, pady=15)

        ctk.CTkLabel(self.left_panel, text="[ MIC INPUT ]", font=("Consolas", 14, "bold"),
                     text_color="#00f0ff").pack(pady=(20, 5))
        self.mic_canvas = tk.Canvas(self.left_panel, width=240, height=60, bg="#071022",
                                     highlightthickness=0)
        self.mic_canvas.pack(pady=5)

        # CENTER PANEL: ARC REACTOR + CONSOLE
        self.center_panel = ctk.CTkFrame(self.body_frame, fg_color="#071022", border_color="#00f0ff",
                                          border_width=1)
        self.center_panel.pack(side="left", fill="both", expand=True, pady=5)

        self.canvas = tk.Canvas(self.center_panel, width=240, height=240, bg="#071022",
                                 highlightthickness=0)
        self.canvas.pack(pady=(20, 10))
        self.draw_static_reactor()

        self.status_label = ctk.CTkLabel(
            self.center_panel, text="INITIALIZING HUD...",
            font=("Consolas", 14, "bold"), text_color="#00f0ff", wraplength=480
        )
        self.status_label.pack(pady=(5, 2))

        self.user_label = ctk.CTkLabel(
            self.center_panel, text="",
            font=("Consolas", 13, "italic"), text_color="#ffffff", wraplength=480
        )
        self.user_label.pack(pady=2)

        ctk.CTkLabel(self.center_panel, text="[ SYSTEM LOG ]", font=("Consolas", 12, "bold"),
                     text_color="#00f0ff").pack(pady=(15, 2))
        self.console = ctk.CTkTextbox(self.center_panel, fg_color="#050d18", text_color="#66e0ff",
                                       font=("Consolas", 11), border_color="#00f0ff", border_width=1)
        self.console.pack(fill="both", expand=True, padx=20, pady=(0, 15))
        self.console.configure(state="disabled")

        # RIGHT PANEL: PROTOCOLS + STATE
        self.right_panel = ctk.CTkFrame(self.body_frame, fg_color="#071022", border_color="#00f0ff",
                                         border_width=1, width=230)
        self.right_panel.pack(side="right", fill="y", padx=(10, 0), pady=5)
        self.right_panel.pack_propagate(False)

        ctk.CTkLabel(self.right_panel, text="[ PROTOCOLS ]", font=("Consolas", 14, "bold"),
                     text_color="#00f0ff").pack(pady=15)

        ctk.CTkButton(self.right_panel, text="YOUTUBE", fg_color="transparent", border_color="#00f0ff",
                      border_width=1, text_color="#00f0ff", hover_color="#0d1b30",
                      command=lambda: webbrowser.open("https://www.youtube.com")).pack(fill="x", padx=15, pady=6)
        ctk.CTkButton(self.right_panel, text="SPOTIFY", fg_color="transparent", border_color="#00f0ff",
                      border_width=1, text_color="#00f0ff", hover_color="#0d1b30",
                      command=lambda: webbrowser.open("https://open.spotify.com")).pack(fill="x", padx=15, pady=6)
        ctk.CTkButton(self.right_panel, text="CALCULATOR", fg_color="transparent", border_color="#00f0ff",
                      border_width=1, text_color="#00f0ff", hover_color="#0d1b30",
                      command=lambda: os.system("calc")).pack(fill="x", padx=15, pady=6)
        ctk.CTkButton(self.right_panel, text="VS CODE", fg_color="transparent", border_color="#00f0ff",
                      border_width=1, text_color="#00f0ff", hover_color="#0d1b30",
                      command=lambda: os.system("code")).pack(fill="x", padx=15, pady=6)

        ctk.CTkLabel(self.right_panel, text="[ VOICE STATUS ]", font=("Consolas", 14, "bold"),
                     text_color="#00f0ff").pack(pady=(25, 10))

        self.state_rows = {}
        for key in ["standby", "listening", "processing", "speaking"]:
            row = ctk.CTkFrame(self.right_panel, fg_color="transparent")
            row.pack(fill="x", padx=20, pady=4)
            dot = ctk.CTkLabel(row, text="●", font=("Consolas", 14), text_color="#1b3a4a")
            dot.pack(side="left")
            lbl = ctk.CTkLabel(row, text=key.upper(), font=("Consolas", 11), text_color="#5b7d8c")
            lbl.pack(side="left", padx=6)
            self.state_rows[key] = (dot, lbl)

        # Kick off animation loops
        self.update_telemetry()
        self.animate()

    # ---------------- STATIC REACTOR ----------------
    def draw_static_reactor(self):
        self.canvas.create_oval(10, 10, 230, 230, outline="#00394a", width=2)
        self.canvas.create_oval(35, 35, 205, 205, outline="#005577", width=1, dash=(3, 5))
        self.canvas.create_oval(60, 60, 180, 180, outline="#00394a", width=1)

    # ---------------- ANIMATION LOOP ----------------
    def animate(self):
        color = self.state_color

        # rotating segmented ring
        self.canvas.delete("rotating")
        for i in range(8):
            start = self.reactor_angle + i * 45
            self.canvas.create_arc(45, 45, 195, 195, start=start, extent=22,
                                    style="arc", outline=color, width=4, tags="rotating")
        for i in range(12):
            start = -self.reactor_angle * 1.5 + i * 30
            self.canvas.create_arc(25, 25, 215, 215, start=start, extent=8,
                                    style="arc", outline=color, width=2, tags="rotating")

        # pulsing core
        self.canvas.delete("core")
        pulse = 22 + 6 * math.sin(self.pulse_t)
        cx, cy = 120, 120
        self.canvas.create_oval(cx - pulse - 10, cy - pulse - 10, cx + pulse + 10, cy + pulse + 10,
                                 outline=color, width=1, tags="core")
        self.canvas.create_oval(cx - pulse, cy - pulse, cx + pulse, cy + pulse,
                                 fill=color, outline="", tags="core")
        self.canvas.create_polygon(
            cx, cy - pulse * 0.6, cx - pulse * 0.5, cy + pulse * 0.4,
            cx + pulse * 0.5, cy + pulse * 0.4,
            fill="#02060d", outline="", tags="core"
        )

        self.reactor_angle = (self.reactor_angle + 3) % 360
        self.pulse_t += 0.12

        # mic bars
        self.mic_canvas.delete("bars")
        active = self.state_name == "listening"
        width_per_bar = 240 / len(self.mic_bars)
        for i in range(len(self.mic_bars)):
            target = random.randint(6, 50) if active else 4
            self.mic_bars[i] += (target - self.mic_bars[i]) * 0.5
            h = max(2, self.mic_bars[i])
            x0 = i * width_per_bar + 4
            x1 = x0 + width_per_bar - 6
            y1 = 55
            y0 = y1 - h
            bar_color = STATE_COLORS["listening"] if active else "#0d3040"
            self.mic_canvas.create_rectangle(x0, y0, x1, y1, fill=bar_color, outline="", tags="bars")

        self.after(45, self.animate)

    # ---------------- TELEMETRY ----------------
    def update_telemetry(self):
        current_time = time.strftime("%H:%M:%S")
        self.time_label.configure(text=current_time)

        cpu = psutil.cpu_percent()
        ram = psutil.virtual_memory().percent
        self.cpu_label.configure(text=f"CPU USAGE: {cpu}%")
        self.cpu_bar.set(cpu / 100)

        self.ram_label.configure(text=f"RAM USAGE: {ram}%")
        self.ram_bar.set(ram / 100)

        # lightweight simulated net-activity flicker so the panel feels alive
        self.net_bar.set(random.uniform(0.05, 0.35))

        self.after(1000, self.update_telemetry)

    # ---------------- STATE / LOG HOOKS ----------------
    def set_state(self, state_name):
        if state_name not in STATE_COLORS:
            state_name = "standby"
        self.state_name = state_name
        self.state_color = STATE_COLORS[state_name]
        self.state_pill.configure(text=f"● {state_name.upper()}", text_color=self.state_color)

        for key, (dot, lbl) in self.state_rows.items():
            if key == state_name:
                dot.configure(text_color=self.state_color)
                lbl.configure(text_color="#ffffff")
            else:
                dot.configure(text_color="#1b3a4a")
                lbl.configure(text_color="#5b7d8c")

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

# MAIN EXECUTION
if __name__ == "__main__":
    app = AdvancedJarvisHUD()
    threading.Thread(target=jarvis_loop, daemon=True).start()

    def load_weather_bg():
        w = get_weather("Athens")
        app.weather_label.configure(text=f"ATHENS: {w}")
    threading.Thread(target=load_weather_bg, daemon=True).start()

    app.mainloop()
