import asyncio
import os
import time
import socketio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

# --- Servidor Unificado (main.py para garantir o deploy) ---
app_fastapi = FastAPI(title="ProfitWave Root")
app_fastapi.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*')
app = socketio.ASGIApp(sio, other_asgi_app=app_fastapi)

@app_fastapi.get("/")
async def root():
    return {"status": "ONLINE", "bot": "ProfitWave v3.1", "msg": "SISTEMA OPERACIONAL"}

@app_fastapi.get("/debug-logs")
async def logs():
    return "Servidor em execução. Aguardando comandos..."

@sio.event
async def connect(sid, environ):
    await sio.emit("server_status", {"status": "ONLINE", "type": "CLOUD"}, to=sid)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
