import asyncio
import os
import time
from collections import deque
import socketio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

# --- Cérebro Ultra-Leve (Sem Pandas/Numpy para Deploy Relâmpago) ---
app = FastAPI(title="ProfitWave Cloud Emergency")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*')
combined_app = socketio.ASGIApp(sio, app)

@app.get("/")
async def root():
    return {"status": "ONLINE", "mode": "EMERGENCY_LIGHT", "time": time.time()}

@sio.event
async def connect(sid, environ):
    await sio.emit("server_status", {"status": "ONLINE", "type": "CLOUD"}, to=sid)
    await sio.emit("robot_state", {"state": "ANALYZING", "message": "Nuvem em Modo de Emergencia (Destravando...)"})

# Exportar como 'app' para compatibilidade total com qualquer comando de início
app_final = combined_app

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(combined_app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
