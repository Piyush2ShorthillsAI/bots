from enum import Enum

class VoiceBotState(Enum):
    IDLE = "Idle"
    LISTENING = "Listening"
    RESPONDING = "Responding"

# Based on your image/description:
# Events:
# 1. Deepgram powered -> transcript not null + is_final = False (interruption_started)
# 2. Deepgram powered -> transcript not null + is_final = True (interruption_completed)
# 3. Response completed (LLM + TTS cycle finished)

# Transitions:
# Given State | Event                 | New State
#----------------------------------------------------
# Idle        | interruption_started  | Listening
# Listening   | interruption_started  | Listening  (Interim results)
# Listening   | interruption_completed| Responding (Process final transcript)
# Responding  | response_completed    | Idle
