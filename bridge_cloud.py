import asyncio
import json
import os
import sys
import time
from typing import Dict, List, Any, Optional

import socketio
from uvicorn import Config, Server
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

# --- Supabase Config (Same as bridge) ---
SUPABASE_URL = "https://vzcixhgdvbnsumtxufto.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InZ6Y2l4aGdkdmJuc3VtdHh1ZnRvIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3NjQ2Njk2MCwiZXhwIjoyMDkyMDQyOTYwfQ.yC1sI6-3bairrP1savk-yH8Q_p7d5woeYlaG_KZQNcI"

# --- Mock Playwright to avoid heavy dependencies on Cloud ---
import sys
from types import ModuleType
mock_playwright = ModuleType("playwright")
mock_playwright_async = ModuleType("playwright.async_api")
mock_playwright_async.async_playwright = None
mock_playwright_async.TimeoutError = Exception
sys.modules["playwright"] = mock_playwright
sys.modules["playwright.async_api"] = mock_playwright_async

# --- Path Management for Cloud ---
sys.path.append(os.getcwd())

AsyncQuotexClient = None

try:
    from api_quotex.client import AsyncQuotexClient
    logger.success("✅ API Quotex carregada via api_quotex.client!")
except ImportError as e:
    logger.warning(f"⚠️ Falha no import inicial: {e}")
    try:
        from api_quotex import AsyncQuotexClient
        logger.success("✅ API Quotex carregada via api_quotex raiz!")
    except ImportError as e2:
        logger.error(f"❌ Erro Crítico de Importação: {e2}")
        # Debug: list directory
        try:
            logger.debug(f"Diretório atual: {os.getcwd()}")
            logger.debug(f"Arquivos na raiz: {os.listdir('.')}")
            if os.path.exists('api_quotex'):
                logger.debug(f"Conteúdo de api_quotex: {os.listdir('api_quotex')}")
        except: pass
        
        # Try one last resort for the nested folder structure
        sys.path.append(os.path.join(os.getcwd(), "API-Quotex-main", "API-Quotex-main"))
        try:
            from api_quotex.client import AsyncQuotexClient
            logger.success("✅ API Quotex carregada via fallback de subdiretório!")
        except ImportError:
            logger.critical("🆘 Falha total ao carregar a biblioteca. O servidor não funcionará corretamente.")

# --- Config ---
HOST = "0.0.0.0"
PORT = int(os.environ.get("PORT", 8080)) # Render uses PORT env var

# --- Socket.IO Setup ---
sio = socketio.AsyncServer(
    async_mode='asgi', 
    cors_allowed_origins='*', 
    logger=False, 
    engineio_logger=False
)
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
socket_app = socketio.ASGIApp(sio, app)

# --- Global State ---
quotex_client: Optional[AsyncQuotexClient] = None
is_broker_connected = False
analyzer = None
analysis_task = None

class CloudAnalyzer:
    """Simplified Market Analyzer for Cloud (No GUI dependencies)"""
    def __init__(self, client: AsyncQuotexClient):
        self.client = client
        self._running = False
        self.timeframe = 1

    async def analyze(self):
        self._running = True
        logger.info(f"🚀 Iniciando análise em nuvem (M{self.timeframe})...")
        while self._running:
            try:
                # Basic market scan logic (simplified from main bridge)
                # This would call the same API methods as the local version
                assets = await self.client.get_assets_and_payouts()
                high_payouts = {k: v for k, v in assets.items() if v >= 80}
                
                if high_payouts:
                    for asset, payout in list(high_payouts.items())[:3]: # Limit scan for cloud resources
                        logger.info(f"📊 Analisando {asset} ({payout}%)")
                        # Emitting fake signals for testing if needed
                        # In production, this would use the RSI/SMA logic
                
                await asyncio.sleep(60)
            except Exception as e:
                logger.error(f"Erro na análise: {e}")
                await asyncio.sleep(10)

    def stop(self):
        self._running = False

@sio.event
async def connect(sid, environ):
    logger.info(f"🌐 Site conectado: {sid}")
    await sio.emit("server_status", {"status": "ONLINE", "type": "CLOUD"})

@sio.on('set_ssid')
async def on_set_ssid(sid, data):
    """Event to receive SSID manually from the site."""
    global quotex_client, is_broker_connected, analyzer
    ssid = data.get("ssid")
    is_demo = data.get("is_demo", True)
    
    if not ssid:
        return await sio.emit("ssid_status", {"status": "ERROR", "message": "SSID inválido"})

    logger.info(f"🔑 Novo SSID recebido. Conectando... (Demo: {is_demo})")
    
    try:
        if quotex_client:
            await quotex_client.disconnect()

        quotex_client = AsyncQuotexClient(ssid=ssid, is_demo=is_demo)
        connected = await quotex_client.connect()
        
        if connected:
            is_broker_connected = True
            logger.success("🟢 Conectado à Quotex via Nuvem!")
            await sio.emit("ssid_status", {"status": "CONNECTED", "message": "Conectado à Quotex via Nuvem!"})
            await sio.emit("broker_status", {"connected": True})
        else:
            await sio.emit("ssid_status", {"status": "ERROR", "message": "Falha ao conectar WebSocket"})
    except Exception as e:
        logger.error(f"Erro de conexão: {e}")
        await sio.emit("ssid_status", {"status": "ERROR", "message": str(e)})

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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(socket_app, host=HOST, port=PORT)
