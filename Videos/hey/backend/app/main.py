import asyncio
import aiohttp
from fastapi import FastAPI, WebSocket, WebSocketDisconnect,Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
import os
from dotenv import load_dotenv
from .state_machine import VoiceBotState
from .services.deepgram_service import DeepgramService
from .services.llm_service import LLMService
from datetime import datetime
import json
import time  # Import time for precise timing
import logging  # Import the logging module
from logging.handlers import RotatingFileHandler # Import RotatingFileHandler
load_dotenv()

#################################################################################################################################
# --- Configure Logging ---
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "backend.log")

# Define log file size and number of backups (example for RotatingFileHandler)
MAX_LOG_BYTES = 5 * 1024 * 1024 # 5 MB
BACKUP_COUNT = 5                # Keep 5 backup log files

# Create a formatter
log_formatter = logging.Formatter(
    '%(asctime)s.%(msecs)03d - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Create file handler
file_handler = RotatingFileHandler(
    LOG_FILE,
    maxBytes=MAX_LOG_BYTES,
    backupCount=BACKUP_COUNT
)
file_handler.setFormatter(log_formatter)
file_handler.setLevel(logging.INFO) # Set level for file handler

# Create console handler
console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)
console_handler.setLevel(logging.INFO) # Set level for console handler

# Get the root logger
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO) # Set the overall minimum level for the root logger

# Add handlers to the root logger
# Clear existing handlers if any from previous basicConfig calls (e.g., in testing)
if root_logger.hasHandlers():
    root_logger.handlers.clear()
root_logger.addHandler(file_handler)
root_logger.addHandler(console_handler)

# Get a specific logger for this module (main.py)
logger = logging.getLogger(__name__)

# --- END Logging Configuration ---
#########################################################################################################################################

app = FastAPI()

#########################################################################################################################################
# --- Static Files ---

# Mount static files for the frontend
BASE_DIR = os.path.dirname(os.path.abspath(__file__)) # This is /project_root/backend/app
# Go up two levels to /project_root, then into 'Heygen-Video-Generator', then into 'dist'
FRONTEND_DIR = os.path.join(BASE_DIR, "..", "..", "Heygen-Video-Generator", "dist")
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

