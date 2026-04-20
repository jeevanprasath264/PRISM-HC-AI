"""
PRISM V3 - Voice + GUI Healthcare Assistant
Save as prism_v3_gui.py and run with: python prism_v3_gui.py

Requirements:
- Python 3.8+
- pip install SpeechRecognition pyttsx3 pyaudio
"""

import tkinter as tk
from tkinter import scrolledtext, messagebox
import threading
import queue
import speech_recognition as sr
import pyttsx3
import time
import re

# ---------------------------
# Helper: Text-to-Speech
# ---------------------------
def speak(text):
    """Speak text using pyttsx3. Reinitialize engine each time to avoid silent bugs."""
    try:
        print("PRISM (speak):", text)
        engine = pyttsx3.init()
        voices = engine.getProperty('voices')
        if len(voices) > 1:
            engine.setProperty('voice', voices[1].id)  # choose second voice if available
        engine.setProperty('rate', 170)
        engine.say(text)
        engine.runAndWait()
        engine.stop()
    except Exception as e:
        print("TTS error:", e)

# ---------------------------
# Symptom analysis & prediction
# ---------------------------
# Simple rule-based mapping: keywords -> possible conditions
CONDITION_KEYWORDS = {
    "common cold": ["cold", "runny nose", "sore throat", "sneez", "congestion"],
    "flu (influenza)": ["fever", "body ache", "chills", "high fever", "fatigue", "headache"],
    "covid-19 (suspected)": ["loss of taste", "loss of smell", "breath", "shortness", "sore throat", "fever", "cough"],
    "stomach infection/food poisoning": ["vomit", "vomiting", "diarrhea", "stomach pain", "abdominal pain", "nausea"],
    "dehydration": ["thirst", "dry mouth", "dizzy", "tired", "weak"],
    "allergy": ["itch", "itchy", "rash", "allergy", "sneeze", "watery eyes"],
    "migraine": ["severe headache", "migraine", "light sensitive", "aura"],
    "urinary infection": ["burning pee", "burn while urinating", "urine pain", "frequent urination"],
    "asthma attack (seek help)": ["wheez", "wheezing", "shortness of breath", "tight chest", "breathless"]
}

# Advice snippets for conditions
CONDITION_ADVICE = {
    "common cold": "Rest, fluids, warm drinks, and OTC paracetamol/ibuprofen if needed. See a doctor if symptoms worsen.",
    "flu (influenza)": "Rest, hydration, antipyretics for fever. If severe or breathing difficulty, seek medical care.",
    "covid-19 (suspected)": "Isolate, test if possible, monitor breathing. Seek medical care if breathing gets difficult or oxygen falls.",
    "stomach infection/food poisoning": "Stay hydrated with ORS, avoid solid food until vomiting reduces. Visit a doctor if severe or prolonged.",
    "dehydration": "Drink oral rehydration solution or water with electrolytes. Seek help if dizzy or faint.",
    "allergy": "Avoid the allergen, take antihistamines and consult a doctor if severe.",
    "migraine": "Rest in a dark quiet room, use prescribed migraine meds if available, seek medical help if new severe headache.",
    "urinary infection": "Drink lots of water and consult a doctor for antibiotics.",
    "asthma attack (seek help)": "Sit upright, use inhaler if prescribed, seek emergency help immediately if severe."
}

def analyze_symptoms(text):
    """Return list of matched conditions and a short aggregated response."""
    t = text.lower()
    matches = {}
    # small normalization
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    for condition, keywords in CONDITION_KEYWORDS.items():
        for kw in keywords:
            if kw in t:
                matches.setdefault(condition, 0)
                matches[condition] += 1

    if not matches:
        return None, "I couldn't match symptoms to a likely condition. Describe symptoms more (e.g. 'fever and cough')."

    # sort by match count
    sorted_conditions = sorted(matches.items(), key=lambda x: x[1], reverse=True)
    top_conditions = [c for c, _ in sorted_conditions[:3]]  # top 3
    # Build response
    response_lines = []
    response_lines.append("Possible conditions I think of:")
    for c in top_conditions:
        response_lines.append(f"- {c}: {CONDITION_ADVICE.get(c, 'Follow general care: rest and see a doctor if it worsens.')}")
    response_lines.append("This is NOT a diagnosis. If severe or worsening, seek professional medical help.")
    return top_conditions, "\n".join(response_lines)

