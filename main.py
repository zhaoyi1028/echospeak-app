import os
import asyncio
import json
import base64
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import google.generativeai as genai
import logging

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 配置 Gemini API
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY environment variable not set")

genai.configure(api_key=GEMINI_API_KEY)

# System Prompt - 酒店场景
HOTEL_SYSTEM_PROMPT = """You are a friendly and professional hotel receptionist at a luxury 5-star hotel. Your role is to:

1. Greet guests warmly and professionally
2. Help with check-in/check-out procedures
3. Answer questions about hotel facilities, room service, dining options, and local attractions
4. Handle reservations and special requests
5. Provide concierge services

Important guidelines:
- Always be polite, patient, and helpful
- Speak clearly and at a moderate pace
- Use professional but warm language
- Offer additional assistance proactively
- If you don't know something, offer to find out

Start by greeting the guest and asking how you can help them today."""

@app.get("/")
async def root():
    return {
        "status": "ok",
        "service": "EchoSpeak API",
        "version": "3.0.0",
        "features": {
            "gemini_live": "enabled",
            "scenario": "hotel_receptionist"
        }
    }

@app.get("/health")
async def health():
    return {"status": "healthy"}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    logger.info("WebSocket connection established")
    
    gemini_task = None
    
    try:
        # 创建 Gemini Live 客户端配置
        model = "models/gemini-2.0-flash-exp"
        config = {
            "generation_config": {
                "response_modalities": ["AUDIO"],
                "speech_config": {
                    "voice_config": {
                        "prebuilt_voice_config": {
                            "voice_name": "Aoede"
                        }
                    }
                }
            },
            "system_instruction": HOTEL_SYSTEM_PROMPT
        }
        
        # 连接到 Gemini Live API
        logger.info("Connecting to Gemini Live API...")
        client = genai.Client(api_key=GEMINI_API_KEY)
        
        async with client.aio.live.connect(model=model, config=config) as session:
            logger.info("Connected to Gemini Live API")
            
            # 发送连接成功消息
            await websocket.send_json({
                "type": "gemini_connected",
                "message": "Connected to Gemini Live"
            })
            
            # 创建任务来处理 Gemini 响应
            async def handle_gemini_responses():
                try:
                    async for response in session.receive():
                        logger.info(f"Received from Gemini: {type(response)}")
                        
                        # 处理服务器内容
                        if hasattr(response, 'server_content'):
                            server_content = response.server_content
                            
                            # 处理音频数据
                            if hasattr(server_content, 'model_turn'):
                                model_turn = server_content.model_turn
                                if hasattr(model_turn, 'parts'):
                                    for part in model_turn.parts:
                                        # 发送音频
                                        if hasattr(part, 'inline_data') and part.inline_data:
                                            audio_data = part.inline_data.data
                                            await websocket.send_json({
                                                "type": "audio",
                                                "data": base64.b64encode(audio_data).decode('utf-8'),
                                                "mime_type": part.inline_data.mime_type
                                            })
                                        
                                        # 发送文本
                                        if hasattr(part, 'text') and part.text:
                                            await websocket.send_json({
                                                "type": "text",
                                                "text": part.text
                                            })
                            
                            # 处理中断
                            if hasattr(server_content, 'turn_complete'):
                                await websocket.send_json({
                                    "type": "turn_complete"
                                })
                        
                        # 处理设置更新
                        if hasattr(response, 'setup_complete'):
                            logger.info("Setup complete")
                            await websocket.send_json({
                                "type": "setup_complete"
                            })
                
                except Exception as e:
                    logger.error(f"Error in Gemini response handler: {e}", exc_info=True)
                    try:
                        await websocket.send_json({
                            "type": "error",
                            "message": str(e)
                        })
                    except:
                        pass
            
            # 启动响应处理任务
            gemini_task = asyncio.create_task(handle_gemini_responses())
            
            # 处理来自客户端的消息
            try:
                while True:
                    message = await websocket.receive_text()
                    data = json.loads(message)
                    
                    msg_type = data.get("type")
                    logger.info(f"Received from client: {msg_type}")
                    
                    if msg_type == "audio":
                        # 转发音频到 Gemini
                        audio_b64 = data.get("data")
                        if audio_b64:
                            audio_bytes = base64.b64decode(audio_b64)
                            
                            # 发送音频数据到 Gemini
                            await session.send(
                                input={
                                    "mime_type": "audio/pcm",
                                    "data": audio_bytes
                                },
                                end_of_turn=False
                            )
                    
                    elif msg_type == "end_of_turn":
                        # 发送回合结束信号
                        await session.send(end_of_turn=True)
                    
                    elif msg_type == "interrupt":
                        # 中断当前回合
                        logger.info("Interrupting current turn")
            
            except WebSocketDisconnect:
                logger.info("Client disconnected")
            except Exception as e:
                logger.error(f"Error processing client message: {e}", exc_info=True)
    
    except Exception as e:
        logger.error(f"WebSocket error: {e}", exc_info=True)
        try:
            await websocket.send_json({
                "type": "error",
                "message": str(e)
            })
        except:
            pass
    
    finally:
        # 清理
        if gemini_task:
            gemini_task.cancel()
            try:
                await gemini_task
            except asyncio.CancelledError:
                pass
        
        logger.info("WebSocket connection closed")

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