#########################################################################################################################################
from .types import Event, EventType
import uuid
NIFI_URL = os.getenv("NIFI_URL") # Default to localhost if not set
# --- In-memory session management (for simplicity) ---
class SessionManager:
    def __init__(self, client_websocket: WebSocket):
        self.current_state: VoiceBotState = VoiceBotState.IDLE
        self.deepgram_service: DeepgramService | None = None
        self.client_websocket = client_websocket
        self.to_halt_ids = set()
        self.curr_response_id = None
        # Add a dictionary to store timestamps for latency calculations
        self.latency_timestamps = {} # Key: response_id or a custom event ID, Value: time.perf_counter() timestamp
    async def respond(self, data: dict):
        # Retrieve timestamp for NIFI request start
        timestamp_start_nifi_call = time.perf_counter() # This marks the start of the NIFI call
        self.latency_timestamps[f"nifi_call_start_{self.curr_response_id}"] = timestamp_start_nifi_call
      #  logger.info(f"SessionManager.respond called with data: {data}. NIFI call initiated for response_id: {self.curr_response_id}")

        body = json.dumps({"chatInput": data["transcript"]})
       # logger.info(f"Sending request to NIFI_URL: {NIFI_URL} with body: {body}")
        
        if self.client_websocket:
            # Make the HTTP POST request to your image-query endpoint
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(NIFI_URL,
                        headers={"Content-Type": "application/json"},
                        data=body
                    ) as response:
                        response.raise_for_status()  # Raise an exception for bad status codes
                        #query_result_dict = await response.json()
                         # --- FIX START: Indentation corrected for the following block ---
                        raw_response_text = await response.text() # Read as plain text
                    
                        # Optional: Log the received content type and raw text for debugging
                        logger.info(f"NIFI Raw Response (Content-Type: {response.headers.get('Content-Type', 'N/A')}): {raw_response_text[:500]}...") # Log first 500 chars

                        try:
                        # Attempt to parse the raw text as JSON
                           query_result_dict = json.loads(raw_response_text)
                        #   logger.info(f"nifi_response_dict: {query_result_dict}") # Log the parsed JSON
                        except json.JSONDecodeError as json_e:
                           logger.error(f"Failed to parse NIFI response as JSON: {json_e}. Raw text: {raw_response_text}", exc_info=True)
                           await self.client_websocket.send_json({
                            "type": "error",
                            "message": f"Backend Error: NIFI response was not valid JSON. Details: {json_e}"
                        })
                           return # Stop processing if JSON parsing fails
                    # --- FIX END ---
                    timestamp_end_nifi_call = time.perf_counter() # Record end time for NIFI latency
                    nifi_latency = (timestamp_end_nifi_call - timestamp_start_nifi_call) * 1000 # Latency in milliseconds
                    logger.info(f"NIFI service response received. Latency: {nifi_latency:.2f}ms for response_id: {self.curr_response_id}") #2
                    self.latency_timestamps[f"nifi_call_end_{self.curr_response_id}"] = timestamp_end_nifi_call
                        
                        # Calculate total backend processing latency if response_id start is available
                    full_backend_start_time = self.latency_timestamps.get(f"overall_backend_start_{self.curr_response_id}")
                    if full_backend_start_time:
                            overall_backend_latency = (timestamp_end_nifi_call - full_backend_start_time) * 1000
                            logger.info(f"Overall backend processing latency (initial audio to LLM response sent): {overall_backend_latency:.2f}ms for response_id: {self.curr_response_id}") #3
                            self.latency_timestamps.pop(f"overall_backend_start_{self.curr_response_id}", None) # Clean up
                 # --- This part is exactly right for the NIFI output structure ---
                llm_message = query_result_dict # query_result_dict IS the {"messages": [...]} structure
            
                
                async for llm_response_chunk in self._call_llm(llm_message):
                   await self.client_websocket.send_json({
                   "type": "llm_response",
                   "text": llm_response_chunk,
                   "response_id": self.curr_response_id
            })
                       # logger.info(f"Sent llm_response to frontend for response_id: {self.curr_response_id}")
            except aiohttp.ClientError as e:
                error_msg = f"Error calling query service: {e}"
                logger.error(error_msg, exc_info=True) # Log exception info
                await self.client_websocket.send_json({
                    "type": "error",
                    "message": f"Error processing  query: {e}"
                })
            except Exception as e:
                error_msg = f"An unexpected error occurred in respond: {e}"
                logger.error(error_msg, exc_info=True) # Log exception info
                await self.client_websocket.send_json({
                    "type": "error",
                    "message": f"An unexpected error occurred: {e}"
                })
        await self.handle_event(event=Event(type=EventType.RESPONSE_COMPLETED, data={}))
       # logger.info("Handle_event called for RESPONSE_COMPLETED.")


    
    async def respond_user_message_interpretation(self, data: dict):
        #logger.info(f"SessionManager.respond_user_message_interpretation called. is_final: {data.get('is_final')}, transcript: '{data.get('transcript')}'")
        # This method is called when the user message is interpreted by Deepgram
        if data.get("is_final"):
            json = {
                "type": "transcript",
                "is_final": data["is_final"],
                "text": data["transcript"],
                "timestamp": datetime.now().strftime("%d-%m-%Y %H:%M:%S"),
                "response_id": self.curr_response_id
            }
            await self.client_websocket.send_json(json)
         #   logger.info(f"Sent final transcript to frontend: '{data['transcript']}' for response_id: {self.curr_response_id}")
            
            # Measure latency from final transcript to NIFI request (this will happen immediately after)
            if self.latency_timestamps.get(f"deepgram_final_transcript_time_{self.curr_response_id}"):
                final_transcript_time = self.latency_timestamps.pop(f"deepgram_final_transcript_time_{self.curr_response_id}")
                time_to_nifi_request = (time.perf_counter() - final_transcript_time) * 1000
                logger.info(f"Latency (Deepgram final transcript to NIFI request initiation): {time_to_nifi_request:.2f}ms for response_id: {self.curr_response_id}") #4
                
            
    async def handle_event(self, event: Event):        
        #logger.info(f"SessionManager.handle_event received event type: {event.type.name}, current state: {self.current_state.name}")

        if event.type == EventType.INTERRUPTION_STARTED and self.current_state != VoiceBotState.LISTENING:
            self.current_state = VoiceBotState.LISTENING
          
            if self.curr_response_id:
                await self.client_websocket.send_json(data={
                    'type': "halt",
                    'text': None,
                    'response_id': self.curr_response_id,
                    "halted_response_ids": list(self.to_halt_ids)
                })
            _uuid = str(uuid.uuid4())
            self.curr_response_id = _uuid
            self.to_halt_ids.add(_uuid)
            logger.info(f"New curr_response_id generated: {_uuid}. Added to halted_ids.")

            self.latency_timestamps[f"overall_backend_start_{self.curr_response_id}"] = time.perf_counter()
           # logger.info(f"Marked overall_backend_start for response_id: {self.curr_response_id}")
            logger.info(f"[handle_event] Marked overall_backend_start for response_id: {self.curr_response_id}")

            # --- Important: This is where Deepgram audio send start should be marked! ---
            # It's crucial this happens *after* curr_response_id is set
            self.latency_timestamps[f"deepgram_audio_send_start_{self.curr_response_id}"] = time.perf_counter()
            logger.info(f"[handle_event] Marked deepgram_audio_send_start for response_id: {self.curr_response_id}")
            
        elif self.current_state == VoiceBotState.LISTENING and event.type == EventType.INTERRUPTION_ENDED:
            self.current_state = VoiceBotState.RESPONDING
           
            asyncio.create_task(self.respond_user_message_interpretation(event.data))
            asyncio.create_task(self.respond(event.data))
            # await self.respond_user_message_interpretation(event.data)
            # await self.respond(event.data)
        elif self.current_state == VoiceBotState.RESPONDING and event.type == EventType.RESPONSE_COMPLETED:
            self.current_state = VoiceBotState.IDLE
          
            if self.curr_response_id:
                self.to_halt_ids.discard(self.curr_response_id)
                logger.info(f"Discarded {self.curr_response_id} from halted_ids. Remaining: {self.to_halt_ids}")
            self.curr_response_id = None
            keys_to_remove = [k for k in self.latency_timestamps if k.endswith(self.curr_response_id)]
            for k in keys_to_remove:
                self.latency_timestamps.pop(k, None)

    async def set_state(self, new_state: VoiceBotState, data: str | None = None):
        self.current_state = new_state

    def get_current_bot_state(self): # Add this method
        return self.current_state

    async def _call_llm(self, message):
        from .services.llm_service import LLMService
        llm = LLMService()
        messages = message["messages"]
        curr_str = str()
        generator = llm.get_response_stream(messages)
        async for item in generator:
            if self.current_state != VoiceBotState.RESPONDING:
                await generator.aclose()
                return
            else:
                curr_str += item
                if any(char in curr_str for char in [".", "!", "?"]):
                    resp = curr_str
                    curr_str = str()
                    yield resp


