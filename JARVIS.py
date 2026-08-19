import os
import asyncio
import edge_tts
import pygame
import speech_recognition as sr
from google import genai
import pvporcupine
from pvrecorder import PvRecorder

# ==========================================
# CONFIGURATION
# ==========================================
GEMINI_KEY = "ΤΟ_GEMINI_API_KEY_ΣΟΥ"
PICOVOICE_ACCESS_KEY = "ΤΟ_PICOVOICE_ACCESS_KEY_ΣΟΥ"

client = genai.Client(api_key=GEMINI_KEY)

# ==========================================
# VOICE SYNTHESIS (Optimized Edge-TTS)
# ==========================================
async def generate_speech(text):
    # Συνδυασμός παραμέτρων για να πλησιάσει τη φωνή του Paul Bettany
    communicate = edge_tts.Communicate(
        text, 
        "en-GB-RyanNeural", 
        rate="-8%",      # Ελαφρώς πιο αργή και επιβλητική ομιλία
        pitch="-5Hz"     # Πιο βαθύς/βαρύς τόνος
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
def listen():
    recognizer = sr.Recognizer()
    with sr.Microphone() as source:
        print("\n[Listening for command...]")
        recognizer.adjust_for_ambient_noise(source, duration=0.3)
        try:
            audio = recognizer.listen(source, timeout=5, phrase_time_limit=8)
            text = recognizer.recognize_google(audio, language="en-US")
            print(f"You: {text}")
            return text
        except:
            return None

# ==========================================
# WAKE WORD & MAIN LOOP
# ==========================================
def main():
    # Αρχικοποίηση Porcupine για τη λέξη "Jarvis"
    porcupine = pvporcupine.create(
        access_key=PICOVOICE_ACCESS_KEY,
        keywords=["jarvis"]
    )
    recorder = PvRecorder(device_index=-1, frame_length=porcupine.frame_length)
    recorder.start()

    print("\n[JARVIS is in standby. Say 'Jarvis' to activate...]")

    try:
        while True:
            pcm = recorder.read()
            keyword_index = porcupine.process(pcm)

            # Μόλις εντοπιστεί η λέξη "Jarvis"
            if keyword_index >= 0:
                print("\n[Wake Word Detected!]")
                speak_jarvis("At your service, sir.")
                
                # Ακούει την εντολή σου
                user_input = listen()
                if user_input:
                    cmd = user_input.lower()
                    if "exit" in cmd or "quit" in cmd:
                        speak_jarvis("Standby mode engaged. Goodbye, sir.")
                        break

                    try:
                        response = client.models.generate_content(
                            model='gemini-2.5-flash',
                            contents=user_input,
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
                
                print("\n[Returning to standby. Say 'Jarvis' to wake me...]")

    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        recorder.stop()
        recorder.delete()
        porcupine.delete()

if __name__ == "__main__":
    main()
