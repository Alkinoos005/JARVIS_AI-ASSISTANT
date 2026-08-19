import time

def listen_for_audio(prompt_text=None):
    if prompt_text and hasattr(app, 'update_status'):
        app.update_status(prompt_text)
        
    recognizer = sr.Recognizer()
    with sr.Microphone() as source:
        # Μειώνουμε το threshold για να πιάνει πιο εύκολα τη φωνή
        recognizer.adjust_for_ambient_noise(source, duration=0.2)
        try:
            audio = recognizer.listen(source, timeout=3, phrase_time_limit=5)
            text = recognizer.recognize_google(audio, language="en-US")
            return text
        except:
            return None

def jarvis_loop():
    speak_jarvis("Systems initialized. Standing by for your instructions, sir.")
    app.update_status("STANDBY: Say 'Jarvis' to activate...")
    
    while True:
        # Ακούει στο παρασκήνιο χωρίς να τυπώνει συνεχώς στο terminal
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
                
                if not execute_system_command(cmd):
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
            
            # Επιστροφή σε standby μετά την απάντηση
            app.update_status("STANDBY: Say 'Jarvis' to activate...")
        
        time.sleep(0.1)
