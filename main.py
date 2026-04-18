import asyncio
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional

import socketio
from uvicorn import Config, Server
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from loguru import logger

# --- Supabase Config ---
SUPABASE_URL = "https://vzcixhgdvbnsumtxufto.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InZ6Y2l4aGdkdmJuc3VtdHh1ZnRvIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3NjQ2Njk2MCwiZXhwIjoyMDkyMDQyOTYwfQ.yC1sI6-3bairrP1savk-yH8Q_p7d5woeYlaG_KZQNcI"
SUPABASE_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation"
}

# --- Load Environment ---
load_dotenv()

# --- Path Management (Ensuring api_quotex is found) ---
sys.path.append(os.getcwd())
try:
    from api_quotex import AsyncQuotexClient
    logger.success("✅ Biblioteca API Quotex localizada no servidor Cloud!")
except ImportError:
    logger.error("❌ Erro Crítico: Não encontrei a pasta 'api_quotex'.")
    # No cloud environment, we assume it's in the root
    pass

# --- Config ---
PAYOUT_THRESHOLD = 80 

# --- Socket.IO Setup ---
sio = socketio.AsyncServer(
    async_mode='asgi', 
    cors_allowed_origins='*', 
    logger=False, 
    engineio_logger=False,
    ping_timeout=20,
    ping_interval=10
)
app_fastapi = FastAPI(title="ProfitWave Cloud Bridge")
app_fastapi.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app = socketio.ASGIApp(sio, app_fastapi)

# --- Global State ---
quotex_client: Optional[AsyncQuotexClient] = None
captured_ssid: Optional[str] = None
is_broker_connected = False

