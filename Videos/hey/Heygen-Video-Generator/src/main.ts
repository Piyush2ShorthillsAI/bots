// import StreamingAvatar, {
//   AvatarQuality,
//   StreamingEvents,
//   TaskType,
// } from "@heygen/streaming-avatar";



// import { AudioRecorder } from "./speech_to_text";




// // DOM elements
// const videoElement = document.getElementById("avatarVideo") as HTMLVideoElement;
// const startButton = document.getElementById("startSession") as HTMLButtonElement;
// const endButton = document.getElementById("endSession") as HTMLButtonElement;
// const recordButton = document.getElementById("recordButton") as HTMLButtonElement;
// const recordingStatus = document.getElementById("recordingStatus") as HTMLParagraphElement;


// let avatar: StreamingAvatar | null = null;
// let sessionData: any = null;
// let audioRecorder: AudioRecorder | null = null;
// let isRecording = false;

// // Helper function to fetch access token
// async function fetchAccessToken(): Promise<string> {
//   const apiKey = import.meta.env.VITE_HEYGEN_API_KEY;

//   if (!apiKey) {
//     throw new Error("HEYGEN API key is missing. Check your .env file.");
//   }

//   const response = await fetch("https://api.heygen.com/v1/streaming.create_token", {
//     method: "POST",
//     headers: {
//       "x-api-key": apiKey,
//       "Content-Type": "application/json",
//     },
//     body: JSON.stringify({}),
//   });  

//   const { data } = await response.json();
//   return data.token;
// }

// // Initialize streaming avatar session
// async function initializeAvatarSession() {
//   // Disable start button immediately to prevent double clicks
//   startButton.disabled = true;

//   try {
//     const token = await fetchAccessToken();
//     avatar = new StreamingAvatar({ token });

//     // Initialize OpenAI Assistant
//     // Replace OpenAI API config with Azure config
      

    
//     avatar.on(StreamingEvents.STREAM_READY, handleStreamReady);
//     avatar.on(StreamingEvents.STREAM_DISCONNECTED, handleStreamDisconnected);
    
//     sessionData = await avatar.createStartAvatar({
//       quality: AvatarQuality.Medium,
//       avatarName: "Wayne_20240711",
//       language: "English",
//     });

//     console.log("Session data:", sessionData);
    
//     // Enable end button
//     endButton.disabled = false;

//   } catch (error) {
//     console.error("Failed to initialize avatar session:", error);
//     // Re-enable start button if initialization fails
//     startButton.disabled = false;
//   }
// }

// // Handle when avatar stream is ready
// function handleStreamReady(event: any) {
//   if (event.detail && videoElement) {
//     videoElement.srcObject = event.detail;
//     videoElement.onloadedmetadata = async () => {
//       await avatar?.room?.startAudio();
//       await avatar?.room?.startVideo();
//       videoElement.play().catch(console.error);
//     };
//   } else {
//     console.error("Stream is not available");
//   }
// }
// function initializeAudioRecorder() {
//   audioRecorder = new AudioRecorder(
//     (status) => {
//       recordingStatus.textContent = status;
//     },
//     async (transcribedText) => {
//       try {
        
//         if (avatar) {
//           console.log("Transcribed text:", transcribedText);
//           const response = await fetch("http://localhost:8090/image-query", {
//             method: "POST",
//             headers: { "Content-Type": "text/plain" },
//             body:transcribedText,
//           });
         
//           const resultText = await response.text();  // <-- Extract text here

//           console.log("nifi response:", resultText);

//           await avatar.speak({
//             text: resultText,
//             taskType: TaskType.REPEAT,
           
//           });
//         }
        
//         console.log("completed speaking");
//       } catch (error) {
//         console.error("Error processing transcribed input:", error);
//       }
//     }
//   );
//   }
// async function toggleRecording() {
//   if (!audioRecorder) {
//       initializeAudioRecorder();
//   }

//   if (!isRecording) {
//       recordButton.textContent = "Stop Recording";
//       await audioRecorder?.startRecording();
//       isRecording = true;
//   } else {
//       recordButton.textContent = "Start Recording";
//       audioRecorder?.stopRecording();
//       isRecording = false;
//   }
// }
// // Handle stream disconnection
// function handleStreamDisconnected() {
//   console.log("Stream disconnected");
//   if (videoElement) {
//     videoElement.srcObject = null;
//   }

//   // Enable start button and disable end button
//   startButton.disabled = false;
//   endButton.disabled = true;
// }

