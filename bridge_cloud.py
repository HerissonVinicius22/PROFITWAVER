import asyncio
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional

import socketio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
import pandas as pd
import numpy as np

# --- Mock Playwright (To avoid Render build errors) ---
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
    logger.success("✅ API Quotex carregada corretamente na Nuvem!")
except ImportError:
    # Try alternate path
    sys.path.append(os.path.join(curr_dir, "api_quotex"))
    try:
        from api_quotex.client import AsyncQuotexClient
        logger.success("✅ API Quotex carregada via path alternativo!")
    except:
        logger.critical("🆘 Falha ao carregar API_QUOTEX. O servidor não funcionará.")

# --- Config ---
HOST = "0.0.0.0"
PORT = int(os.environ.get("PORT", 8080))
PAYOUT_THRESHOLD = 80

# --- Supabase Config ---
SUPABASE_URL = "https://vzcixhgdvbnsumtxufto.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InZ6Y2l4aGdkdmJuc3VtdHh1ZnRvIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3NjQ2Njk2MCwiZXhwIjoyMDkyMDQyOTYwfQ.yC1sI6-3bairrP1savk-yH8Q_p7d5woeYlaG_KZQNcI"
SUPABASE_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation"
}

# --- Socket.IO Setup ---
sio = socketio.AsyncServer(
    async_mode='asgi', 
    cors_allowed_origins='*',
    ping_timeout=60,      # Aumentado para lidar com oscilações da rede
    ping_interval=25
)
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
socket_app = socketio.ASGIApp(sio, app)

# --- Global State ---
quotex_client: Optional[AsyncQuotexClient] = None
is_broker_connected = False

