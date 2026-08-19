import asyncio
import edge_tts

async def generate_speech(text):
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
