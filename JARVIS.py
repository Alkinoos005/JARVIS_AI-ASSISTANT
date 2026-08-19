import os
import requests
import pygame
import speech_recognition as sr
from google import genai

# ==========================================
# CONFIGURATION & API KEYS
# ==========================================
# 1. Gemini API Key (από αistudio.google.com - ξεκινάει με AIzaSy...)
GEMINI_KEY = "ΤΟ_GEMINI_API_KEY_ΣΟΥ"

# 2. Fish Audio API Key (το sk-fish-****Lwog που μόλις έφτιαξες)
FISH_AUDIO_API_KEY = "sk-fish-****Lwog"

# JARVIS Voice Model ID (Paul Bettany / Iron Man)
JARVIS_MODEL_ID = "7f9227f2d3274212a3d02d334e32019c"

# Αρχικοποίηση Gemini Client
client = genai.Client(api_key=GEMINI_KEY)

# ==========================================
# VOICE SYNTHESIS (Fish Audio API)
# ==========================================
def speak_jarvis(text):
    print(f"\nJARVIS: {text}")
    
    url = "https://api.fish.audio/v1/tts"
    payload = {
        "text": text,
        "reference_id": JARVIS_MODEL_ID,
        "format": "mp3",
        "latency": "normal"
    }
    headers = {
        "Authorization": f"Bearer {FISH_AUDIO_API_KEY}",
        "Content-Type": "application/json"
    }

    try:
        response = requests.post(url, json=payload, headers=headers)
        
        if response.status_code == 200:
            audio_filename = "jarvis_voice.mp3"
            with open(audio_filename, "wb") as f:
                f.write(response.content)
                
            pygame.mixer.init()
            pygame.mixer.music.load(audio_filename)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                pygame.time.Clock().tick(10)
            pygame.mixer.quit()
            
            if os.path.exists(audio_filename):
                os.remove(audio_filename)
        else:
            print(f"[Voice Error ({response.status_code})]: {response.text}")
    except Exception as e:
        print(f"[TTS Error]: {e}")

# ==========================================
# SPEECH RECOGNITION (STT)
# ==========================================
def listen():
    recognizer = sr.Recognizer()
    with sr.Microphone() as source:
        print("\n[Listening...]")
        recognizer.adjust_for_ambient_noise(source, duration=0.3)
        audio = recognizer.listen(source)
    try:
        text = recognizer.recognize_google(audio, language="en-US")
        print(f"You: {text}")
        return text
    except sr.UnknownValueError:
        return None
    except sr.RequestError as e:
        print(f"[Speech Recognition Error]: {e}")
        return None

# ==========================================
# MAIN EXECUTION LOOP
# ==========================================
if __name__ == "__main__":
    # Εισαγωγική ατάκα
    speak_jarvis("Allow me to introduce myself. I am JARVIS. How may I assist you today, sir?")

    while True:
        user_input = listen()
        if user_input:
            cmd = user_input.lower()
            
            # Εντολή τερματισμού
            if "exit" in cmd or "quit" in cmd or "goodbye" in cmd:
                speak_jarvis("Systems shutting down. Good day, sir.")
                break
                
            try:
                # Απάντηση από Gemini 2.5 Flash
                response = client.models.generate_content(
                    model='gemini-2.5-flash',
                    contents=user_input,
                    config={
                        'system_instruction': (
                            'You are JARVIS, Tony Starks AI assistant. Speak in a calm, highly intelligent, '
                            'polite British tone. Keep answers concise, witty, and extremely brief (1-2 sentences max).'
                        )
                    }
                )
                
                if response and response.text:
                    speak_jarvis(response.text)
            except Exception as e:
                print(f"[Gemini Error]: {e}")


uv pip install requests --system

Αντικατάστησε τις τιμές στις μεταβλητές GEMINI_KEY (γραμμή 12) και FISH_AUDIO_API_KEY (γραμμή 15) με τα δικά σου API Keys.

Αποθήκευσε το αρχείο (Ctrl + S).

Τρέξε από το τερματικό:

PowerShell
python jarvis.py
