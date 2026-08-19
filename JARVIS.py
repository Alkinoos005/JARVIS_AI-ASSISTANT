import os
import time
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
GEMINI_KEY = ""
client = genai.Client(api_key=GEMINI_KEY)

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
    except:
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
    if hasattr(app, 'update_status'):
        app.update_status(f"JARVIS: {text}")
    
    asyncio.run(generate_speech(text))
    
    pygame.mixer.init()
    pygame.mixer.music.load("jarvis_voice.mp3")
    pygame.mixer.music.play()
    while pygame.mixer.music.get_busy():
        pygame.time.Clock().tick(10)
    pygame.mixer.quit()
    
    if os.path.exists("jarvis_voice.mp3"):
        os.remove("jarvis_voice.mp3")

# ==========================================
# SPEECH RECOGNITION (STT)
# ==========================================
def listen_for_audio(prompt_text=None):
    if prompt_text and hasattr(app, 'update_status'):
        app.update_status(prompt_text)
        
    recognizer = sr.Recognizer()
    with sr.Microphone() as source:
        recognizer.adjust_for_ambient_noise(source, duration=0.2)
        try:
            audio = recognizer.listen(source, timeout=3, phrase_time_limit=5)
            text = recognizer.recognize_google(audio, language="en-US")
            return text
        except:
            return None

# ==========================================
# CORE ASSISTANT LOGIC (Background Thread)
# ==========================================
def jarvis_loop():
    speak_jarvis("Systems initialized. Standing by for your instructions, sir.")
    app.update_status("STANDBY: Say 'Jarvis' to activate...")
    
    while True:
        wake_input = listen_for_audio()
        
        if wake_input and "jarvis" in wake_input.lower():
            speak_jarvis("At your service, sir.")
            
            user_command = listen_for_audio("LISTENING FOR COMMAND...")
            if user_command:
                app.update_user_text(f"You: {user_command}")
                cmd = user_command.lower()
                
                if "exit" in cmd or "quit" in cmd:
                    speak_jarvis("Shutting down systems. Have a good day, sir.")
                    app.destroy()
                    break
                
                # Εκτέλεση τοπικής εντολής συστήματος
                if not execute_system_command(cmd):
                    # Gemini AI για γενικές ερωτήσεις
                    try:
                        response = client.models.generate_content(
                            model='gemini-2.5-flash',
                            contents=user_command,
                            config={
                                'system_instruction': (
                                    'You are JARVIS, Tony Starks loyal AI assistant. Speak in an extremely well-spoken, '
                                    'polite, calm, and slightly monotone British gentleman voice. Be helpful, concise, '
                                    'and witty, keeping answers strictly to 1 short sentence. Always address the user as sir.'
                                )
                            }
                        )
                        if response and response.text:
                            speak_jarvis(response.text)
                    except Exception as e:
                        speak_jarvis("I seem to have encountered a temporary glitch, sir.")
            
            app.update_status("STANDBY: Say 'Jarvis' to activate...")
        
        time.sleep(0.1)

