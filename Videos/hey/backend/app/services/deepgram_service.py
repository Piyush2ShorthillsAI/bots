import asyncio
import os
from dotenv import load_dotenv
from deepgram import (
    DeepgramClient,
    DeepgramClientOptions,
    LiveTranscriptionEvents,
    LiveOptions,
    # For type hinting if needed, though often the data is dict-like
    # from deepgram.clients.listen.v1.async_client import AsyncLiveClient # Example
    # from deepgram.clients.listen.v1.response import OpenResponse, LiveTranscriptionResponse, MetadataResponse, ErrorResponse, CloseResponse, UtteranceEndResponse
)
import logging # Import logging
import time # Import time for precise timing

load_dotenv()

DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")

from ..types import Event, EventType


# Get a logger for this module. It will inherit from the root logger configured in main.py
logger = logging.getLogger(__name__)

class DeepgramService:
    def __init__(self, session_manager):
        self.session_manager = session_manager
        self.dg_connection = None # This will be the AsyncLiveClient instance
        self.current_state_setter = None
        self.accumulated_transcript = str()
        self.websocket_callback = session_manager.client_websocket # ADD THIS LINE
        
        
    async def connect(self):
      #  logger.info("Attempting to connect to Deepgram...")
        try:
            config = DeepgramClientOptions(
                options={"keepalive": "true"} # Keepalive can be useful
            )
            deepgram = DeepgramClient(DEEPGRAM_API_KEY, config)
            self.dg_connection = deepgram.listen.asynclive.v("1")

            self.dg_connection.on(LiveTranscriptionEvents.Open, self._on_open)
            self.dg_connection.on(LiveTranscriptionEvents.Transcript, self._on_message)
            self.dg_connection.on(LiveTranscriptionEvents.Metadata, self._on_metadata) # Signature will change
            self.dg_connection.on(LiveTranscriptionEvents.Error, self._on_error)       # Signature will change
            self.dg_connection.on(LiveTranscriptionEvents.Close, self._on_close)       # Signature will change
            # self.dg_connection.on(LiveTranscriptionEvents.UtteranceEnd, self._on_utterance_end)

            # options = LiveOptions(
            #     model="nova-2",
            #     language="en-US",
            #     encoding="linear16",
            #     sample_rate=16000,
            #     interim_results=True,
            #     utterance_end_ms="1000",
            #     vad_events=True,
            #     smart_format=True,
            #     punctuate=True
            #)
            options = LiveOptions(
                model="nova-3",
                language="en-US",
                encoding="opus",  # <--- CHANGE THIS TO OPUS
                # sample_rate=16000, # For Opus, Deepgram often infers sample rate from the stream,
                                     # but specifying can sometimes help if issues arise.
                                     # The client requests 16000Hz, so Opus will likely encode at that.
                interim_results=True,
                utterance_end_ms="1000",
                vad_events=True,
                smart_format=True,
                punctuate=False,
                channels=1
            )


            # options = LiveOptions(
            #     model="nova-3",
            #     language="en-US",
            #     smart_format=True,
            #     encoding="linear16",
            #     channels=1,
            #     sample_rate=16000,
            #     interim_results=True,
            #     utterance_end_ms="1000",
            #     vad_events=True,
            #     punctuate=False
            # )
            print("Attempting to connect to Deepgram...")
            if await self.dg_connection.start(options) is False:
                print("Failed to connect to Deepgram")
                logger.error("Failed to connect to Deepgram.")
                # await self.websocket_callback({"type": "error", "message": "Failed to connect to STT service."})
                return False
          #  logger.info("Deepgram connection initiated successfully.")
            return True
        except Exception as e:
            print(f"Error connecting to Deepgram: {e}")
            # await self.websocket_callback({"type": "error", "message": f"STT connection error: {e}"})
            logger.exception(f"Error connecting to Deepgram: {e}")

            return False

    def set_state_setter(self, state_setter):
        self.current_state_setter = state_setter

    async def _on_open(self, dg_client_instance, open_data, **kwargs):
        # This signature assumes 'open_data' is passed as a second positional argument
        print(f"Deepgram connection opened. Client: {dg_client_instance}, Event Data: {open_data}, Kwargs: {kwargs}")
        await self.websocket_callback({"type": "stt_status", "status": "connected"})

    async def _on_message(self, dg_client_instance, result, **kwargs):
        # 'result' is the LiveTranscriptionResponse
        from ..state_machine import VoiceBotState

        if not (result and hasattr(result, 'channel') and
                hasattr(result.channel, 'alternatives') and
                result.channel.alternatives and
                hasattr(result.channel.alternatives[0], 'transcript')):
            print(f"Received malformed transcript data: {result}")
            logger.warning(f"Received malformed transcript data from Deepgram: {result}")
            return

        transcript = result.channel.alternatives[0].transcript
        is_final = hasattr(result, 'is_final') and result.is_final        
        

        # --- DEBUG START ---
        current_response_id = self.session_manager.curr_response_id
        logger.debug(f"[_on_message] Current response_id: {current_response_id}")
        logger.debug(f"[_on_message] Latency timestamps before processing: {self.session_manager.latency_timestamps}")
        # --- DEBUG END ---
        
        ################################################################
         # Capture timestamp when Deepgram sends first/interim transcript
        
        if transcript and current_response_id:
            key_for_first_transcript_time = f"deepgram_first_transcript_time_{current_response_id}"
            key_for_audio_send_start = f"deepgram_audio_send_start_{current_response_id}"

            if key_for_first_transcript_time not in self.session_manager.latency_timestamps:
                self.session_manager.latency_timestamps[key_for_first_transcript_time] = time.perf_counter()
                logger.info(f"[_on_message] Marked first transcript time for {current_response_id}")   
                # Calculate Deepgram STT latency (audio sent to first transcript received)
                audio_send_start = self.session_manager.latency_timestamps.get(f"deepgram_audio_send_start_{self.session_manager.curr_response_id}")
                logger.info("audio_send_start: %")
                
                 # --- DEBUG START ---
                logger.debug(f"[_on_message] Checking audio_send_start for key '{key_for_audio_send_start}': {audio_send_start}")
                # --- DEBUG END ---
                if audio_send_start:
                    stt_latency = (time.perf_counter() - audio_send_start) * 1000
                    logger.info(f"Deepgram STT latency (audio sent to first transcript): {stt_latency:.2f}ms for response_id: {current_response_id}") #1
                    self.session_manager.latency_timestamps.pop(key_for_audio_send_start, None) # Clean up
                    logger.debug(f"[_on_message] Cleaned up '{key_for_audio_send_start}'. Remaining: {self.session_manager.latency_timestamps}")
                else:
                    logger.warning(f"[_on_message] audio_send_start was None or not found for response_id: {current_response_id}. Cannot calculate STT latency.")
            else:
                logger.debug(f"[_on_message] First transcript time already marked for {current_response_id}. Skipping re-marking.")

        ################################################################
        if transcript:
            current_full_transcript = self.accumulated_transcript + transcript
            if is_final:
                self.accumulated_transcript = current_full_transcript + " "
                
                if self.session_manager.curr_response_id:
                    self.session_manager.latency_timestamps[f"deepgram_final_transcript_time_{self.session_manager.curr_response_id}"] = time.perf_counter()
                    logger.info(f"Marked deepgram_final_transcript_time for response_id: {self.session_manager.curr_response_id}")
                asyncio.create_task(
                    self.session_manager.handle_event(
                        Event(
                            type=EventType.INTERRUPTION_ENDED,
                            data={
                                "transcript": self.accumulated_transcript.strip(),
                                "is_final": True
                            }
                        )
                    )
                )
                # await self.session_manager.handle_event(
                #     Event(
                #         type=EventType.INTERRUPTION_ENDED,
                #         data={
                #             "transcript": self.accumulated_transcript.strip(),
                #             "is_final": True
                #         }
                #     )
                # )
                self.accumulated_transcript = str()
            else:
                
               # logger.debug(f"Interim transcript: '{self.accumulated_transcript}'")
                asyncio.create_task(
                    self.session_manager.handle_event(
                        Event(
                            type=EventType.INTERRUPTION_STARTED,
                            data={
                                "transcript": '',
                                "is_final": False
                            }
                        )
                    )
                )
                
                # await self.session_manager.handle_event(
                #     Event(
                #         type=EventType.INTERRUPTION_STARTED,
                #         data={
                #             "transcript": '',
                #             "is_final": False
                #         }
                #     )
                # )

    # async def _on_utterance_end(self, dg_client_instance, utterance_end_data, **kwargs):
    #     # 'utterance_end_data' is the UtteranceEndResponse
    #     from app.state_machine import VoiceBotState
    #     print(f"Deepgram UtteranceEnd. Client: {dg_client_instance}, Event Data: {utterance_end_data}, Kwargs: {kwargs}. Accumulated: '{self.accumulated_transcript.strip()}'")
        
    #     final_text_for_llm = self.accumulated_transcript.strip()
    #     self.accumulated_transcript = ""

    #     if final_text_for_llm:
    #         if self.current_state_setter:
    #             await self.current_state_setter(VoiceBotState.RESPONDING, final_text_for_llm)
    #     elif self.current_state_setter:
    #         current_state_value = VoiceBotState.IDLE # Default
    #         if hasattr(self.current_state_setter, '_session_ref_for_state_getter_'): # A way to get current state if main.py exposes it
    #             current_state_value = self.current_state_setter._session_ref_for_state_getter_().current_state

    #         if current_state_value == VoiceBotState.LISTENING:
    #             print("Utterance ended with no transcribed speech, returning to IDLE.")
    #             await self.current_state_setter(VoiceBotState.IDLE)

    # Handlers where the event data might be in kwargs or not passed positionally after dg_client_instance
    async def _on_metadata(self, dg_client_instance, **kwargs):
        print(f"Deepgram metadata event. Client: {dg_client_instance}, Kwargs: {kwargs}")
        # Deepgram's MetadataResponse object might be under a specific key in kwargs, or 'response'
        metadata_data = kwargs.get('metadata', kwargs.get('response')) # Common keys for such payloads
        if metadata_data:
            print(f"Actual metadata payload: {metadata_data}")
            # Example: request_id = metadata_data.request_id (if it's an object)
            # Or if it's a dict: request_id = metadata_data.get('request_id')
        else:
            logger.warning("Metadata payload not found directly in kwargs for Deepgram metadata event.")

            print("Metadata payload not found directly in kwargs. Content of kwargs was printed above.")

    async def _on_error(self, dg_client_instance, **kwargs):
        print(f"Deepgram error event. Client: {dg_client_instance}, Kwargs: {kwargs}")
        # Deepgram's ErrorResponse object might be under a specific key in kwargs
        logger.error(f"Deepgram error event. Client: {dg_client_instance}, Kwargs: {kwargs}")
        
        error_data = kwargs.get('error', kwargs.get('response')) # Common keys

        err_msg = "Unknown STT error"
        if error_data:
            logger.error(f"Actual error payload from kwargs: {error_data}")
            if hasattr(error_data, 'err_msg') and error_data.err_msg: # If it's an ErrorResponse object
                err_msg = error_data.err_msg
            elif isinstance(error_data, dict):
                err_msg = error_data.get('err_msg', error_data.get('message', str(error_data)))
            elif hasattr(error_data, 'message') and error_data.message: # General error object
                err_msg = error_data.message
            else:
                err_msg = str(error_data)
        else:
            err_msg = f"STT error occurred; no specific error data in kwargs. Kwargs printed above."
            print(err_msg)
        if self.session_manager.curr_response_id:
            keys_to_remove = [k for k in self.session_manager.latency_timestamps if k.endswith(self.session_manager.curr_response_id)]
            for k in keys_to_remove:
                self.session_manager.latency_timestamps.pop(k, None)
            logger.warning(f"Cleared latency timestamps for response_id {self.session_manager.curr_response_id} due to Deepgram error.") # This should log
        await self.websocket_callback({"type": "error", "message": f"STT error: {err_msg}"})

    async def _on_close(self, dg_client_instance, **kwargs):
        print(f"Deepgram connection closed event. Client: {dg_client_instance}, Kwargs: {kwargs}")
        # Deepgram's CloseResponse object might be under 'close' or 'response' in kwargs
        # close_data = kwargs.get('close', kwargs.get('response'))
        # if close_data:
        # print(f"Actual close event data from kwargs: {close_data}")
        await self.websocket_callback({"type": "stt_status", "status": "disconnected"})

    async def send_audio(self, audio_chunk):
        if self.dg_connection: # Simplified check
            try:
               # logger.debug(f"Sending audio chunk of size {len(audio_chunk)} to Deepgram.") # Uncomment for high volume debug
                await self.dg_connection.send(audio_chunk)
            except Exception as e:
                logger.error(f"Error sending audio to Deepgram: {e}", exc_info=True)
                # Consider how to handle this: maybe close connection, notify client, etc.
                # await self.websocket_callback({"type": "error", "message": f"STT send audio error: {e}"})
        # else:
            # print("Deepgram connection not available or already closed, cannot send audio.")


    async def close_connection(self):
        if self.dg_connection:
            print("Attempting to finish Deepgram connection...")
            try:
                await self.dg_connection.finish()
                #logger.info("Deepgram connection finished successfully.")
            except Exception as e:
                print(f"Exception during Deepgram finish: {e}")
                logger.exception(f"Exception during Deepgram finish: {e}")
            finally:
                self.dg_connection = None
                #logger.info("Deepgram connection set to None.")
                print("Deepgram connection set to None.")