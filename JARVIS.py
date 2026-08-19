import os
import asyncio
import webbrowser
import threading
import edge_tts
import pygame
import speech_recognition as sr
import customtkinter as ctk
from google import genai

# ==========================================
# CONFIGURATION
# ==========================================
GEMINI_KEY = "ΤΟ_GEMINI_API_KEY_ΣΟΥ"
client = genai.Client(api_key=GEMINI_KEY)

# ==========================================
# SYSTEM COMMANDS (PC CONTROL)
# ==========================================
def execute_system_command(command):
    cmd = command.lower()
    
    if "youtube" in cmd:
        speak_jarvis("Opening YouTube for you, sir.")
        webbrowser.open("https://www.youtube.com")
        return True
    elif "google" in cmd or "browser" in cmd:
        speak_jarvis("Opening the browser, sir.")
        webbrowser.open("https://www.google.com")
        return True
    elif "vscode" in cmd or "code" in cmd:
        speak_jarvis("Launching Visual Studio Code, sir.")
        os.system("code")
        return True
    elif "calculator" in cmd:
        speak_jarvis("Opening the calculator, sir.")
        os.system("calc")
        return True
    return False

# ==========================================
# VOICE SYNTHESIS (Monotone British Tone)
# ==========================================
async def generate_speech(text):
    # -12% rate & -8Hz pitch για πιο υποτονικό, μονότονο και ήρεμο ρομποτικό ύφος
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
def listen_for_audio(prompt_text="[Listening...]"):
    if hasattr(app, 'update_status'):
        app.update_status(prompt_text)
        
    recognizer = sr.Recognizer()
    with sr.Microphone() as source:
        recognizer.adjust_for_ambient_noise(source, duration=0.3)
        try:
            audio = recognizer.listen(source, timeout=5, phrase_time_limit=6)
            text = recognizer.recognize_google(audio, language="en-US")
            return text
        except:
            return None

# ==========================================
# CORE ASSISTANT LOGIC (Background Thread)
# ==========================================
def jarvis_loop():
    speak_jarvis("Systems initialized. Standing by for your instructions, sir.")
    
    while True:
        wake_input = listen_for_audio("STANDBY: Say 'Jarvis'...")
        
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
                
                # Έλεγχος για τοπικές εντολές υπολογιστή
                if not execute_system_command(cmd):
                    # Απάντηση από Gemini AI με αυστηρό British Gentleman Persona
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

# ==========================================
# FUTURISTIC HUD GUI (CustomTkinter)
# ==========================================
class JarvisHUD(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("J.A.R.V.I.S. SYSTEM INTERFACE")
        self.geometry("600x400")
        ctk.set_appearance_mode("dark")

        # Κεντρικό Frame
        self.main_frame = ctk.CTkFrame(self, corner_radius=15, fg_color="#0a0f1d", border_color="#00d2ff", border_width=2)
        self.main_frame.pack(fill="both", expand=True, padx=20, pady=20)

        # Τίτλος HUD
        self.title_label = ctk.CTkLabel(
            self.main_frame, text="J.A.R.V.I.S. MARK VII", 
            font=("Orbitron", 22, "bold"), text_color="#00d2ff"
        )
        self.title_label.pack(pady=(20, 10))

        # Status Display
        self.status_label = ctk.CTkLabel(
            self.main_frame, text="INITIALIZING...", 
            font=("Consolas", 14), text_color="#7f8c8d", wraplength=500
        )
        self.status_label.pack(pady=15)

        # User Text Display
        self.user_label = ctk.CTkLabel(
            self.main_frame, text="", 
            font=("Consolas", 13, "italic"), text_color="#ffffff", wraplength=500
        )
        self.user_label.pack(pady=10)

        # Arc Reactor Visual
        self.arc_reactor = ctk.CTkButton(
            self.main_frame, text="ARC CORE ONLINE", font=("Consolas", 12, "bold"),
            fg_color="transparent", border_color="#00d2ff", border_width=1,
            hover=False, text_color="#00d2ff"
        )
        self.arc_reactor.pack(side="bottom", pady=20)

    def update_status(self, text):
        self.status_label.configure(text=text)

    def update_user_text(self, text):
        self.user_label.configure(text=text)

# ==========================================
# MAIN EXECUTION
# ==========================================
if __name__ == "__main__":
    app = JarvisHUD()
    
    # Εκτέλεση σε background thread
    threading.Thread(target=jarvis_loop, daemon=True).start()
    
    app.mainloop()