# ==========================================
# ADVANCED STARK HUD INTERFACE
# ==========================================
class AdvancedJarvisHUD(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("J.A.R.V.I.S. MARK VII SYSTEM INTERFACE")
        self.geometry("1100x650")
        self.configure(fg_color="#030811")
        ctk.set_appearance_mode("dark")

        # --- HEADER PANEL ---
        self.header_frame = ctk.CTkFrame(self, fg_color="#071022", border_color="#00f0ff", border_width=1, corner_radius=10)
        self.header_frame.pack(fill="x", padx=15, pady=(15, 5))

        self.title_label = ctk.CTkLabel(
            self.header_frame, text="STARK INDUSTRIES // J.A.R.V.I.S. HUD INTERFACE", 
            font=("Consolas", 18, "bold"), text_color="#00f0ff"
        )
        self.title_label.pack(side="left", padx=20, pady=10)

        self.time_label = ctk.CTkLabel(
            self.header_frame, text="00:00:00", 
            font=("Consolas", 16, "bold"), text_color="#00d2ff"
        )
        self.time_label.pack(side="right", padx=20, pady=10)

        # --- MAIN HUD BODY ---
        self.body_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.body_frame.pack(fill="both", expand=True, padx=15, pady=5)

        # LEFT PANEL: SYSTEM DIAGNOSTICS (CPU, RAM, WEATHER)
        self.left_panel = ctk.CTkFrame(self.body_frame, fg_color="#071022", border_color="#00f0ff", border_width=1, width=280)
        self.left_panel.pack(side="left", fill="y", padx=(0, 10), pady=5)
        self.left_panel.pack_propagate(False)

        ctk.CTkLabel(self.left_panel, text="[ SYSTEM MONITOR ]", font=("Consolas", 14, "bold"), text_color="#00f0ff").pack(pady=15)

        self.cpu_label = ctk.CTkLabel(self.left_panel, text="CPU USAGE: 0%", font=("Consolas", 12), text_color="#a0e0ff")
        self.cpu_label.pack(anchor="w", padx=20, pady=5)
        self.cpu_bar = ctk.CTkProgressBar(self.left_panel, progress_color="#00f0ff", fg_color="#0d1b30")
        self.cpu_bar.pack(fill="x", padx=20, pady=(0, 15))

        self.ram_label = ctk.CTkLabel(self.left_panel, text="RAM USAGE: 0%", font=("Consolas", 12), text_color="#a0e0ff")
        self.ram_label.pack(anchor="w", padx=20, pady=5)
        self.ram_bar = ctk.CTkProgressBar(self.left_panel, progress_color="#00f0ff", fg_color="#0d1b30")
        self.ram_bar.pack(fill="x", padx=20, pady=(0, 15))

        self.weather_label = ctk.CTkLabel(self.left_panel, text="WEATHER: Fetching...", font=("Consolas", 12), text_color="#00d2ff")
        self.weather_label.pack(anchor="w", padx=20, pady=20)

        # CENTER PANEL: ARC REACTOR & CONSOLE
        self.center_panel = ctk.CTkFrame(self.body_frame, fg_color="#071022", border_color="#00f0ff", border_width=1)
        self.center_panel.pack(side="left", fill="both", expand=True, pady=5)

        # Arc Reactor Canvas
        self.canvas = tk.Canvas(self.center_panel, width=220, height=220, bg="#071022", highlightthickness=0)
        self.canvas.pack(pady=(20, 10))
        self.draw_arc_reactor()

        # Status Display
        self.status_label = ctk.CTkLabel(
            self.center_panel, text="INITIALIZING HUD...", 
            font=("Consolas", 14, "bold"), text_color="#00f0ff", wraplength=450
        )
        self.status_label.pack(pady=10)

        self.user_label = ctk.CTkLabel(
            self.center_panel, text="", 
            font=("Consolas", 13, "italic"), text_color="#ffffff", wraplength=450
        )
        self.user_label.pack(pady=5)

        # RIGHT PANEL: QUICK CONTROLS / SHORTCUTS
        self.right_panel = ctk.CTkFrame(self.body_frame, fg_color="#071022", border_color="#00f0ff", border_width=1, width=220)
        self.right_panel.pack(side="right", fill="y", padx=(10, 0), pady=5)
        self.right_panel.pack_propagate(False)

        ctk.CTkLabel(self.right_panel, text="[ PROTOCOLS ]", font=("Consolas", 14, "bold"), text_color="#00f0ff").pack(pady=15)

        btn_youtube = ctk.CTkButton(self.right_panel, text="YOUTUBE", fg_color="transparent", border_color="#00f0ff", border_width=1, text_color="#00f0ff", command=lambda: webbrowser.open("https://www.youtube.com"))
        btn_youtube.pack(fill="x", padx=15, pady=8)

        btn_spotify = ctk.CTkButton(self.right_panel, text="SPOTIFY", fg_color="transparent", border_color="#00f0ff", border_width=1, text_color="#00f0ff", command=lambda: webbrowser.open("https://open.spotify.com"))
        btn_spotify.pack(fill="x", padx=15, pady=8)

        btn_calc = ctk.CTkButton(self.right_panel, text="CALCULATOR", fg_color="transparent", border_color="#00f0ff", border_width=1, text_color="#00f0ff", command=lambda: os.system("calc"))
        btn_calc.pack(fill="x", padx=15, pady=8)

        # Start HUD Background Loops
        self.update_telemetry()

    def draw_arc_reactor(self):
        """Σχεδιάζει τον φουτουριστικό Arc Reactor κύκλο"""
        self.canvas.create_oval(10, 10, 210, 210, outline="#00f0ff", width=2)
        self.canvas.create_oval(30, 30, 190, 190, outline="#005577", width=1, dash=(4, 4))
        self.canvas.create_oval(50, 50, 170, 170, outline="#00f0ff", width=3)
        self.canvas.create_oval(80, 80, 140, 140, fill="#003355", outline="#00f0ff", width=2)
        self.canvas.create_oval(95, 95, 125, 125, fill="#00f0ff", outline="")

    def update_telemetry(self):
        """Ενημερώνει σε πραγματικό χρόνο ώρα, CPU, RAM & Weather"""
        # Ώρα
        current_time = time.strftime("%H:%M:%S")
        self.time_label.configure(text=current_time)

        # CPU & RAM
        cpu = psutil.cpu_percent()
        ram = psutil.virtual_memory().percent
        self.cpu_label.configure(text=f"CPU USAGE: {cpu}%")
        self.cpu_bar.set(cpu / 100)

        self.ram_label.configure(text=f"RAM USAGE: {ram}%")
        self.ram_bar.set(ram / 100)

        # Ανανέωση κάθε 1 δευτερόλεπτο
        self.after(1000, self.update_telemetry)

    def update_status(self, text):
        self.status_label.configure(text=text)

    def update_user_text(self, text):
        self.user_label.configure(text=text)

# ==========================================
# MAIN EXECUTION
# ==========================================
if __name__ == "__main__":
    app = AdvancedJarvisHUD()
    threading.Thread(target=jarvis_loop, daemon=True).start()
    
    # Φόρτωση καιρού στο αριστερό panel
    def load_weather_bg():
        w = get_weather("Athens")
        app.weather_label.configure(text=f"ATHENS: {w}")
    threading.Thread(target=load_weather_bg, daemon=True).start()

    app.mainloop()