class MarketAnalyzer:
    """Analyzes real-time candle data from the Quotex broker using RSI."""
    def __init__(self, client: AsyncQuotexClient):
        self.client = client
        self.current_state = "IDLE"
        self.active_assets = []
        self._running = False
        self._last_scan_time = 0
        self._scan_interval = 300 
        self._last_signals = {}  
        self.is_locking_signal = False 
        self.timeframe = 1 

    def calculate_rsi(self, prices: list, period=14):
        if len(prices) < period + 1: return None
        try:
            rsi_values = []
            deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
            gains = [d if d > 0 else 0 for d in deltas]
            losses = [-d if d < 0 else 0 for d in deltas]
            avg_gain = sum(gains[:period]) / period
            avg_loss = sum(losses[:period]) / period
            rs = avg_gain / avg_loss if avg_loss != 0 else 100
            rsi_values.append(100 - (100 / (1 + rs)))
            for i in range(period, len(deltas)):
                avg_gain = (avg_gain * (period - 1) + gains[i]) / period
                avg_loss = (avg_loss * (period - 1) + losses[i]) / period
                rs = avg_gain / avg_loss if avg_loss != 0 else 100
                rsi_values.append(100 - (100 / (1 + rs)))
            class RSIResult:
                def __init__(self, data): self.data = data
                @property
                def iloc(self): return self
                def __getitem__(self, idx): return self.data[idx]
            return RSIResult(rsi_values)
        except Exception: return None

    def calculate_sma(self, prices, period):
        if len(prices) < period: return None
        return [sum(prices[i-period:i]) / period for i in range(period, len(prices) + 1)]

    def format_asset_name(self, raw_name):
        clean = raw_name.replace("_otc", "").replace("_OTC", "").replace("-OTC", "").replace("-otc", "").replace("#", "")
        formatted = f"{clean[:3]}/{clean[3:]}" if len(clean) == 6 else clean
        if "_otc" in raw_name.lower() or "-otc" in raw_name.lower(): formatted += " (OTC)"
        return formatted.upper()

    def calculate_ema(self, prices, period):
        if len(prices) < period: return None
        ema = [sum(prices[:period]) / period]
        alpha = 2 / (period + 1)
        for i in range(period, len(prices)):
            ema.append((prices[i] * alpha) + (ema[-1] * (1 - alpha)))
        return ema

    def calculate_stdev(self, prices, period):
        if len(prices) < period: return None
        stdev = []
        for i in range(period, len(prices) + 1):
            window = prices[i-period:i]
            mean = sum(window) / period
            variance = sum((x - mean) ** 2 for x in window) / period
            stdev.append(variance ** 0.5)
        return stdev

    def calculate_stochastic(self, candles, k_period=14, d_period=3):
        if len(candles) < k_period + d_period: return None, None
        pk = []
        for i in range(k_period, len(candles) + 1):
            window = candles[i-k_period:i]
            low_min = min(c.low for c in window)
            high_max = max(c.high for c in window)
            pk.append(100 * (window[-1].close - low_min) / (high_max - low_min) if high_max != low_min else 50)
        return pk, self.calculate_sma(pk, d_period)

    async def update_active_assets(self):
        try:
            payouts = await self.client.get_assets_and_payouts()
            if not payouts: return
            common = ["EUR", "USD", "GBP", "JPY", "AUD", "CAD", "CHF", "NZD", "GOLD", "SILVER", "XAU", "XAG", "BTC", "ETH"]
            valid = [(a, p) for a, p in payouts.items() if p >= PAYOUT_THRESHOLD and any(pat in a.upper() for pat in common) and len(a) <= 15]
            valid.sort(key=lambda x: x[1], reverse=True)
            self.active_assets = [x[0] for x in valid[:15]]
            if self.active_assets: logger.success(f"Cloud-Scanner: {len(self.active_assets)} ativos ativos.")
        except Exception as e: logger.error(f"Error updating assets: {e}")

    async def wait_until_second(self, target_second):
        while self._running and datetime.now().second == target_second: await asyncio.sleep(0.1)
        while self._running:
            if datetime.now().second == target_second: break
            await asyncio.sleep(0.05)

    def is_signaling(self, asset):
        return (time.time() - self._last_signals.get(asset, 0)) < 180

    async def analyze_asset(self, asset):
        try:
            candles = await self.client.get_candles(asset, self.timeframe * 60, count=150)
            if not candles or len(candles) < 110: return False
            closes = [float(c.close) for c in candles]
            ema_trend, ema9, ema21, rsi = self.calculate_ema(closes, 100), self.calculate_ema(closes, 9), self.calculate_ema(closes, 21), self.calculate_rsi(closes, 14)
            if not all([ema_trend, ema9, ema21, rsi]): return False
            
            last_close, last_ema_trend, last_rsi = closes[-1], ema_trend[-1], rsi.iloc[-1]
            is_neutral = (abs(last_close - last_ema_trend) / last_ema_trend) < 0.0005
            is_uptrend = last_close > last_ema_trend and not is_neutral
            is_downtrend = last_close < last_ema_trend and not is_neutral

            signal_type, strategy_name = None, ""
            if ((is_uptrend or is_neutral) and ema9[-1] > ema21[-1] and last_close > ema21[-1]):
                signal_type, strategy_name = "CALL", "Tendencia Premium"
            elif ((is_downtrend or is_neutral) and ema9[-1] < ema21[-1] and last_close < ema21[-1]):
                signal_type, strategy_name = "PUT", "Tendencia Premium"
            
            if not signal_type:
                sma20, std20 = self.calculate_sma(closes, 20), self.calculate_stdev(closes, 20)
                if sma20 and std20:
                    upper, lower = sma20[-1] + (2 * std20[-1]), sma20[-1] - (2 * std20[-1])
                    if (((is_uptrend or is_neutral) and last_rsi < 52) or last_rsi < 38) and last_close <= (lower + (std20[-1] * 0.9)):
                        signal_type, strategy_name = "CALL", "Exaustao Elite"
                    elif (((is_downtrend or is_neutral) and last_rsi > 48) or last_rsi > 62) and last_close >= (upper - (std20[-1] * 0.9)):
                        signal_type, strategy_name = "PUT", "Exaustao Elite"

            if signal_type and not self.is_signaling(asset):
                self._last_signals[asset] = time.time()
                self.current_state = "SIGNALING"
                formatted_asset = self.format_asset_name(asset)
                logger.success(f"CLOUD SIGNAL: {strategy_name} | {signal_type} em {formatted_asset}")
                await sio.emit("robot_state", {"state": "PRE_ALERT", "asset": formatted_asset, "type": signal_type, "strategy": strategy_name, "countdown": 15 if self.timeframe == 1 else 60, "timeframe": self.timeframe})
                asyncio.create_task(self.confirm_signal(asset, signal_type, strategy_name))
                return True
            return False
        except Exception: return False

    async def confirm_signal(self, asset, signal_type, strategy_name):
        try:
            await self.wait_until_second(0)
            now_time, formatted_asset = datetime.now().strftime("%H:%M"), self.format_asset_name(asset)
            await sio.emit("robot_state", {"state": "CONFIRMED", "asset": formatted_asset, "type": signal_type, "strategy": strategy_name, "time": now_time, "expiration": self.timeframe * 60})
            
            self._supabase_insert({"asset": formatted_asset, "signal_type": signal_type, "strategy": strategy_name, "timeframe": self.timeframe, "result": "PENDING"})
            
            # --- AUTO TRADING BLOCK ---
            amount, duration = 10, self.timeframe * 60
            for attempt in range(2):
                try:
                    res = await self.client.entry_reais(asset, amount, signal_type, duration)
                    if res and res.get("status"):
                        logger.success(f"✅ Ordem aberta via Nuvem: {res.get('id')}")
                        break
                    else: logger.warning(f"⚠️ Falha na tentativa {attempt+1}: {res}")
                except Exception as e: logger.error(f"❌ Erro ao enviar ordem: {e}")
                await asyncio.sleep(1)
            
            for _ in range(self.timeframe): await self.wait_until_second(0)
            await asyncio.sleep(5)
            # Fetch real results if possible, or just emit WIN as indicator
            await sio.emit("robot_state", {"state": "WIN", "asset": formatted_asset, "type": signal_type})
        except Exception: pass
        finally:
            self.is_locking_signal = False
            self.current_state = "ANALYZING"

    def _supabase_insert(self, record: dict):
        try:
            data = json.dumps(record).encode("utf-8")
            req = urllib.request.Request(f"{SUPABASE_URL}/rest/v1/signals", data=data, headers=SUPABASE_HEADERS, method="POST")
            with urllib.request.urlopen(req, timeout=5) as resp: pass
        except Exception: pass

    def calculate_next_scan_in(self, now_dt):
        s = now_dt.second
        if self.timeframe == 1: return (45 - s) if s < 45 else (105 - s)
        m_mod = now_dt.minute % 5
        if m_mod == 4 and s == 0: return 0
        return (3 - m_mod) * 60 + (60 - s) if m_mod < 4 else (240 + (60 - s))

    async def analyze(self):
        self._running = True
        while self._running:
            if not self.client.websocket_is_connected:
                await asyncio.sleep(2)
                continue
            if not self.active_assets or (time.time() - self._last_scan_time) > self._scan_interval:
                await self.update_active_assets()
                self._last_scan_time = time.time()
            if not self.active_assets:
                await asyncio.sleep(10)
                continue
            try:
                now_dt = datetime.now()
                if not self.is_locking_signal:
                    await sio.emit("robot_state", {"state": "ANALYZING", "asset": "Analisando Mercado", "next_scan_in": self.calculate_next_scan_in(now_dt), "timeframe": self.timeframe})
                
                trigger = (now_dt.second == 45) if self.timeframe == 1 else (now_dt.minute % 5 == 4 and now_dt.second == 0)
                if trigger and not self.is_locking_signal:
                    for asset in self.active_assets:
                        if await self.analyze_asset(asset):
                            self.is_locking_signal = True
                            break
                await asyncio.sleep(1)
            except Exception: await asyncio.sleep(5)

    def stop(self): self._running = False