// // End the avatar session
// async function terminateAvatarSession() {
//   if (!avatar || !sessionData) return;

//   await avatar.stopAvatar();
//   videoElement.srcObject = null;
//   avatar = null;
  
// }


// startButton.addEventListener("click", initializeAvatarSession);
// endButton.addEventListener("click", terminateAvatarSession);
// recordButton.addEventListener("click", toggleRecording);


// NEW: Track if MediaRecorder is actively sending data to the backend


//
import StreamingAvatar, {
  AvatarQuality,
  StreamingEvents,
  TaskType,
} from "@heygen/streaming-avatar";

// DOM elements
const videoElement = document.getElementById("avatarVideo") as HTMLVideoElement;
const startButton = document.getElementById("startSession") as HTMLButtonElement;
const endButton = document.getElementById("endSession") as HTMLButtonElement;
const recordButton = document.getElementById("recordButton") as HTMLButtonElement; // Repurposed for mic status/mute
const recordingStatus = document.getElementById("recordingStatus") as HTMLParagraphElement; // For transcripts
/////////////////////////////////////////////////////////////////////

const latencyOutput = document.getElementById("latencyOutput") as HTMLPreElement; // Element to display/store latencies JSON
const downloadButton = document.getElementById("downloadLatencies") as HTMLButtonElement; // New: Download button

///////////////////////////////////////////////////////////////////////////

let avatar: StreamingAvatar | null = null;
let sessionData: any = null;
let socket: WebSocket | null = null; // WebSocket instance for backend communication
let isCurrentlySpeaking = false; // Flag to track if the avatar is speaking (HeyGen's status)

// --- Variables for Continuous Recording & Backend-Driven Interrupt Logic ---
let mediaRecorder: MediaRecorder | null = null;
let microphoneStream: MediaStream | null = null; // To hold the microphone stream and stop tracks
let isMicrophoneActive = false; // Track if the microphone is actively capturing

// --- Global set to track halted response IDs ---
// This set will store IDs of responses that the backend has told us to halt.
const haltedResponseIds = new Set<string>();

// --- Latency Tracking Variables ---
interface FrontendLatencyRecord {
  type: string; // e.g., "mic_to_backend_send", "llm_to_heygen_speak", "heygen_speak_start", "heygen_interrupt_stop"
  id?: string; // Optional: associate with a response_id if relevant
  durationMs: number;
  timestamp: string; // ISO 8601 string (e.g., "2024-07-25T14:30:00.123Z")
  details?: any; // Any additional context
}

// --- Local Storage Key ---
const LOCAL_STORAGE_LATENCY_KEY = "frontendLatenciesData";

// --- Latency Array (initialized from localStorage) ---
let frontendLatencies: FrontendLatencyRecord[] = loadLatenciesFromLocalStorage();

// Helper function to get current precise timestamp for logging
function getTimestamp(): string {
  const now = new Date();
  return `${now.toISOString().slice(0, 23)}Z`; // "2024-07-25T14:30:00.123Z"
}

// Function to load latencies from localStorage
function loadLatenciesFromLocalStorage(): FrontendLatencyRecord[] {
  try {
    const storedData = localStorage.getItem(LOCAL_STORAGE_LATENCY_KEY);
    return storedData ? JSON.parse(storedData) : [];
  } catch (e) {
    console.error("Failed to load latencies from localStorage:", e);
    return [];
  }
}

// Function to save latencies to localStorage and update UI
function saveLatenciesToLocalStorage() {
  try {
    localStorage.setItem(LOCAL_STORAGE_LATENCY_KEY, JSON.stringify(frontendLatencies));
    if (latencyOutput) {
      latencyOutput.textContent = JSON.stringify(frontendLatencies, null, 2); // Update UI
    }
  } catch (e) {
    console.error("Failed to save latencies to localStorage:", e);
  }
}

// Helper to record and store latencies
function recordFrontendLatency(type: string, durationMs: number, id?: string, details?: any) {
  const record: FrontendLatencyRecord = {
    type,
    durationMs,
    timestamp: getTimestamp(),
  };
  if (id) record.id = id;
  if (details) record.details = details;
  frontendLatencies.push(record);
 // console.log(`[LATENCY] ${type}: ${durationMs.toFixed(2)}ms`, id ? `(ID: ${id})` : '', details || '');
  saveLatenciesToLocalStorage(); // Save to localStorage after each record
}