# ---------------------------
# GUI App
# ---------------------------
class PrismGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("PRISM — Voice + GUI Healthcare Assistant")
        self.root.geometry("600x600")
        self.root.resizable(False, False)

        # chat display
        self.chat = scrolledtext.ScrolledText(root, wrap=tk.WORD, state=tk.DISABLED, font=("Helvetica", 11))
        self.chat.place(x=10, y=10, width=580, height=430)

        # user input entry
        self.entry_var = tk.StringVar()
        self.entry = tk.Entry(root, textvariable=self.entry_var, font=("Helvetica", 12))
        self.entry.place(x=10, y=450, width=420, height=36)
        self.entry.bind("<Return>", self.on_send)

        # send button
        self.send_btn = tk.Button(root, text="Send", command=self.on_send, width=8)
        self.send_btn.place(x=440, y=450, width=70, height=36)

        # mic button (record)
        self.mic_btn = tk.Button(root, text="🎤 Speak", command=self.on_mic_press, width=8)
        self.mic_btn.place(x=520, y=450, width=70, height=36)

        # status label
        self.status_var = tk.StringVar(value="Ready")
        self.status_label = tk.Label(root, textvariable=self.status_var, anchor="w")
        self.status_label.place(x=10, y=500, width=400, height=24)

        # clear and exit buttons
        self.clear_btn = tk.Button(root, text="Clear", command=self.clear_chat)
        self.clear_btn.place(x=420, y=500, width=70, height=30)
        self.exit_btn = tk.Button(root, text="Exit", command=self.on_exit)
        self.exit_btn.place(x=500, y=500, width=70, height=30)

        # queue for thread-safe GUI updates
        self.q = queue.Queue()

        # speech recognizer
        self.recognizer = sr.Recognizer()
        self.microphone_available = True
        try:
            # Quick microphone check (don't block long)
            with sr.Microphone() as src:
                pass
        except Exception as e:
            print("Warning: microphone not available:", e)
            self.microphone_available = False
            self.mic_btn.config(state=tk.DISABLED)

        # initial greeting
        self.insert_chat("PRISM", "Hello! I'm PRISM, your virtual healthcare assistant. Describe your symptoms or press the mic.")
        threading.Thread(target=speak, args=("Hello! I am PRISM, your virtual healthcare assistant. Describe your symptoms or press the mic.",), daemon=True).start()

        # periodic check for queue updates
        self.root.after(100, self.process_queue)

    def insert_chat(self, who, message):
        self.chat.config(state=tk.NORMAL)
        if who == "You":
            self.chat.insert(tk.END, f"You: {message}\n\n")
        else:
            self.chat.insert(tk.END, f"{who}: {message}\n\n")
        self.chat.see(tk.END)
        self.chat.config(state=tk.DISABLED)

    def set_status(self, text):
        self.status_var.set(text)

    def clear_chat(self):
        self.chat.config(state=tk.NORMAL)
        self.chat.delete(1.0, tk.END)
        self.chat.config(state=tk.DISABLED)

    def on_exit(self):
        if messagebox.askokcancel("Exit PRISM", "Are you sure you want to exit?"):
            self.root.destroy()

    # -------------------------
    # Send (text) handler
    # -------------------------
    def on_send(self, event=None):
        user_text = self.entry_var.get().strip()
        if not user_text:
            return
        self.entry_var.set("")
        self.insert_chat("You", user_text)
        self.set_status("Analyzing...")
        # analyze in background
        threading.Thread(target=self.handle_user_text, args=(user_text,), daemon=True).start()

    def handle_user_text(self, text):
        # If user asked for time
        if "time" in text.lower():
            current_time = time.strftime("%I:%M %p")
            response = f"The current time is {current_time}."
            self.q.put(("PRISM", response))
            threading.Thread(target=speak, args=(response,), daemon=True).start()
            self.set_status("Ready")
            return

        # If contains exit
        if any(w in text.lower() for w in ["bye", "exit", "quit"]):
            response = "Take care of your health! Goodbye."
            self.q.put(("PRISM", response))
            threading.Thread(target=speak, args=(response,), daemon=True).start()
            self.set_status("Ready")
            # optional: exit after short pause
            time.sleep(5)
            self.q.put(("__exit__", None))
            return

        # Try symptom analysis
        conditions, analysis_text = analyze_symptoms(text)
        self.q.put(("PRISM", analysis_text))
        threading.Thread(target=speak, args=(analysis_text,), daemon=True).start()
        self.set_status("Ready")

    # -------------------------
    # Mic (voice) handler
    # -------------------------
    def on_mic_press(self):
        if not self.microphone_available:
            messagebox.showerror("Microphone", "Microphone not available on this system.")
            return
        # spawn a thread to record so GUI doesn't hang
        t = threading.Thread(target=self.record_and_recognize, daemon=True)
        t.start()

    def record_and_recognize(self):
        self.set_status("Listening...")
        self.q.put(("PRISM", "Listening... (speak now)"))
        try:
            with sr.Microphone() as source:
                # adjust for ambient noise
                self.recognizer.adjust_for_ambient_noise(source, duration=1)
                audio = self.recognizer.listen(source, phrase_time_limit=7)
        except OSError as e:
            self.q.put(("PRISM", "Microphone error: " + str(e)))
            self.set_status("Ready")
            return

        self.set_status("Processing...")
        self.q.put(("PRISM", "Processing..."))
        try:
            text = self.recognizer.recognize_google(audio)
            self.q.put(("You", text))
            # handle like text send
            threading.Thread(target=self.handle_user_text, args=(text,), daemon=True).start()
        except sr.UnknownValueError:
            msg = "Sorry, I didn't catch that. Please try again."
            self.q.put(("PRISM", msg))
            threading.Thread(target=speak, args=(msg,), daemon=True).start()
        except sr.RequestError:
            msg = "Network error for speech recognition. Please check your connection."
            self.q.put(("PRISM", msg))
            threading.Thread(target=speak, args=(msg,), daemon=True).start()
        finally:
            self.set_status("Ready")

    # -------------------------
    # Queue processor (GUI thread)
    # -------------------------
    def process_queue(self):
        try:
            while True:
                who, message = self.q.get_nowait()
                if who == "__exit__":
                    self.root.quit()
                    return
                self.insert_chat(who, message)
        except queue.Empty:
            pass
        self.root.after(100, self.process_queue)


# ---------------------------
# Run the App
# ---------------------------
def main():
    root = tk.Tk()
    app = PrismGUI(root)
    root.protocol("WM_DELETE_WINDOW", app.on_exit)
    root.mainloop()

if __name__ == "__main__":
    main()
