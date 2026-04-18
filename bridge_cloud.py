import asyncio
import json
import os
import sys
import time
import urllib.request
from datetime import datetime
from typing import Dict, List, Any, Optional
from collections import deque

import socketio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
import pandas as pd
import numpy as np

# --- Diagnostic Logs ---
log_buffer = deque(maxlen=100)
def log_sink(message):
    log_buffer.append(message.record["message"])
logger.add(log_sink)

# --- Mock Playwright ---
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

# --- Path Management ---
curr_dir = os.getcwd()
sys.path.append(os.path.join(curr_dir, "API-Quotex-main", "API-Quotex-main"))
try:
    from api_quotex.client import AsyncQuotexClient
    logger.info("✅ API Quotex carregada corretamente.")
except:
    logger.error("❌ Falha ao carregar API_QUOTEX.")

# --- Config ---
HOST = "0.0.0.0"
PORT = int(os.environ.get("PORT", 8080))
PAYOUT_THRESHOLD = 80
SUPABASE_URL = "https://vzcixhgdvbnsumtxufto.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InZ6Y2l4aGdkdmJuc3VtdHh1ZnRvIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImhhdCI6MTc3NjQ2Njk2MCwiZXhwIjoyMDkyMDQyOTYwfQ.yC1sI6-3bairrP1savk-yH8Q_p7d5woeYlaG_KZQNcI"
SUPABASE_HEADERS = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json"}

# --- Global State ---
quotex_client: Optional[AsyncQuotexClient] = None
is_broker_connected = False
analyzer = None
analysis_task = None

# --- Market Analyzer Class ---
class CloudAnalyzer:
    def __init__(self, client: AsyncQuotexClient):
        self.client = client
        self._running = False
        self.timeframe = 1
        self.active_assets = []
        self._last_scan_time = 0
        self._scan_interval = 300
        self._last_signals = {}
        self.is_locking_signal = False

    async def update_active_assets(self):
        try:
            payouts = await self.client.get_assets_and_payouts()
            if not payouts: return
            valid = [(a, p) for a, p in payouts.items() if p >= PAYOUT_THRESHOLD]
            valid.sort(key=lambda x: x[1], reverse=True)
            self.active_assets = [x[0] for x in valid[:15]]
            logger.info(f"Scanner: {len(self.active_assets)} ativos.")
        except: pass

    async def analyze(self):
        self._running = True
        logger.info("🧠 Cérebro Cloud: ON")
        while self._running:
            try:
                if not self.client.websocket_is_connected:
                    await asyncio.sleep(2); continue
                
                if not self.active_assets or (time.time() - self._last_scan_time) > self._scan_interval:
                    await self.update_active_assets()
                    self._last_scan_time = time.time()

                await sio.emit("robot_state", {"state": "ANALYZING", "message": f"Monitorando {len(self.active_assets)} pares"})
                await asyncio.sleep(10)
            except: await asyncio.sleep(5)

    def stop(self): self._running = False

# --- Socket.IO & FastAPI ---
sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*', ping_timeout=60, ping_interval=25)
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

@app.get("/")
async def root():
    return {"status": "ONLINE", "bot": "ProfitWave Cloud", "timestamp": time.time()}

@app.get("/debug-logs")
async def get_debug_logs():
    return "\n".join(list(log_buffer))

@sio.event
async def connect(sid, environ):
    global is_broker_connected, analyzer
    await sio.emit("server_status", {"status": "ONLINE", "type": "CLOUD"}, to=sid)
    if is_broker_connected:
        await sio.emit("broker_status", {"connected": True}, to=sid)
        if analyzer and analyzer._running:
            await sio.emit("robot_state", {"state": "ANALYZING", "message": "IA em Monitoramento Ativo"}, to=sid)

@sio.on('set_ssid')
async def on_set_ssid(sid, data):
    global quotex_client, is_broker_connected
    ssid, is_demo = data.get("ssid"), data.get("is_demo", True)
    if not ssid: return
    try:
        quotex_client = AsyncQuotexClient(ssid=ssid, is_demo=is_demo)
        if await quotex_client.connect():
            is_broker_connected = True
            await sio.emit("broker_status", {"connected": True})
            logger.success("✅ Quotex Conectada!")
    except: pass

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

# IMPORTANTE: A variável 'app' deve ser o socket_app final para o uvicorn identificar
app = socketio.ASGIApp(sio, app)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT)