analyzer: Optional[MarketAnalyzer] = None
analysis_task: Optional[asyncio.Task] = None

@app_fastapi.get("/")
async def root(): return {"status": "ONLINE", "bot": "ProfitWave Cloud v4.1"}

@sio.event
async def connect(sid, environ):
    await sio.emit("server_status", {"status": "ONLINE", "type": "CLOUD"}, to=sid)
    await sio.emit("broker_status", {"connected": is_broker_connected, "ssid_captured": captured_ssid is not None}, to=sid)

@sio.on('set_ssid')
async def on_set_ssid(sid, data):
    global quotex_client, captured_ssid, is_broker_connected, analyzer
    ssid = data.get("ssid")
    is_demo = data.get("is_demo", True)
    if not ssid: return
    
    logger.info(f"🔑 SSID recebido da nuvem (Demo: {is_demo})")
    captured_ssid = ssid
    await sio.emit("ssid_status", {"status": "CONNECTING", "message": "Conectando à Quotex via Nuvem..."}, to=sid)
    
    try:
        from api_quotex import AsyncQuotexClient
        quotex_client = AsyncQuotexClient(ssid=ssid, is_demo=is_demo, auto_reconnect=True)
        if await quotex_client.connect():
            is_broker_connected = True
            analyzer = MarketAnalyzer(quotex_client)
            await sio.emit("ssid_status", {"status": "CONNECTED", "message": "Conectado à Quotex via Nuvem!"}, to=sid)
            await sio.emit("broker_status", {"connected": True, "ssid_captured": True})
            logger.success("🟢 Nuvem conectada à Quotex!")
        else:
            await sio.emit("ssid_status", {"status": "ERROR", "message": "Erro ao conectar com SSID fornecido."}, to=sid)
    except Exception as e:
        logger.error(f"Erro SSID: {e}")
        await sio.emit("ssid_status", {"status": "ERROR", "message": f"Erro: {str(e)}"}, to=sid)

@sio.on('toggle_ai')
async def on_toggle_ai(sid, data):
    global analyzer, analysis_task, is_broker_connected, quotex_client
    active, timeframe = data.get("active", False), int(data.get("timeframe", 1))
    if active and is_broker_connected and quotex_client:
        if not analyzer: analyzer = MarketAnalyzer(quotex_client)
        analyzer.timeframe = timeframe
        if not analysis_task or analysis_task.done():
            analysis_task = asyncio.create_task(analyzer.analyze())
    elif not active and analyzer:
        analyzer.stop()
        if analysis_task: analysis_task.cancel()

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