// --- Timestamps for Latency Calculation ---
const heygenSpeakCallTimestamps: Map<string, number> = new Map(); // Key: response_id, Value: timestamp of avatar.speak() call
let heygenInterruptCallTimestamp: number | null = null; // Timestamp of avatar.interrupt() call

///////////////////////////////////////////////////////////
// Helper function to fetch access token
async function fetchAccessToken(): Promise<string> {
  const apiKey = import.meta.env.VITE_HEYGEN_API_KEY;

  if (!apiKey) {
  
    throw new Error("HEYGEN API key is missing. Check your .env file.");
  }
  try
  {
    const response = await fetch("https://api.heygen.com/v1/streaming.create_token", {
    method: "POST",
    headers: {
      "x-api-key": apiKey,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({}),
  });
  if (!response.ok) {
    // More verbose error for network issues
    const errorBody = await response.text();
   
    throw new Error(`Failed to create HeyGen token: ${response.status} ${response.statusText} - ${errorBody}`);
}
  const { data } = await response.json();
  return data.token;
}
catch (error) {
  // Pass the error object directly
  
  console.error("Error in fetchAccessToken:", error);
  throw error; // Re-throw to propagate if needed
}

}

// Initialize streaming avatar session
async function initializeAvatarSession() {
  startButton.disabled = true;
  endButton.disabled = false; // Enable end button

  if (downloadButton) downloadButton.disabled = false; // Enable download button

  try {
    const token = await fetchAccessToken();
    avatar = new StreamingAvatar({ token });
    
   
    socket = new WebSocket("wss://52.179.140.142:8000/ws/voice"); // Ensure this URL is cor[object Event]rect

    socket.onopen = () => {
     
      console.log("WebSocket connection established with backend.");
      startContinuousMicrophone(); // Start continuous microphone recording
      if (recordButton) {
        recordButton.disabled = false;
      }
    };

    socket.onmessage = async (event) => {
      try {
        const message = JSON.parse(event.data);
        console.log("Received message from backend:", message);
      
        if (message.type === "llm_response") {
          const llmText = message.text;
          const responseId = message.response_id; // Get the response ID from the backend message

          console.log("LLM Response for avatar:", llmText);
          if (avatar) {
            // Check if this specific response_id has been marked as halted by the backend.
            // Your backend's `handle_event` sends `curr_response_id` in the `halt` message.
            // We expect the `llm_response` to carry the same `response_id`.
            if (responseId && haltedResponseIds.has(responseId)) {
            
              console.log(`Skipping LLM response with ID ${message.response_id} as it was halted by backend.`);
            } else {
               // --- LATENCY POINT 2: LLM Response Received to HeyGen speak() call ---
               const startSpeakCall = performance.now();
               if (responseId) { // Only store if responseId exists
                 heygenSpeakCallTimestamps.set(responseId, startSpeakCall);
               }
                await avatar.speak({
                    text: llmText,
                    taskType: TaskType.REPEAT,
                    // If you want to associate a response_id with HeyGen's speech for
                    // finer control, you might need to pass it here if the SDK supports it.
                    // For now, `haltedResponseIds` will stop *subsequent* speaks.
                });
                const endSpeakCall = performance.now();
                recordFrontendLatency(
                "llm_to_heygen_speak_call",
                endSpeakCall - startSpeakCall,
                responseId,
                { llmTextLength: llmText.length }
              );
            }
          }
        } else if (message.type === "error") {
         
          console.error("Error from backend:", message.message);
          alert("Error: " + message.message);
        } else if (message.type === "info") {
          
          console.log("Info from backend:", message.message);
        } else if (message.type === "warning") {
          
          console.warn("Warning from backend:", message.message);
        } else if (message.type === "transcript") {
         
          if (recordingStatus) {
            recordingStatus.textContent = `Transcript: ${message.text} (Final: ${message.is_final})`;
          }
        } else if (message.type === "halt") {
            // This is the core of backend-driven interruption
          
            console.log("Received HALT message from backend.");

            if (avatar) {
                // Tell HeyGen to stop speaking immediately
                // --- LATENCY POINT 4: HeyGen Interrupt Call Start ---
                heygenInterruptCallTimestamp = performance.now();
                
                await avatar.interrupt();
               
                console.log("HeyGen avatar interrupted by backend HALT command.");
            }
            // Add the halted response IDs to the local set to prevent playing their audio later
            if (message.halted_response_ids && Array.isArray(message.halted_response_ids)) {
            
              message.halted_response_ids.forEach((id: string) => haltedResponseIds.add(id));
            }
            // log(time user function "messsage.halted_response_ids" + message.halted_response_ids);
            // Also add the specific response_id if provided (this is the `curr_response_id` from backend)
            if (message.response_id) {
              
                haltedResponseIds.add(message.response_id);
            }
        }

      } catch (error) {
      
        console.error("Error parsing WebSocket message:", error);
      }
    };

    socket.onclose = () => {
   
      console.log("WebSocket connection closed.");
      if (avatar) {
       
        avatar.stopAvatar();
      }
      socket = null;
     
      stopContinuousMicrophone();
      startButton.disabled = false;
      endButton.disabled = true;
      if (recordButton) {
       
        recordButton.disabled = true;
        recordButton.textContent = "Mic OFF";
        recordButton.style.backgroundColor = "";
      }
      if (recordingStatus) recordingStatus.textContent = "";
      if (downloadButton) downloadButton.disabled = true;
      haltedResponseIds.clear();
      heygenSpeakCallTimestamps.clear();
      heygenInterruptCallTimestamp = null;
      // Optionally clear localStorage on session close if you want fresh data for each session:
      localStorage.removeItem(LOCAL_STORAGE_LATENCY_KEY);
      frontendLatencies = []; // Clear in-memory array too if removing from local storage
      saveLatenciesToLocalStorage(); // Update UI
    
      haltedResponseIds.clear(); // Clear halted IDs on session close
    };

    socket.onerror = (error) => {
    
      console.error("WebSocket error:", error);
      alert("WebSocket error! Check console for details.");
    
      stopContinuousMicrophone();
      startButton.disabled = false;
      endButton.disabled = true;
      if (recordButton) {
        recordButton.disabled = true;
        recordButton.textContent = "Mic Error";
        recordButton.style.backgroundColor = "red";
      }
      if (recordingStatus) recordingStatus.textContent = "WebSocket Error!";
      if (downloadButton) downloadButton.disabled = true;
      haltedResponseIds.clear();
      heygenSpeakCallTimestamps.clear();
      heygenInterruptCallTimestamp = null;
      haltedResponseIds.clear(); // Clear halted IDs on error
    };

    // HeyGen SDK event listeners
    
    avatar.on(StreamingEvents.STREAM_READY, handleStreamReady);
    avatar.on(StreamingEvents.STREAM_DISCONNECTED, handleStreamDisconnected);
    // --- LATENCY POINT 3: AVATAR_START_TALKING ---
    avatar.on(StreamingEvents.AVATAR_START_TALKING, (event) => {
      console.log("Avatar AVATAR_START_TALKING event");
      isCurrentlySpeaking = true;
      // No need for interruptSentForCurrentUtterance flag here as backend dictates interrupt
      let matchedResponseId: string | undefined;
      // Heuristic: If HeyGen doesn't provide a direct ID, find the closest timestamp or the last stored ID.
      // For a robust system, HeyGen's speak() call should ideally allow passing and returning a correlation ID.
      if (event.detail?.data?.id) {
        matchedResponseId = event.detail.data.id;
      } else if (heygenSpeakCallTimestamps.size > 0) {
        // Fallback: If no direct ID, just use the last stored ID for simplicity.
        // This is a heuristic and might not be accurate if multiple speak calls happen rapidly.
        matchedResponseId = Array.from(heygenSpeakCallTimestamps.keys()).pop();
      }

      if (matchedResponseId && heygenSpeakCallTimestamps.has(matchedResponseId)) {
        const speakCallTime = heygenSpeakCallTimestamps.get(matchedResponseId)!;
        const latency = performance.now() - speakCallTime;
        recordFrontendLatency("heygen_speak_start", latency, matchedResponseId);
        heygenSpeakCallTimestamps.delete(matchedResponseId); // Clean up after use
      } else {
        recordFrontendLatency("heygen_speak_start", -1, matchedResponseId, { reason: "No matching speak call timestamp or ID from HeyGen event" });
      }    
    });
    // --- LATENCY POINT 4: AVATAR_STOP_TALKING (after interrupt or natural stop) ---
    avatar.on(StreamingEvents.AVATAR_STOP_TALKING, () => {
      console.log("Avatar AVATAR_STOP_TALKING event");
      isCurrentlySpeaking = false;
      if(isCurrentlySpeaking){}
      // When avatar finishes speaking naturally, clear any pending halted IDs
      // because a new response cycle is about to begin.
      if (heygenInterruptCallTimestamp !== null) {
        const latency = performance.now() - heygenInterruptCallTimestamp;
        recordFrontendLatency("heygen_interrupt_stop", latency);
        heygenInterruptCallTimestamp = null; // Reset
      } else {
        recordFrontendLatency("heygen_natural_stop", -1, undefined, { reason: "Avatar stopped naturally, no interrupt call recorded" });
      }
      haltedResponseIds.clear(); 
    });

    sessionData = await avatar.createStartAvatar({
      quality: AvatarQuality.Medium,
     
      avatarName: "Wayne_20240711",
      language: "English",
    });
    
    console.log("Session data:", sessionData);
  } catch (error) {
   
    console.error("Failed to initialize avatar session:", error);
    startButton.disabled = false;
    endButton.disabled = true;
    if (recordButton) {
      recordButton.disabled = true;
      recordButton.textContent = "Mic OFF";
      recordButton.style.backgroundColor = "";
    }
    if (recordingStatus) recordingStatus.textContent = "Session Init Failed.";
    if (downloadButton) downloadButton.disabled = true;
  }
}

// Handle when avatar stream is ready
function handleStreamReady(event: any) {
  if (event.detail && videoElement) {
    videoElement.srcObject = event.detail;
    videoElement.onloadedmetadata = async () => {
      await avatar?.room?.startAudio();
      await avatar?.room?.startVideo();
      videoElement.play().catch(console.error);
    };
  } else {
   
    console.error("Stream is not available");
  }
}

// Handle stream disconnection
function handleStreamDisconnected() {
 
  console.log("Stream disconnected");
  if (videoElement) {
    videoElement.srcObject = null;
  }
  startButton.disabled = false;
  endButton.disabled = true;
  stopContinuousMicrophone();
  if (recordButton) {
    recordButton.disabled = true;
    recordButton.textContent = "Mic OFF";
    recordButton.style.backgroundColor = "";
  }
  if (recordingStatus) recordingStatus.textContent = "Stream Disconnected.";
  if (downloadButton) downloadButton.disabled = true;
  haltedResponseIds.clear(); // Clear halted IDs on disconnect
  heygenSpeakCallTimestamps.clear();
  heygenInterruptCallTimestamp = null;
  // If you want to clear all data on stream disconnect:
  localStorage.removeItem(LOCAL_STORAGE_LATENCY_KEY);
  frontendLatencies = [];
  saveLatenciesToLocalStorage();
}

// End the avatar session. This uses HeyGen's streaming.stop API.
async function terminateAvatarSession() {
  if (!avatar || !sessionData) return;

  await avatar.stopAvatar();
  videoElement.srcObject = null;
  avatar = null;

  if (socket) {
    socket.close();
    socket = null;
  }
  isCurrentlySpeaking = false;
  stopContinuousMicrophone();
  startButton.disabled = false;
  endButton.disabled = true;
  if (recordButton) {
    recordButton.disabled = true;
    recordButton.textContent = "Mic OFF";
    recordButton.style.backgroundColor = "";
  }
  if (recordingStatus) recordingStatus.textContent = "Session Ended.";
  if (downloadButton) downloadButton.disabled = true;
  haltedResponseIds.clear();
  heygenSpeakCallTimestamps.clear();
  heygenInterruptCallTimestamp = null;
  // If you want to clear all data on session end:
  localStorage.removeItem(LOCAL_STORAGE_LATENCY_KEY);
  frontendLatencies = [];
  saveLatenciesToLocalStorage();
  

}


// --- Continuous Audio Recording and Sending to Backend (via WebSocket) ---
async function startContinuousMicrophone() {
 
  if (isMicrophoneActive && mediaRecorder && mediaRecorder.state === "recording") {
      console.log("Microphone is already active and recording.");
     
      return;
  }

  try {
    microphoneStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,    // Reduces echo
        noiseSuppression: true,    // Reduces background noise
        channelCount: 1,           // Forces mono audio
        // You can add other constraints like sampleRate, sampleSize if needed
        // sampleRate: 16000,
        // sampleSize: 16,
      }
    });
    mediaRecorder = new MediaRecorder(microphoneStream);
    
   
  
    mediaRecorder.ondataavailable = async (event) => {
      if (event.data.size > 0) {
        // *** CRITICAL CHANGE: REMOVE FRONTEND-TRIGGERED INTERRUPT HERE ***
        // The original `if (isCurrentlySpeaking && !interruptSentForCurrentUtterance)`
        // block is entirely removed as interruption is now backend-driven.
      
        // --- LATENCY POINT 1: Mic Audio to Backend WebSocket Send ---
      
       // const startSend = performance.now();
      
        // Send ALL audio chunk to backend via WebSocket for Deepgram processing
        if (socket && socket.readyState === WebSocket.OPEN) {
          socket.send(event.data);
       //   const endSend = performance.now();
        //  recordFrontendLatency("mic_to_backend_send", endSend - startSend, undefined, { chunkSize: event.data.size });
        
        //  console.log("Sent audio chunk to backend.",event.data); // Uncomment for detailed logging
        } else {
          console.warn("WebSocket not connected. Audio data not sent. (This should not happen if mic starts only when socket is open)");
        }
      }
    };

    mediaRecorder.onstop = () => {
      
      console.log("Microphone recording stopped.");
      isMicrophoneActive = false;
      if (recordButton) {
        recordButton.textContent = "Mic OFF";
        recordButton.style.backgroundColor = "";
      }
      if (recordingStatus) recordingStatus.textContent = "Microphone Off.";
      if (microphoneStream) {
        microphoneStream.getTracks().forEach(track => track.stop());
        microphoneStream = null;
      }
    };

    mediaRecorder.onstart = () => {
      
      console.log("Microphone recording started.");
      isMicrophoneActive = true;
      if (recordButton) {
        recordButton.textContent = "Mic ON";
        recordButton.style.backgroundColor = "green";
      }
      if (recordingStatus) recordingStatus.textContent = "Microphone On. Speak to interact.";
      // `interruptSentForCurrentUtterance` is no longer needed here.
    };

    // Start recording immediately with a timeslice to get continuous data
    mediaRecorder.start(100); 
    
    console.log("Attempting to start continuous microphone.");

  } catch (err) {
   
    console.error('Error accessing microphone:', err);
    alert(`Microphone access is required for this application: ${err instanceof Error ? err.message : String(err)}. Please allow microphone access and reload the page.`);
    isMicrophoneActive = false;
    if (recordButton) {
      recordButton.textContent = "Mic Error";
      recordButton.style.backgroundColor = "red";
    }
    if (recordingStatus) recordingStatus.textContent = "Microphone Access Denied.";
  }
}

