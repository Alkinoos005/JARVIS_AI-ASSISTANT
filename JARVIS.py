import os
import asyncio
import edge_tts
import pygame
import speech_recognition as sr
from google import genai

# ==========================================
# CONFIGURATION
# ==========================================
GEMINI_KEY = "ΤΟ_GEMINI_API_KEY_ΣΟΥ"  # Βάλε το δικό σου Gemini Key (AIzaSy...)
client = genai.Client(api_key=GEMINI_KEY)

# ==========================================
# VOICE SYNTHESIS (Edge-TTS - 100% Free)
# ==========================================
async def generate_speech(text):
    # en-GB-RyanNeural -> Βρετανική φωνή με ελαφρώς πιο ήρεμο/βαρύ τόνο
    communicate = edge_tts.Communicate(text, "en-GB-RyanNeural", rate="-5%", pitch="-2Hz")
    await communicate.save("jarvis_voice.mp3")

def speak_jarvis(text):
    print(f"\nJARVIS: {text}")
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
        print(f"[Speech Error]: {e}")
        return None

# ==========================================
# MAIN EXECUTION
# ==========================================
if __name__ == "__main__":
    speak_jarvis("Allow me to introduce myself. I am JARVIS. How may I assist you today, sir?")

    while True:
        user_input = listen()
        if user_input:
            cmd = user_input.lower()
            
            if "exit" in cmd or "quit" in cmd or "goodbye" in cmd:
                speak_jarvis("Systems shutting down. Good day, sir.")
                break
                
            try:
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

uv pip install pvporcupine pvrecorder edge-tts pygame google-genai speechrecognition --system
