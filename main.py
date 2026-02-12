"""
EchoSpeak Backend with Gemini API - FIXED VERSION
"""
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import os
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="EchoSpeak API", version="3.0.2")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

SCENARIO_PROMPTS = {
    'hotel-checkin': """You are a hotel front desk staff at Hilton Hotel.
Your role: YOU are the employee, USER is the guest.
Start: "Good evening! Welcome to Hilton Hotel. Do you have a reservation?"
Keep responses SHORT (1-2 sentences). Stay in character. Do NOT mention English practice.""",

    'restaurant': """You are a waiter at Olive Garden.
Your role: YOU are the waiter, USER is the customer.
Start: "Good evening! Welcome to Olive Garden. Table for how many?"
Keep responses SHORT. Stay in character. Do NOT mention language learning.""",

    'grocery-shopping': """You are a store employee.
Your role: YOU are the employee, USER is the customer.
Start: "Hi! Can I help you find something?"
Keep responses SHORT. Stay in character.""",

    'doctor-appointment': """You are Dr. Smith, a family doctor.
Your role: YOU are the doctor, USER is the patient.
Start: "Hello! I'm Dr. Smith. What brings you in today?"
Keep responses SHORT. Professional but warm.""",

    'bank-account': """You are a bank teller.
Your role: YOU are the teller, USER is the customer.
Start: "Good afternoon! How can I help you?"
Keep responses SHORT. Professional and clear."""
}

@app.get("/")
async def root():
    return {
        "app": "EchoSpeak API",
        "version": "3.0.2",
        "status": "running",
        "gemini_configured": bool(GEMINI_API_KEY)
    }

@app.get("/health")
async def health():
    return {"status": "healthy"}

@app.websocket("/ws/conversation")
async def websocket_conversation(websocket: WebSocket):
    await websocket.accept()
    logger.info("Client connected")
    
    try:
        config = await websocket.receive_json()
        scenario_id = config.get('scenario', 'hotel-checkin')
        level = config.get('level', 'B1')
        
        logger.info(f"Session: {scenario_id}, level: {level}")
        
        await websocket.send_json({"type": "ready"})
        
        greetings = {
            'hotel-checkin': "Good evening! Welcome to Hilton Hotel. Do you have a reservation?",
            'restaurant': "Good evening! Welcome to Olive Garden. Table for how many?",
            'grocery-shopping': "Hi there! Can I help you find something?",
            'doctor-appointment': "Hello! I'm Dr. Smith. What brings you in today?",
            'bank-account': "Good afternoon! How can I help you today?"
        }
        
        greeting = greetings.get(scenario_id, "Hello! How can I help?")
        
        await websocket.send_json({"type": "text", "text": greeting})
        await websocket.send_json({"type": "speak", "text": greeting})
        
        system_prompt = SCENARIO_PROMPTS.get(scenario_id, "")
        conversation = [{"role": "assistant", "content": greeting}]
        
        while True:
            data = await websocket.receive_json()
            
            if data.get('type') == 'text':
                user_text = data.get('text', '')
                logger.info(f"User: {user_text}")
                
                conversation.append({"role": "user", "content": user_text})
                
                try:
                    import google.generativeai as genai
                    genai.configure(api_key=GEMINI_API_KEY)
                    
                    model = genai.GenerativeModel('gemini-2.0-flash-exp')
                    
                    prompt = f"{system_prompt}\n\nConversation:\n"
                    for msg in conversation[-6:]:
                        role = "Customer" if msg['role'] == 'user' else "You"
                        prompt += f"{role}: {msg['content']}\n"
                    prompt += "\nYour response (1-2 sentences):"
                    
                    response = model.generate_content(prompt)
                    ai_text = response.text.strip()
                    
                    logger.info(f"AI: {ai_text}")
                    
                    conversation.append({"role": "assistant", "content": ai_text})
                    
                    await websocket.send_json({"type": "text", "text": ai_text})
                    await websocket.send_json({"type": "speak", "text": ai_text})
                    
                except Exception as e:
                    logger.error(f"Error: {e}")
                    fallback = "I see. Could you tell me more?"
                    await websocket.send_json({"type": "text", "text": fallback})
                    await websocket.send_json({"type": "speak", "text": fallback})
                
    except WebSocketDisconnect:
        logger.info("Client disconnected")
    except Exception as e:
        logger.error(f"Error: {e}")

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