function stopContinuousMicrophone() {
  if (mediaRecorder && mediaRecorder.state !== "inactive") {
    mediaRecorder.stop();
  } else if (microphoneStream) {
    microphoneStream.getTracks().forEach(track => track.stop());
    microphoneStream = null;
    isMicrophoneActive = false;
    if (recordButton) {
        recordButton.textContent = "Mic OFF";
        recordButton.style.backgroundColor = "";
    }
   
    console.log("Microphone stream forcefully stopped.");
  }
}

// --- Event Listeners ---
startButton.addEventListener("click", initializeAvatarSession);
endButton.addEventListener("click", terminateAvatarSession);

if (recordButton) {
  recordButton.addEventListener("click", () => {
    if (isMicrophoneActive) {
      stopContinuousMicrophone();
    
      console.log("Mic manually turned OFF.");
    } else {
      if (socket && socket.readyState === WebSocket.OPEN) {
        startContinuousMicrophone();
       
        console.log("Mic manually turned ON.");
      } else {
       
        alert("Please start an avatar session first to activate the microphone.");
      }
    }
  });
  recordButton.disabled = true;
  recordButton.textContent = "Mic OFF";
  recordButton.style.backgroundColor = "";
}
// New: Event listener for the download button
if (downloadButton) {
  downloadButton.addEventListener("click", () => {
    const dataStr = JSON.stringify(frontendLatencies, null, 2);
    const blob = new Blob([dataStr], { type: "application/json" });
    const url = URL.createObjectURL(blob);

    const a = document.createElement("a");
    a.href = url;
    // Filename will include a timestamp like 'frontend_latencies_2024-07-25T14-30-00.json'
    a.download = `frontend_latencies_${new Date().toISOString().slice(0, 19).replace(/:/g, '-')}.json`;
    document.body.appendChild(a);

    a.click();

    document.body.removeChild(a);
    URL.revokeObjectURL(url);

    console.log("Latency data download initiated.");
  });
  downloadButton.disabled = true; // Disable initially until session starts
}


startButton.disabled = false;
endButton.disabled = true;


if (downloadButton) downloadButton.disabled = true; // Ensure download button is disabled on load

// Initial UI update on page load to show any previously stored latencies
if (latencyOutput) {
    latencyOutput.textContent = JSON.stringify(frontendLatencies, null, 2);
}
