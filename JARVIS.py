import os
import asyncio
import edge_tts
import pygame
import speech_recognition as sr
from google import genai

# ==========================================
# CONFIGURATION
# ==========================================
GEMINI_KEY = "ΤΟ_GEMINI_API_KEY_ΣΟΥ"
client = genai.Client(api_key=GEMINI_KEY)

# ==========================================
# VOICE SYNTHESIS (Edge-TTS)
# ==========================================
async def generate_speech(text):
    communicate = edge_tts.Communicate(
        text, 
        "en-GB-RyanNeural", 
        rate="-8%",      # Βαρύτερος, επιβλητικός ρυθμός
        pitch="-5Hz"     # Χαμηλότερη συχνότητα τύπου Paul Bettany
    )
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
def listen_for_audio(prompt_text="[Listening...]"):
    recognizer = sr.Recognizer()
    with sr.Microphone() as source:
        print(f"\n{prompt_text}")
        recognizer.adjust_for_ambient_noise(source, duration=0.3)
        try:
            audio = recognizer.listen(source, timeout=5, phrase_time_limit=6)
            text = recognizer.recognize_google(audio, language="en-US")
            return text
        except:
            return None

# ==========================================
# MAIN EXECUTION WITH WAKE WORD
# ==========================================
if __name__ == "__main__":
    speak_jarvis("Systems online. Standing by, sir.")

    while True:
        # 1. Αναμονή για τη λέξη "Jarvis"
        wake_input = listen_for_audio("[Standby: Say 'Jarvis' to activate...]")
        
        if wake_input and "jarvis" in wake_input.lower():
            # 2. Ενεργοποίηση μόλις ακούσει "Jarvis"
            speak_jarvis("At your service, sir.")
            
            # 3. Ακρόαση της πραγματικής εντολής
            user_command = listen_for_audio("[Listening for command...]")
            
            if user_command:
                print(f"You: {user_command}")
                cmd = user_command.lower()
                
                if "exit" in cmd or "quit" in cmd or "goodbye" in cmd:
                    speak_jarvis("Shutting down systems. Goodbye, sir.")
                    break
                    
                try:
                    response = client.models.generate_content(
                        model='gemini-2.5-flash',
                        contents=user_command,
                        config={
                            'system_instruction': (
                                'You are JARVIS, Tony Starks AI assistant. Speak in a calm, highly intelligent, '
                                'polite British tone. Keep answers concise, witty, and extremely brief (1 sentence max).'
                            )
                        }
                    )
                    
                    if response and response.text:
                        speak_jarvis(response.text)
                except Exception as e:
                    print(f"[Gemini Error]: {e}")
                    if response and response.text:
                        speak_jarvis(response.text)
                except Exception as e:
                    print(f"[Gemini Error]: {e}")