@app.on_event("startup")
async def startup_event():
 
    # Check Azure OpenAI connection
    try:
        from .services.llm_service import LLMService
        llm = LLMService()
 
        headers = {
            "api-key": llm.api_key,
            "Content-Type": "application/json"
        }
        payload = {
            "messages": [{"role": "user", "content": "ping"}],
            "temperature": 0,
            "stream": False
        }
 
        async with aiohttp.ClientSession() as session:
            async with session.post(llm.api_url, headers=headers, json=payload) as resp:
                if resp.status != 200:
                    raise Exception(f"Azure OpenAI API call failed: {resp.status}, {await resp.text()}")
                data = await resp.json()
                if "choices" not in data or len(data["choices"]) == 0:
                    raise Exception("Azure OpenAI response did not contain choices.")
                print("Azure OpenAI connection successful.")
    except Exception as e:
        print(f"Could not connect to Azure OpenAI on startup: {e}. Please check your credentials and endpoint.")
    
@app.get("/", response_class=HTMLResponse)
async def get_root():
    # Serve the frontend HTML
   # logger.info("Root endpoint '/' accessed.")
    html_file_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(html_file_path):
        with open(html_file_path, "r") as f:
            return HTMLResponse(content=f.read())
    logger.error(f"Frontend index.html not found at: {html_file_path}") # This is an error if it's supposed to be there
   
    return HTMLResponse("<h1>Frontend not found</h1>")

