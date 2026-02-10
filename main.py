"""
EchoSpeak Backend with Gemini Live API Integration
FastAPI + WebSocket + Gemini Multimodal Live API
"""
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import os
import asyncio
import json
import base64
import logging
from typing import Optional
import aiohttp

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="EchoSpeak Live API", version="3.0.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_LIVE_URL = "wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1alpha.GenerativeService.BidiGenerateContent"

# Scenario system prompts
SCENARIO_PROMPTS = {
    'hotel-checkin': """You are a friendly hotel front desk staff member at Hilton Hotel.
Your role:
- Greet guests warmly
- Ask for reservation
- Request ID and credit card
- Assign room
- Explain hotel amenities
- Offer luggage help

Keep responses natural, brief (1-2 sentences), and professional.
Speak like a real hotel employee would.""",

    'restaurant': """You are a waiter at Olive Garden restaurant.
Your role:
- Greet customers warmly
- Ask table size
- Offer drinks
- Take food orders
- Suggest menu items
- Handle special requests

Keep responses natural, friendly, and brief (1-2 sentences).
Speak like a real waiter would.""",

    'grocery-shopping': """You are a helpful employee at a supermarket.
Your role:
- Help customers find items
- Provide product information
- Suggest alternatives
- Inform about sales
- Be friendly and helpful

Keep responses natural, helpful, and brief (1-2 sentences).
Speak like a real store employee would.""",

    'doctor-appointment': """You are Dr. Smith, a caring family doctor.
Your role:
- Ask about symptoms
- Listen to patient concerns
- Provide medical advice
- Explain diagnoses clearly
- Show empathy

Keep responses professional, caring, and brief (1-2 sentences).
Speak like a real doctor would.""",

    'bank-account': """You are a professional bank teller.
Your role:
- Help with account opening
- Request required documents
- Explain account types
- Answer banking questions
- Be professional and clear

Keep responses professional, clear, and brief (1-2 sentences).
Speak like a real bank teller would."""
}

class GeminiLiveConnection:
    def __init__(self, api_key: str, scenario: str, level: str):
        self.api_key = api_key
        self.scenario = scenario
        self.level = level
        self.ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self.session: Optional[aiohttp.ClientSession] = None
        
    async def connect(self):
        """Connect to Gemini Live API"""
        url = f"{GEMINI_LIVE_URL}?key={self.api_key}"
        self.session = aiohttp.ClientSession()
        
        try:
            self.ws = await self.session.ws_connect(url)
            logger.info("✅ Connected to Gemini Live API")
            
            # Send initial setup
            await self.setup_session()
            return True
        except Exception as e:
            logger.error(f"❌ Gemini Live connection failed: {e}")
            return False
    
    async def setup_session(self):
        """Setup Gemini Live session with system prompt"""
        system_prompt = SCENARIO_PROMPTS.get(self.scenario, "You are a helpful English teacher.")
        
        # Add level-specific instructions
        level_instructions = {
            'A1': "Use very simple words. Speak slowly and clearly. Use short sentences.",
            'A2': "Use simple everyday words. Speak clearly. Use basic sentences.",
            'B1': "Use common words. Speak at normal pace. Use clear sentences.",
            'B2': "Use natural language. Speak naturally. Use varied sentences.",
            'C1': "Use advanced vocabulary. Speak fluently. Use complex sentences.",
            'C2': "Use sophisticated language. Speak like a native. Use nuanced expressions."
        }
        
        full_prompt = f"{system_prompt}\n\nLanguage level: {self.level}. {level_instructions.get(self.level, '')}"
        
        setup_message = {
            "setup": {
                "model": "models/gemini-2.0-flash-exp",
                "generation_config": {
                    "response_modalities": ["AUDIO"],
                    "speech_config": {
                        "voice_config": {
                            "prebuilt_voice_config": {
                                "voice_name": "Aoede"  # Natural female voice
                            }
                        }
                    }
                },
                "system_instruction": {
                    "parts": [{"text": full_prompt}]
                }
            }
        }
        
        await self.ws.send_json(setup_message)
        logger.info(f"✅ Setup sent for scenario: {self.scenario}, level: {self.level}")
    
    async def send_audio(self, audio_data: str):
        """Send audio to Gemini"""
        message = {
            "realtime_input": {
                "media_chunks": [
                    {
                        "data": audio_data,
                        "mime_type": "audio/pcm"
                    }
                ]
            }
        }
        await self.ws.send_json(message)
    
    async def receive_messages(self):
        """Receive messages from Gemini"""
        async for msg in self.ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                data = json.loads(msg.data)
                yield data
            elif msg.type == aiohttp.WSMsgType.ERROR:
                logger.error(f"WebSocket error: {msg.data}")
                break
    
    async def close(self):
        """Close connection"""
        if self.ws:
            await self.ws.close()
        if self.session:
            await self.session.close()
        logger.info("🔌 Gemini Live connection closed")