class CloudAnalyzer:
    """Robust Market Analyzer for Cloud (Ported from quotex_bridge.py)"""
    def __init__(self, client: AsyncQuotexClient):
        self.client = client
        self._running = False
        self.timeframe = 1
        self.active_assets = []
        self._last_scan_time = 0
        self._scan_interval = 300
        self._last_signals = {}
        self.is_locking_signal = False
        self.current_state = "IDLE"

    def calculate_ema(self, prices, period):
        return pd.Series(prices).ewm(span=period, adjust=False).mean().tolist()

    def calculate_sma(self, prices, period):
        return pd.Series(prices).rolling(window=period).mean().tolist()

    def calculate_rsi(self, prices, period=14):
        delta = pd.Series(prices).diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))

    def calculate_stochastic(self, candles, k_period=14, d_period=3):
        df = pd.DataFrame([{ "high": c.high, "low": c.low, "close": c.close } for c in candles])
        low_min = df["low"].rolling(window=k_period).min()
        high_max = df["high"].rolling(window=k_period).max()
        pk = 100 * (df["close"] - low_min) / (high_max - low_min)
        pd_val = pk.rolling(window=d_period).mean()
        return pk.tolist(), pd_val.tolist()

    def calculate_stdev(self, prices, period):
        return pd.Series(prices).rolling(window=period).std().tolist()

    def format_asset_name(self, raw_name):
        clean = raw_name.replace("_otc", "").replace("_OTC", "").replace("-OTC", "").replace("-otc", "").replace("#", "")
        is_otc = "_otc" in raw_name.lower() or "-otc" in raw_name.lower()
        formatted = f"{clean[:3]}/{clean[3:]}" if len(clean) == 6 else clean
        if is_otc: formatted += " (OTC)"
        return formatted.upper()

    async def update_active_assets(self):
        try:
            payouts = await self.client.get_assets_and_payouts()
            if not payouts: return
            valid = []
            for asset, payout in payouts.items():
                if payout >= PAYOUT_THRESHOLD and len(asset) <= 15:
                    valid.append((asset, payout))
            valid.sort(key=lambda x: x[1], reverse=True)
            self.active_assets = [x[0] for x in valid[:15]]
            logger.info(f"📊 Scanner Nuvem: {len(self.active_assets)} ativos encontrados.")
        except Exception as e:
            logger.error(f"Erro ao buscar ativos: {e}")

    async def analyze_asset(self, asset):
        try:
            period_secs = self.timeframe * 60
            candles = await self.client.get_candles(asset, period_secs, count=150)
            if not candles or len(candles) < 110: return False
            
            closes = [float(c.close) for c in candles]
            ema_trend = self.calculate_ema(closes, 100)
            ema9 = self.calculate_ema(closes, 9)
            ema21 = self.calculate_ema(closes, 21)
            rsi = self.calculate_rsi(closes, 14)
            
            last_close, last_trend, last_rsi = closes[-1], ema_trend[-1], rsi.iloc[-1]
            is_uptrend = last_close > last_trend
            is_downtrend = last_close < last_trend
            
            signal_type, strategy_name = None, ""

            # Strategy 1: Trend Premium
            if is_uptrend and ema9[-1] > ema21[-1] and last_close > ema21[-1]:
                signal_type, strategy_name = "CALL", "Tendencia Premium"
            elif is_downtrend and ema9[-1] < ema21[-1] and last_close < ema21[-1]:
                signal_type, strategy_name = "PUT", "Tendencia Premium"

            # Strategy 2: Exhaustion Elite
            if not signal_type:
                sma20 = self.calculate_sma(closes, 20)
                std20 = self.calculate_stdev(closes, 20)
                if sma20[-1] and std20[-1]:
                    upper = sma20[-1] + (2 * std20[-1])
                    lower = sma20[-1] - (2 * std20[-1])
                    if last_rsi < 38 and last_close <= (lower + (std20[-1] * 0.5)):
                        signal_type, strategy_name = "CALL", "Exaustao Elite"
                    elif last_rsi > 62 and last_close >= (upper - (std20[-1] * 0.5)):
                        signal_type, strategy_name = "PUT", "Exaustao Elite"

            if signal_type:
                now = time.time()
                if asset in self._last_signals and (now - self._last_signals[asset]) < 180: return False
                self._last_signals[asset] = now
                
                formatted = self.format_asset_name(asset)
                logger.success(f"🚀 SINAL NUVEM: {strategy_name} | {signal_type} em {formatted}")
                
                await sio.emit("robot_state", {
                    "state": "PRE_ALERT", "asset": formatted, "type": signal_type, 
                    "strategy": strategy_name, "countdown": 15 if self.timeframe == 1 else 60,
                    "expiration": self.timeframe * 60
                })
                
                asyncio.create_task(self.confirm_signal(asset, signal_type, strategy_name))
                return True
            return False
        except Exception as e:
            logger.error(f"Erro analisando {asset}: {e}")
            return False

    async def confirm_signal(self, asset, signal_type, strategy_name):
        try:
            self.is_locking_signal = True
            # Wait for candle close
            target_sec = 0
            while datetime.now().second != target_sec: await asyncio.sleep(0.1)
            
            formatted = self.format_asset_name(asset)
            await sio.emit("robot_state", {
                "state": "CONFIRMED", "asset": formatted, "type": signal_type,
                "strategy": strategy_name, "time": datetime.now().strftime("%H:%M"),
                "expiration": self.timeframe * 60
            })
            
            # --- SUPABASE LOG ---
            try:
                rec = {"asset": formatted, "signal_type": signal_type, "strategy": strategy_name, 
                       "timeframe": self.timeframe, "result": "PENDING", "amount": 10}
                req = urllib.request.Request(f"{SUPABASE_URL}/rest/v1/signals", 
                                             data=json.dumps(rec).encode(), headers=SUPABASE_HEADERS, method="POST")
                urllib.request.urlopen(req, timeout=5)
            except: pass

            # --- AUTO TRADE ---
            logger.info(f"💰 Executando entrada na Nuvem: {formatted} | {signal_type}")
            await self.client.entry_reais(asset, 10, signal_type, self.timeframe * 60)
            
            # Reset after some time
            await asyncio.sleep(30)
            self.is_locking_signal = False
        except Exception as e:
            logger.error(f"Erro na confirmação: {e}")
            self.is_locking_signal = False

    async def analyze(self):
        self._running = True
        logger.info("🧠 Cérebro Cloud Ativado!")
        while self._running:
            try:
                if not self.client.websocket_is_connected:
                    await asyncio.sleep(2); continue
                
                now = datetime.now()
                if not self.active_assets or (time.time() - self._last_scan_time) > self._scan_interval:
                    await self.update_active_assets()
                    self._last_scan_time = time.time()

                if not self.is_locking_signal:
                    await sio.emit("robot_state", {
                        "state": "ANALYZING", "asset": "Nuvem Monitorando", 
                        "message": f"Analisando {len(self.active_assets)} pares (M{self.timeframe})",
                        "next_scan_in": (45 - now.second) if now.second < 45 else (105 - now.second)
                    })

                if (self.timeframe == 1 and now.second == 45) or (self.timeframe == 5 and now.minute % 5 == 4 and now.second == 0):
                    for asset in self.active_assets:
                        if await self.analyze_asset(asset): break
                
                await asyncio.sleep(1)
            except Exception as e:
                logger.error(f"Erro no loop principal: {e}")
                await asyncio.sleep(5)

    def stop(self): self._running = False

