import asyncio
import json
import os
import sys
import time
from datetime import datetime
from typing import Optional
from collections import deque

import socketio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
import pandas as pd
import numpy as np

# --- Logs de Diagnóstico ---
log_buffer = deque(maxlen=100)
def log_sink(message):
    log_buffer.append(message.record["message"])
logger.add(log_sink)

# --- Mock Playwright (Evitar erro de build no Render) ---
class MockPlaywright:
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass
    @property
    def chromium(self): return self
    async def launch(self, **kwargs): return self
    async def new_context(self, **kwargs): return self
    async def new_page(self): return self
    async def goto(self, url, **kwargs): pass
    async def close(self): pass

sys.modules["playwright"] = type("obj", (), {"async_api": type("obj", (), {"async_playwright": MockPlaywright})})
sys.modules["playwright.async_api"] = type("obj", (), {"async_playwright": MockPlaywright})

# --- Carregamento da API Quotex ---
curr_dir = os.getcwd()
sys.path.append(os.path.join(curr_dir, "API-Quotex-main", "API-Quotex-main"))
try:
    from api_quotex.client import AsyncQuotexClient
    logger.info("✅ API Quotex carregada.")
except:
    logger.error("❌ Erro ao carregar API_QUOTEX.")

# --- Estado Global ---
HOST = "0.0.0.0"
PORT = int(os.environ.get("PORT", 8080))
quotex_client = None
is_broker_connected = False
analyzer = None
analysis_task = None

# --- Servidor e Socket ---
sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*', ping_timeout=60, ping_interval=25)
app = FastAPI(title="ProfitWave Cloud")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

@app.get("/")
async def root():
    return {"status": "ONLINE", "bot": "ProfitWave Cloud v3", "time": time.time()}

@app.get("/debug-logs")
async def get_debug_logs():
    return "\n".join(list(log_buffer))

# --- Inteligência Artificial (Simplificada para teste) ---
class CloudAnalyzer:
    def __init__(self, client):
        self.client = client
        self._running = False
        self.timeframe = 1
    
    async def analyze(self):
        self._running = True
        logger.info("🧠 IA Cloud Iniciada")
        while self._running:
            try:
                if not self.client or not self.client.websocket_is_connected:
                    await asyncio.sleep(2); continue
                
                await sio.emit("robot_state", {
                    "state": "ANALYZING", 
                    "message": "Nuvem Monitorando Mercado...",
                    "next_scan_in": 30
                })
                await asyncio.sleep(10)
            except: await asyncio.sleep(5)
    
    def stop(self): self._running = False

# --- Eventos Socket.IO ---
@sio.event
async def connect(sid, environ):
    global is_broker_connected, analyzer
    await sio.emit("server_status", {"status": "ONLINE", "type": "CLOUD"}, to=sid)
    if is_broker_connected:
        await sio.emit("broker_status", {"connected": True}, to=sid)
        if analyzer and analyzer._running:
            await sio.emit("robot_state", {"state": "ANALYZING"}, to=sid)

@sio.on('set_ssid')
async def on_set_ssid(sid, data):
    global quotex_client, is_broker_connected
    ssid, is_demo = data.get("ssid"), data.get("is_demo", True)
    try:
        quotex_client = AsyncQuotexClient(ssid=ssid, is_demo=is_demo)
        if await quotex_client.connect():
            is_broker_connected = True
            await sio.emit("broker_status", {"connected": True})
            logger.success("✅ Quotex Conectada via Nuvem!")
    except Exception as e:
        logger.error(f"Erro Conexão: {e}")

@sio.on('toggle_ai')
async def on_toggle_ai(sid, data):
    global analyzer, analysis_task, is_broker_connected
    active = data.get("active", False)
    if active and is_broker_connected:
        if not analyzer: analyzer = CloudAnalyzer(quotex_client)
        if not analysis_task or analysis_task.done():
            analysis_task = asyncio.create_task(analyzer.analyze())
    elif not active and analyzer:
        analyzer.stop()
        await sio.emit("robot_state", {"state": "IDLE"})

# --- Finalização da Ponte ---
combined_app = socketio.ASGIApp(sio, app)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(combined_app, host=HOST, port=PORT)