@app.get("/")
async def root():
    return {
        "app": "EchoSpeak Live API",
        "version": "3.0.0",
        "gemini_live": "enabled",
        "gemini_configured": bool(GEMINI_API_KEY)
    }

@app.get("/health")
async def health():
    return {"status": "healthy", "gemini_live": bool(GEMINI_API_KEY)}

@app.websocket("/ws/conversation")
async def websocket_conversation(websocket: WebSocket):
    """WebSocket endpoint for real-time conversation"""
    await websocket.accept()
    logger.info("🔗 Client connected")
    
    gemini_conn: Optional[GeminiLiveConnection] = None
    
    try:
        # Wait for initial config from client
        initial_data = await websocket.receive_json()
        scenario = initial_data.get('scenario')
        level = initial_data.get('level', 'B1')
        
        logger.info(f"📝 Starting session: scenario={scenario}, level={level}")
        
        # Connect to Gemini Live
        gemini_conn = GeminiLiveConnection(GEMINI_API_KEY, scenario, level)
        connected = await gemini_conn.connect()
        
        if not connected:
            await websocket.send_json({
                "type": "error",
                "message": "Failed to connect to Gemini Live API"
            })
            return
        
        # Notify client ready
        await websocket.send_json({
            "type": "ready",
            "message": "Connected to Gemini Live"
        })
        
        # Create tasks for bidirectional streaming
        async def forward_to_gemini():
            """Forward audio from client to Gemini"""
            try:
                while True:
                    data = await websocket.receive_json()
                    
                    if data.get('type') == 'audio':
                        # Forward audio to Gemini
                        audio_data = data.get('data')
                        await gemini_conn.send_audio(audio_data)
                    
                    elif data.get('type') == 'end_turn':
                        # Signal end of user turn
                        logger.info("🔚 User turn ended")
                    
            except WebSocketDisconnect:
                logger.info("Client disconnected")
            except Exception as e:
                logger.error(f"Error forwarding to Gemini: {e}")
        
        async def forward_to_client():
            """Forward responses from Gemini to client"""
            try:
                async for response in gemini_conn.receive_messages():
                    # Parse Gemini response
                    if 'serverContent' in response:
                        server_content = response['serverContent']
                        
                        # Check for audio response
                        if 'modelTurn' in server_content:
                            model_turn = server_content['modelTurn']
                            
                            for part in model_turn.get('parts', []):
                                # Audio data
                                if 'inlineData' in part:
                                    audio_data = part['inlineData']['data']
                                    await websocket.send_json({
                                        "type": "audio",
                                        "data": audio_data
                                    })
                                
                                # Text transcript
                                if 'text' in part:
                                    text = part['text']
                                    await websocket.send_json({
                                        "type": "text",
                                        "text": text
                                    })
                        
                        # Check for turn complete
                        if server_content.get('turnComplete'):
                            await websocket.send_json({
                                "type": "turn_complete"
                            })
                    
            except Exception as e:
                logger.error(f"Error forwarding to client: {e}")
        
        # Run both tasks concurrently
        await asyncio.gather(
            forward_to_gemini(),
            forward_to_client()
        )
        
    except WebSocketDisconnect:
        logger.info("🔌 Client disconnected")
    except Exception as e:
        logger.error(f"❌ WebSocket error: {e}")
        await websocket.send_json({
            "type": "error",
            "message": str(e)
        })
    finally:
        if gemini_conn:
            await gemini_conn.close()

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