# --- Persistence Helper ---
def save_session(ssid, is_demo):
    try:
        with open("session_cloud.json", "w") as f:
            json.dump({"ssid": ssid, "is_demo": is_demo}, f)
    except: pass

def load_session():
    try:
        if os.path.exists("session_cloud.json"):
            with open("session_cloud.json", "r") as f:
                return json.load(f)
    except: pass
    return None

@sio.event
async def connect(sid, environ):
    global is_broker_connected, analyzer
    logger.info(f"🌐 Site conectado: {sid}")
    
    # 1. Avisa que o servidor está Online
    await sio.emit("server_status", {"status": "ONLINE", "type": "CLOUD"}, to=sid)
    
    # 2. Se já estiver logado na Quotex, avisa o novo cliente
    if is_broker_connected:
        await sio.emit("broker_status", {"connected": True}, to=sid)
        await sio.emit("ssid_status", {"status": "CONNECTED", "message": "Nuvem Operacional!"}, to=sid)
        
        # 3. CRÍTICO: Se a IA já estiver analisando, avisa o site para mudar o texto de "DESLIGADA"
        if analyzer and analyzer._running:
            await sio.emit("robot_state", {
                "state": "ANALYZING", 
                "message": "Nuvem já estava operando!",
                "timeframe": analyzer.timeframe
            }, to=sid)
            logger.debug(f"📤 Sincronizado status ATIVO para o cliente {sid}")

@sio.on('set_ssid')
async def on_set_ssid(sid, data):
    global quotex_client, is_broker_connected
    ssid, is_demo = data.get("ssid"), data.get("is_demo", True)
    if not ssid: return
    
    # Salva para caso o servidor reinicie
    save_session(ssid, is_demo)
    
    try:
        if quotex_client: await quotex_client.disconnect()
        quotex_client = AsyncQuotexClient(ssid=ssid, is_demo=is_demo)
        if await quotex_client.connect():
            is_broker_connected = True
            await sio.emit("ssid_status", {"status": "CONNECTED", "message": "Nuvem Conectada!"})
            await sio.emit("broker_status", {"connected": True})
    except Exception as e: logger.error(f"Erro: {e}")

# --- State Refresh Loop ---
async def heartbeat_loop():
    while True:
        try:
            global is_broker_connected, analyzer
            # Mantém a conexão viva e sincronizada
            await sio.emit("server_status", {"status": "ONLINE", "type": "CLOUD", "time": time.time()})
            if is_broker_connected:
                await sio.emit("broker_status", {"connected": True})
                if analyzer and analyzer._running:
                    await sio.emit("robot_state", {"state": "ANALYZING", "message": "Nuvem em Monitoramento Ativo"})
        except: pass
        await asyncio.sleep(15)

# Autoreconnect on startup
@app.on_event("startup")
async def startup_event():
    asyncio.create_task(try_reconnect())
    asyncio.create_task(heartbeat_loop())

async def try_reconnect():
    global quotex_client, is_broker_connected
    session = load_session()
    if session:
        logger.info("reconnecting to previous session...")
        try:
            quotex_client = AsyncQuotexClient(ssid=session['ssid'], is_demo=session['is_demo'])
            if await quotex_client.connect():
                is_broker_connected = True
                logger.success("✅ Autoreconnect Cloud executado com sucesso!")
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
        await sio.emit("robot_state", {"state": "IDLE", "message": "IA Desligada"})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(socket_app, host=HOST, port=PORT)