async def websocket_message_sender(websocket: WebSocket, message: dict):
    """Helper to send messages to client websocket."""
    await websocket.send_json(message)

@app.websocket("/ws/voice")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    session = SessionManager(client_websocket=websocket)
   # logger.info("WebSocket accepted.")
    # Initialize Deepgram service for this connection
    session.deepgram_service = DeepgramService(
        session_manager=session
    )
    session.deepgram_service.set_state_setter(session.set_state)

    try:
        # Initial state update to client
        await session.set_state(VoiceBotState.IDLE)
        deepgram_connect_start = time.perf_counter() # Mark Deepgram connection start
        
        # Attempt to connect to Deepgram
        if not await session.deepgram_service.connect():
            await websocket.send_json({"type": "error", "message": "Could not connect to STT service."})
            # Keep WebSocket open but STT won't work
        else:
            deepgram_connect_end = time.perf_counter()
            deepgram_connect_latency = (deepgram_connect_end - deepgram_connect_start) * 1000
            logger.info(f"Deepgram connection successful. Latency: {deepgram_connect_latency:.2f}ms. Ready to listen.") #5
            await websocket.send_json({"type": "info", "message": "Connected to STT. Ready to listen."})


        while True:
            data = await websocket.receive()
            
            if "bytes" in data:
                audio_chunk = data["bytes"]
                # print(f"Received audio chunk of size: {len(audio_chunk)}")
                if session.deepgram_service and session.deepgram_service.dg_connection:
                    # Event: Deepgram powered -> transcript not null + is_final = False (interruption_started)
                    # This is implicitly handled by Deepgram SDK callbacks now which will set state
                    if session.current_state == VoiceBotState.IDLE:
                        pass
                        # asyncio.create_task(session.handle_event())
                        # await session.set_state(VoiceBotState.LISTENING) # Explicitly move to listening on first audio
                    if session.curr_response_id and f"deepgram_audio_send_start_{session.curr_response_id}" not in session.latency_timestamps:
                        session.latency_timestamps[f"deepgram_audio_send_start_{session.curr_response_id}"] = time.perf_counter()
                        logger.info(f"Marked deepgram_audio_send_start for response_id: {session.curr_response_id}")
                   
                    await session.deepgram_service.send_audio(audio_chunk)
                else:
                    logger.warning("STT service not connected. Audio not processed.")
                    await websocket.send_json({"type": "warning", "message": "STT service not connected. Audio not processed."})

            elif "text" in data: # For control messages if any, or if client sends text
                message = data["text"]
                print(f"Received text message: {message}")
                # Potentially handle text commands from client, e.g., "stop", "reset"
                if message == "REQUEST_IDLE_STATE": # Example control message
                    await session.set_state(VoiceBotState.IDLE)
                    await websocket.send_json({"type": "info", "message": "Bot set to IDLE by request."})


    except WebSocketDisconnect:
        print("Client disconnected")
        if session.deepgram_service:
            await session.deepgram_service.close_connection()
        session.client_websocket = None
        # Reset state or session if needed
        session.current_state = VoiceBotState.IDLE 
        session.latency_timestamps.clear() # Clear all latency timestamps on disconnect
       # logger.info("Session manager and latency timestamps reset on disconnect.")
    except Exception as e:
        print(f"WebSocket Error: {e}")
        logger.exception(f"WebSocket Error: {e}")
        if session.client_websocket: # Check if still connected
            try:
                await session.client_websocket.send_json({
                    "type": "error",
                    "message": f"An internal server error occurred: {str(e)}"
                })
            except Exception as send_e:
                logger.error(f"Error sending error to client: {send_e}")
    finally:
        if session.deepgram_service:
            await session.deepgram_service.close_connection()
        session.client_websocket = None # Clear websocket on disconnect/error
        session.latency_timestamps.clear() # Ensure clear on any exit
        #logger.info("WebSocket connection closed for session.")

# To run: uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000