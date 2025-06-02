class EventType:
    INTERRUPTION_STARTED = "interruption_started"
    INTERRUPTION_ENDED = "interruption_ended"
    RESPONSE_COMPLETED = "response_completed"

class Event:
    
    def __init__(self, type:EventType, data:dict):
        self.type = type
        self.data = data
    
    def __repr__(self):
        return f"Event(type={self.type}, data={self.data})"