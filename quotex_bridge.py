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

# --- Character Encoding for Windows ---
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        # Older Python versions fallback
        import codecs
        sys.stdout = codecs.getwriter("utf-8")(sys.stdout.detach())
        sys.stderr = codecs.getwriter("utf-8")(sys.stderr.detach())

# --- Logging Setup ---
logger.add("profitwave_debug.log", rotation="100 MB", level="DEBUG", encoding="utf-8")

# --- Path Management ---
def setup_api_path():
    """Finds and adds the Quotex API parent directory to sys.path."""
    curr_dir = os.getcwd()
    # Try multiple potential locations for the API
    search_paths = [
        # 1. Absolute path provided by user
        r"c:\Users\Trader Academic\Downloads\API-Quotex-main\API-Quotex-main",
        # 2. Relative to current dir (sibling folder)
        os.path.join(os.path.dirname(curr_dir), "API-Quotex-main", "API-Quotex-main"),
        # 3. Same folder (if copied inside)
        os.path.join(curr_dir, "API-Quotex-main", "API-Quotex-main"),
        # 4. User Downloads folder
        os.path.join(os.path.expanduser("~"), "Downloads", "API-Quotex-main", "API-Quotex-main")
    ]
    
    for p in search_paths:
            try:
                if p not in sys.path:
                    sys.path.insert(0, p)
                from api_quotex import AsyncQuotexClient, websocket_client
                import api_quotex
                logger.success(f"✅ API Quotex carregada de: {api_quotex.__file__}")
                return True
            except Exception as e:
                logger.error(f"❌ Erro ao importar a API Quotex em {p}: {e}")
                import traceback
                logger.debug(traceback.format_exc())
                # If we found the directory but import failed for OTHER reasons (like missing deps),
                # we should probably tell the user instead of just continuing.
                if "api_quotex" in str(e):
                    continue
                return False
    return False

if not setup_api_path():
    logger.error("❌ Erro Crítico: Não encontrei a pasta 'api_quotex' em nenhum dos caminhos conhecidos.")
    logger.info("DICA: Certifique-se que o repositório 'API-Quotex-main' está na sua pasta Downloads.")
    sys.exit(1)

from api_quotex import AsyncQuotexClient


# --- Load Environment ---
load_dotenv()

# --- Config ---
HOST = "0.0.0.0"
PORT = 5001
PAYOUT_THRESHOLD = 80  # Target payout lowered to 80% to find more assets

# --- Socket.IO Setup ---
sio = socketio.AsyncServer(
    async_mode='asgi', 
    cors_allowed_origins='*', 
    logger=False, 
    engineio_logger=False,
    ping_timeout=20,
    ping_interval=10
)
app = FastAPI()
socket_app = socketio.ASGIApp(sio, app)

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
        self._scan_interval = 300  # Scan every 5 minutes
        self._last_signals = {}  # {asset: last_signal_time}
        self.is_locking_signal = False # Global signal lock
        self.timeframe = 1 # Default M1 (1 or 5)

    def calculate_rsi(self, prices: list, period=14):
        """Manual RSI implementation to avoid Pandas dependency issues on Windows."""
        if len(prices) < period + 1:
            return None
        
        try:
            rsi_values = []
            deltas = []
            for i in range(1, len(prices)):
                deltas.append(prices[i] - prices[i-1])
            
            gains = [d if d > 0 else 0 for d in deltas]
            losses = [-d if d < 0 else 0 for d in deltas]
            
            # Initial SMA gain/loss
            avg_gain = sum(gains[:period]) / period
            avg_loss = sum(losses[:period]) / period
            
            # First RSI value
            rs = avg_gain / avg_loss if avg_loss != 0 else 100
            rsi_values.append(100 - (100 / (1 + rs)))
            
            # Subsequent Wilders smoothing
            for i in range(period, len(deltas)):
                avg_gain = (avg_gain * (period - 1) + gains[i]) / period
                avg_loss = (avg_loss * (period - 1) + losses[i]) / period
                rs = avg_gain / avg_loss if avg_loss != 0 else 100
                rsi_values.append(100 - (100 / (1 + rs)))
            
            # Return as a custom class to support .iloc[-1] and .iloc[-2] syntax
            class RSIResult:
                def __init__(self, data): self.data = data
                @property
                def iloc(self): return self
                def __getitem__(self, idx): return self.data[idx]
            
            return RSIResult(rsi_values)
        except Exception as e:
            logger.error(f"❌ Erro no cálculo manual do RSI: {e}")
            return None

    def calculate_sma(self, prices, period):
        """Simple Moving Average."""
        if len(prices) < period: return None
        sma = []
        for i in range(period, len(prices) + 1):
            window = prices[i-period:i]
            sma.append(sum(window) / period)
        return sma

    def format_asset_name(self, raw_name):
        """EURUSD_otc -> EUR/USD (OTC)"""
        clean = raw_name.replace("_otc", "").replace("_OTC", "").replace("-OTC", "").replace("-otc", "")
        # Remove any leading hash or special characters
        clean = clean.replace("#", "")
        is_otc = "_otc" in raw_name.lower() or "-otc" in raw_name.lower()
        
        if len(clean) == 6:
            formatted = f"{clean[:3]}/{clean[3:]}"
        else:
            formatted = clean
        
        if is_otc:
            formatted += " (OTC)"
        return formatted.upper()

    def calculate_ema(self, prices, period):
        """Exponential Moving Average."""
        if len(prices) < period: return None
        ema = []
        alpha = 2 / (period + 1)
        
        # Start with SMA for the first EMA value
        initial_sma = sum(prices[:period]) / period
        ema.append(initial_sma)
        
        for i in range(period, len(prices)):
            current_ema = (prices[i] * alpha) + (ema[-1] * (1 - alpha))
            ema.append(current_ema)
        return ema

    def calculate_stdev(self, prices, period):
        """Standard Deviation."""
        if len(prices) < period: return None
        stdev = []
        for i in range(period, len(prices) + 1):
            window = prices[i-period:i]
            mean = sum(window) / period
            variance = sum((x - mean) ** 2 for x in window) / period
            stdev.append(variance ** 0.5)
        return stdev

    def calculate_stochastic(self, candles, k_period=14, d_period=3):
        """Stochastic Oscillator %K and %D."""
        if len(candles) < k_period + d_period: return None, None
        
        pk = []
        for i in range(k_period, len(candles) + 1):
            window = candles[i-k_period:i]
            low_min = min(c.low for c in window)
            high_max = max(c.high for c in window)
            current_close = window[-1].close
            
            if high_max - low_min == 0:
                pk.append(50)
            else:
                pk.append(100 * (current_close - low_min) / (high_max - low_min))
        
        # %D is SMA of %K
        pd = self.calculate_sma(pk, d_period)
        return pk, pd

    async def update_active_assets(self):
        """Finds the top available assets with payout >= PAYOUT_THRESHOLD."""
        try:
            payouts = await self.client.get_assets_and_payouts()
            if not payouts:
                logger.warning("⚠️ No payouts returned from broker.")
                return

            valid = []
            # Lista de moedas e commodities comuns para evitar nomes estranhos
            common_patterns = ["EUR", "USD", "GBP", "JPY", "AUD", "CAD", "CHF", "NZD", "GOLD", "SILVER", "XAU", "XAG", "BTC", "ETH"]
            
            for asset, payout in payouts.items():
                # Filter by payout
                if payout < PAYOUT_THRESHOLD:
                    continue
                
                # Filter by valid name patterns (avoiding indices or weird stocks it might not have)
                asset_upper = asset.upper()
                if not any(pat in asset_upper for pat in common_patterns):
                    continue
                
                # Avoid very long internal names
                if len(asset) > 15:
                    continue
                    
                valid.append((asset, payout))
            
            # Sort by payout descending and take top 15
            valid.sort(key=lambda x: x[1], reverse=True)
            self.active_assets = [x[0] for x in valid[:15]]
            
            if self.active_assets:
                logger.success(f"Scanner: Analisando {len(self.active_assets)} ativos (Payout >= {PAYOUT_THRESHOLD}%)")
            else:
                logger.warning(f"Aviso: Nenhuma moeda com payout >= {PAYOUT_THRESHOLD}% encontrada.")
                await sio.emit("robot_state", {"state": "ANALYZING", "asset": "Sem moedas >80%", "message": f"Aguardando lucro > {PAYOUT_THRESHOLD}%..."})
        except Exception as e:
            logger.error(f"❌ Error updating assets: {e}")

    def get_candle_color(self, candle):
        """Returns 'G' for green, 'R' for red, 'D' for doji."""
        if candle.close > candle.open: return "G"
        if candle.close < candle.open: return "R"
        return "D"

    async def wait_until_second(self, target_second):
        """Waits until the system clock hits the target second (ensures it waits for the NEXT occurrence)."""
        logger.debug(f"⏳ Waiting for second :{target_second:02d}...")
        
        # Se já estivermos no segundo alvo, esperamos sair dele primeiro
        # para garantir que pegaremos a PRÓXIMA virada.
        while self._running and datetime.now().second == target_second:
            await asyncio.sleep(0.1)
            
        while self._running:
            now = datetime.now()
            if now.second == target_second:
                break
            await asyncio.sleep(0.05)

    def is_signaling(self, asset):
        """Checks if an asset recently fired a signal (prevents spam)."""
        now = time.time()
        if asset in self._last_signals and (now - self._last_signals[asset]) < 180: # 3 min lock
            return True
        return False

    async def analyze_asset(self, asset):
        """Logic for a single asset analysis."""
        try:
            period_secs = self.timeframe * 60
            # Optimization: 150 candles for stable trend without long delays
            candles = await self.client.get_candles(asset, period_secs, count=150)
            if not candles or len(candles) < 110:
                return
            
            closes = [float(c.close) for c in candles]
            signal_type = None
            strategy_name = ""
            
            # --- CALCULATE CORE INDICATORS ---
            ema_trend = self.calculate_ema(closes, 100)
            ema9 = self.calculate_ema(closes, 9)
            ema21 = self.calculate_ema(closes, 21)
            rsi = self.calculate_rsi(closes, 14)
            
            if not (ema_trend and ema9 and ema21 and rsi):
                return

            last_close = closes[-1]
            last_ema_trend = ema_trend[-1]
            last_rsi = rsi.iloc[-1]
            
            # TREND FILTER (EMA 100)
            # Neutral zone: Price within 0.05% of EMA 100
            diff_pct = abs(last_close - last_ema_trend) / last_ema_trend
            is_neutral = diff_pct < 0.0005
            is_uptrend = last_close > last_ema_trend and not is_neutral
            is_downtrend = last_close < last_ema_trend and not is_neutral

            # --- 1. ESTRATÉGIA: TENDENCIA PREMIUM (EMA ALIGNMENT) ---
            # Very relaxed: Alignment + Price on the right side of EMA 21
            if (is_uptrend or is_neutral) and (ema9[-1] > ema21[-1]):
                if last_close > ema21[-1]: # Price must be above medium EMA
                    signal_type = "CALL"
                    strategy_name = "Tendencia Premium"
            elif (is_downtrend or is_neutral) and (ema9[-1] < ema21[-1]):
                if last_close < ema21[-1]:
                    signal_type = "PUT"
                    strategy_name = "Tendencia Premium"

            # --- 2. ESTRATÉGIA: EXAUSTAO ELITE (RSI + BOLLINGER) ---
            if not signal_type:
                sma20 = self.calculate_sma(closes, 20)
                std20 = self.calculate_stdev(closes, 20)
                if sma20 and std20:
                    upper = sma20[-1] + (2 * std20[-1])
                    lower = sma20[-1] - (2 * std20[-1])
                    
                    # COMPRA: (Tendencia Alta/Neutral + RSI < 52) OU (Reversao RSI < 38)
                    can_call = ((is_uptrend or is_neutral) and last_rsi < 52) or (last_rsi < 38)
                    if can_call and last_close <= (lower + (std20[-1] * 0.9)):
                        signal_type = "CALL"
                        strategy_name = "Exaustao Elite"
                    
                    # VENDA: (Tendencia Baixa/Neutral + RSI > 48) OU (Reversao RSI > 62)
                    can_put = ((is_downtrend or is_neutral) and last_rsi > 48) or (last_rsi > 62)
                    if not signal_type and can_put and last_close >= (upper - (std20[-1] * 0.9)):
                        signal_type = "PUT"
                        strategy_name = "Exaustao Elite"
                    
                    # Log near-misses for debug
                    if not signal_type:
                        if 30 <= last_rsi <= 70:
                            dist = abs(last_close-lower if last_rsi < 50 else last_close-upper)
                            logger.info(f"🔍 Avaliando {self.format_asset_name(asset)}: RSI {last_rsi:.1f} | Distância BB: {dist:.5f}")

            # --- 3. ESTRATÉGIA: PRICE ACTION CONFIRMADO (ENGOLFO + TREND) ---
            if not signal_type:
                prev = candles[-2]
                curr = candles[-1]
                # Engolfo de Alta
                if curr.close > curr.open and prev.close < prev.open and curr.close > prev.open:
                    # Plus some volume/size check would be nice, but let's keep it sensitive
                    signal_type = "CALL"
                    strategy_name = "Price Action Pro"
                # Engolfo de Baixa
                elif curr.close < curr.open and prev.close > prev.open and curr.close < prev.open:
                    signal_type = "PUT"
                    strategy_name = "Price Action Pro"

                # --- 4. ESTRATÉGIA: RÁPIDA SNIPER (SCALP RSI/STOCH) ---
                if not signal_type:
                    pk, pd = self.calculate_stochastic(candles, 9, 3)
                    if pk and pd:
                        # Extremos sem filtro de tendência para scalping
                        if pk[-1] < 20 and last_rsi < 38:
                            signal_type = "CALL"
                            strategy_name = "Rápida Sniper"
                        elif pk[-1] > 80 and last_rsi > 62:
                            signal_type = "PUT"
                            strategy_name = "Rápida Sniper"

            if signal_type:
                if self.is_signaling(asset):
                    return

                self._last_signals[asset] = time.time()
                self.current_state = "SIGNALING"
                
                formatted_asset = self.format_asset_name(asset)
                logger.success(f"SIGNAL: {strategy_name} | {signal_type} em {formatted_asset}")
                
                # Send Pre-alert (Formatted)
                await sio.emit("robot_state", {
                    "state": "PRE_ALERT", 
                    "asset": formatted_asset, 
                    "type": signal_type, 
                    "strategy": strategy_name,
                    "countdown": 15 if self.timeframe == 1 else 60,
                    "timeframe": self.timeframe,
                    "expiration": self.timeframe * 60
                })
                
                # We spawn a confirmation task
                asyncio.create_task(self.confirm_signal(asset, signal_type, strategy_name))
                return True
            
            return False

        except Exception as e:
            logger.error(f"Error analyzing {asset}: {e}")

    def _supabase_insert(self, record: dict) -> str:
        """Inserts a record into Supabase signals table. Returns the UUID."""
        try:
            url = f"{SUPABASE_URL}/rest/v1/signals"
            data = json.dumps(record).encode("utf-8")
            req = urllib.request.Request(url, data=data, headers=SUPABASE_HEADERS, method="POST")
            with urllib.request.urlopen(req, timeout=5) as resp:
                result = json.loads(resp.read().decode())
                if result and len(result) > 0:
                    return result[0].get("id", "")
        except Exception as e:
            logger.warning(f"[Supabase] Erro ao inserir sinal: {e}")
        return ""

    def _supabase_update(self, signal_id: str, result: str):
        """Updates the result (WIN/LOSS) of a signal in Supabase."""
        if not signal_id:
            return
        try:
            url = f"{SUPABASE_URL}/rest/v1/signals?id=eq.{signal_id}"
            now_iso = datetime.now(timezone.utc).isoformat()
            data = json.dumps({"result": result, "result_at": now_iso}).encode("utf-8")
            headers = {**SUPABASE_HEADERS, "Prefer": "return=minimal"}
            req = urllib.request.Request(url, data=data, headers=headers, method="PATCH")
            with urllib.request.urlopen(req, timeout=5) as resp:
                logger.info(f"[Supabase] Sinal {signal_id[:8]}... atualizado: {result}")
        except Exception as e:
            logger.warning(f"[Supabase] Erro ao atualizar resultado: {e}")

    async def confirm_signal(self, asset, signal_type, strategy_name):
        try:
            # High-Precision Wait until 00s (End of candle)
            await self.wait_until_second(0)
            
            now_time = datetime.now().strftime("%H:%M")
            formatted_asset = self.format_asset_name(asset)
            
            await sio.emit("robot_state", {
                "state": "CONFIRMED",
                "asset": formatted_asset,
                "type": signal_type,
                "strategy": strategy_name,
                "time": now_time,
                "expiration": self.timeframe * 60
            })
            
            # --- SALVAR SINAL NO SUPABASE ---
            supabase_id = self._supabase_insert({
                "asset": formatted_asset,
                "signal_type": signal_type,
                "strategy": strategy_name,
                "timeframe": self.timeframe,
                "expiration_secs": self.timeframe * 60,
                "result": "PENDING",
                "amount": 10
            })
            if supabase_id:
                logger.info(f"[Supabase] ✅ Sinal salvo — ID: {supabase_id[:8]}...")
            
            # --- AUTO TRADING BLOCK ---
            now_full = datetime.now().strftime("%H:%M:%S")
            logger.info(f"🚀 [ENTRADA] {now_full} | Ativo: {formatted_asset} | Expiração: {self.timeframe} min")
            
            amount = 10 # Default amount
            duration = self.timeframe * 60
            
            # Garantia de que a entrada ocorra na abertura da vela
            for attempt in range(2):
                try:
                    res = await self.client.entry_reais(asset, amount, signal_type, duration)
                    if res and res.get("status"):
                        logger.success(f"✅ Ordem aberta com sucesso: {res.get('id')}")
                        break
                    else:
                        logger.warning(f"⚠️ Falha na tentativa {attempt+1}: {res}")
                except Exception as e:
                    logger.error(f"❌ Erro ao enviar ordem: {e}")
                await asyncio.sleep(1)
            
            # Wait for the trade candles to close
            for _ in range(self.timeframe):
                await asyncio.sleep(10)
                await self.wait_until_second(0)
            
            # Now check for WIN/LOSS immediately (Turbo mode)
            asyncio.create_task(self.check_and_emit_result(asset, signal_type, supabase_id))
            
            # Keep locked for 5s more to show the result clearly
            await asyncio.sleep(5)
        except Exception as e:
            logger.error(f"Error in confirm_signal: {e}")
        finally:
            self.is_locking_signal = False
            self.current_state = "ANALYZING"

    async def check_and_emit_result(self, asset, signal_type, supabase_id: str = ""):
        """Fetches final candle data and determines if it was a WIN or LOSS."""
        try:
            # SINCRO DINÂMICA: Aguardar 5.5s para garantir que o Websocket da Quotex atualizou o histórico
            await asyncio.sleep(5.5)
            
            period_secs = self.timeframe * 60
            candles = await self.client.get_candles(asset, period_secs, count=10)
            if not candles: 
                logger.warning(f"⚠️ Could not fetch result candles for {asset}")
                return
            
            # The candle we want is the one that just closed.
            # Usually [-2] at 3.5s mark. Let's log it for audit.
            result_candle = candles[-2]
            
            open_price = float(result_candle.open)
            close_price = float(result_candle.close)
            candle_time = datetime.fromtimestamp(result_candle.time).strftime("%H:%M")
            
            is_win = False
            if signal_type == "CALL" and close_price > open_price:
                is_win = True
            elif signal_type == "PUT" and close_price < open_price:
                is_win = True
            
            result_state = "WIN" if is_win else "LOSS"
            formatted_asset = self.format_asset_name(asset)
            
            # Audit log for the user
            logger.info(f"📊 audit: [{formatted_asset}] {candle_time} | {signal_type} | Open: {open_price:.5f} -> Close: {close_price:.5f} | NEXT: {result_state}")
            
            await sio.emit("robot_state", {
                "state": result_state,
                "asset": formatted_asset,
                "type": signal_type
            })
            
            # --- ATUALIZAR RESULTADO NO SUPABASE (WIN/LOSS) ---
            if supabase_id:
                self._supabase_update(supabase_id, result_state)

        except Exception as e:
            logger.error(f"Error checking result: {e}")

    def calculate_next_scan_in(self, now_dt):
        s = now_dt.second
        if self.timeframe == 1: return (45 - s) if s < 45 else (105 - s)
        m_mod = now_dt.minute % 5
        if m_mod == 4 and s == 0: return 0
        return (3 - m_mod) * 60 + (60 - s) if m_mod < 4 else (299 + (60-s))

    async def analyze(self):
        """High-precision dispatcher loop (1s resolution)."""
        self._running = True
        logger.info("🚀 High-Precision Scanner Started")
        
        # Immediate feedback to frontend
        await sio.emit("robot_state", {"state": "ANALYZING", "asset": "Iniciando...", "message": "Iniciando scanner de alta precisão..."})
        
        while self._running:
            if not self.client.websocket_is_connected:
                await sio.emit("robot_state", {"state": "ANALYZING", "asset": "Sem Conexão", "message": "Aguardando WebSocket..."})
                await asyncio.sleep(2)
                continue

            # Update assets list every 5 min
            now_ts = time.time()
            if not self.active_assets or (now_ts - self._last_scan_time) > self._scan_interval:
                # Update assets
                await self.update_active_assets()
                # Use Top 15 assets for more volume
                if self.active_assets:
                    self.active_assets = self.active_assets[:15]
                self._last_scan_time = now_ts

            if not self.active_assets:
                # If we still have no assets, show a specific message and wait
                await sio.emit("robot_state", {"state": "ANALYZING", "asset": "Sem Moedas", "message": f"Nenhum par com payout >= {PAYOUT_THRESHOLD}%"})
                await asyncio.sleep(10)
                continue

            try:
                now_dt = datetime.now()
                second = now_dt.second
                
                # State display logic
                if not self.is_locking_signal:
                    self.current_state = "ANALYZING"
                    await sio.emit("robot_state", {
                        "state": "ANALYZING", 
                        "asset": "Analisando Mercado",
                        "assets_count": len(self.active_assets),
                        "message": f"Timeframe: M{self.timeframe}",
                        "next_scan_in": self.calculate_next_scan_in(now_dt),
                        "timeframe": self.timeframe,
                        "expiration": self.timeframe * 60
                    })

                # SIGNAL TRIGGER: M1 (at 45s) or M5 (at minute 4, 00s)
                trigger_time = False
                countdown_val = 15
                
                if self.timeframe == 1:
                    trigger_time = (second == 45)
                    countdown_val = 15
                else: # M5 - Trigger at 4m 00s (60s before)
                    trigger_time = (now_dt.minute % 5 == 4 and second == 0)
                    countdown_val = 60

                if trigger_time:
                    if self.is_locking_signal:
                        logger.info(f"⏳ {self.timeframe}m mark reached but system is LOCKED by active trade. Skipping scan.")
                    else:
                        logger.info(f"⏱️ {self.timeframe}m mark reached. Scanning {len(self.active_assets)} assets for signals...")
                        any_found = False
                        for asset in self.active_assets:
                            # Verify if asset had a signal in the last 150 candles
                            found = await self.analyze_asset(asset)
                            if found:
                                # Global lock: only one signal at a time
                                self.is_locking_signal = True
                                any_found = True
                                break
                        
                        if not any_found:
                            # Log every minute in M5 mode for peace of mind
                            if self.timeframe == 5 and second == 0:
                                logger.info(f"⏳ Monitorando Mercado M5... Próximo ciclo em {4 - (now_dt.minute % 5)}m")
                            elif self.timeframe == 1:
                                logger.info("📡 Scan completo: Nenhum sinal forte encontrado.")

                await asyncio.sleep(1) # Watch the clock every second
            except Exception as e:
                logger.error(f"High-precision scanner error: {e}")
                await asyncio.sleep(5)

    def signal_type_for_ui(self, signal):
        """Standardizes signal types for the frontend."""
        return "CALL" if signal == "CALL" else "PUT"

    def stop(self):
        self._running = False


analyzer: Optional[MarketAnalyzer] = None
analysis_task: Optional[asyncio.Task] = None
heartbeat_task: Optional[asyncio.Task] = None


# --- Events ---
@sio.event
async def connect(sid, environ):
    global is_broker_connected, captured_ssid
    logger.info(f"Frontend connected: {sid}")
    # Send current broker connection status
    await sio.emit("broker_status", {
        "connected": is_broker_connected,
        "ssid_captured": captured_ssid is not None
    })


@sio.event
async def capture_ssid(sid, data):
    """
    Opens a Playwright browser to qxbroker.com login page.
    Intercepts WebSocket frames to capture the SSID automatically
    when the user logs in manually.
    """
    global quotex_client, analyzer, analysis_task, heartbeat_task, captured_ssid, is_broker_connected
    
    logger.info("🌐 SSID capture requested. Launching browser...")
    await sio.emit("ssid_status", {"status": "LAUNCHING", "message": "Abrindo navegador..."})

    try:
        from playwright.async_api import async_playwright
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=False,
                args=[
                    "--start-maximized", 
                    "--disable-blink-features=AutomationControlled",
                    "--no-first-run",
                    "--no-default-browser-check"
                ]
            )
            context = await browser.new_context(
                viewport={"width": 1280, "height": 768},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = await context.new_page()
            
            found_ssid = None
            ssid_event = asyncio.Event()
            
            # Intercept WebSocket frames to capture the authorization message
            def on_ws_created(ws):
                logger.info(f"🔗 WebSocket opened: {ws.url}")
                
                def on_ws_frame_sent(payload):
                    nonlocal found_ssid
                    try:
                        text = payload if isinstance(payload, str) else payload.decode('utf-8', errors='ignore')
                        if '42["authorization",' in text:
                            found_ssid = text
                            logger.success(f"🔑 SSID CAPTURADO! ({text[:60]}...)")
                            ssid_event.set()
                    except Exception:
                        pass
                
                ws.on("framesent", on_ws_frame_sent)
            
            page.on("websocket", on_ws_created)
            
            # Navigate to Quotex login
            login_url = "https://qxbroker.com/pt/sign-in/"
            await sio.emit("ssid_status", {"status": "BROWSER_OPEN", "message": "Navegador aberto - faça o login na Quotex!"})
            
            try:
                await page.goto(login_url, wait_until="domcontentloaded", timeout=30000)
            except Exception as e:
                logger.warning(f"Navigation warning (continuing): {e}")
            
            logger.info("⏳ Waiting for user to log in and SSID to be captured...")
            await sio.emit("ssid_status", {"status": "WAITING_LOGIN", "message": "Aguardando seu login na Quotex..."})
            
            # Wait up to 5 minutes for the SSID to be captured via WebSocket interception
            try:
                await asyncio.wait_for(ssid_event.wait(), timeout=300)
            except asyncio.TimeoutError:
                logger.error("⏰ Timeout waiting for SSID capture")
                await sio.emit("ssid_status", {"status": "ERROR", "message": "Tempo esgotado (5 min). Tente novamente."})
                await browser.close()
                return
            
            if not found_ssid:
                await sio.emit("ssid_status", {"status": "ERROR", "message": "Não foi possível capturar o SSID."})
                await browser.close()
                return
            
            # SSID captured! Close browser and connect
            captured_ssid = found_ssid
            logger.success(f"✅ SSID captured successfully!")
            await sio.emit("ssid_status", {"status": "CAPTURED", "message": "SSID capturado! Conectando ao servidor..."})
            
            # Close the browser now - we have what we need
            await asyncio.sleep(1)
            await browser.close()
            
            # Now connect to Quotex with the captured SSID
            await _connect_with_ssid(captured_ssid)
                
    except Exception as e:
        logger.exception(f"SSID capture error: {e}")
        error_msg = str(e)
        if "playwright" in error_msg.lower():
            error_msg = "Erro no Playwright (navegador não encontrado ou bloqueado)."
        await sio.emit("ssid_status", {"status": "ERROR", "message": f"Erro: {error_msg}"})


async def _connect_with_ssid(ssid: str):
    """Connect to Quotex broker using a captured SSID and start analysis."""
    global quotex_client, analyzer, analysis_task, heartbeat_task, is_broker_connected
    
    await sio.emit("ssid_status", {"status": "CONNECTING", "message": "Conectando ao servidor Quotex..."})
    
    try:
        # Determine if demo from the SSID
        is_demo = True
        if '"isDemo":0' in ssid or '"isDemo": 0' in ssid:
            is_demo = False
        
        quotex_client = AsyncQuotexClient(
            ssid=ssid, 
            is_demo=is_demo,
            auto_reconnect=True,
            enable_logging=True
        )
        
        connected = await quotex_client.connect()
        
        if connected and quotex_client.websocket_is_connected:
            is_broker_connected = True
            logger.success("🟢 Connected to Quotex broker!")
            
            # Get balance info
            balance_info = ""
            try:
                balance = await quotex_client.get_balance()
                if balance:
                    balance_info = f" | Saldo: ${balance.amount:.2f}"
            except Exception:
                pass
            
            await sio.emit("ssid_status", {
                "status": "CONNECTED", 
                "message": f"Conectado à Quotex!{balance_info}"
            })
            await sio.emit("broker_status", {"connected": True, "ssid_captured": True})
            
            # Start market analyzer
            analyzer = MarketAnalyzer(quotex_client)
            
            # Start heartbeat
            async def heartbeat():
                while is_broker_connected:
                    await sio.emit("heartbeat", {"time": time.time()})
                    await asyncio.sleep(5)
            
            if heartbeat_task and not heartbeat_task.done():
                heartbeat_task.cancel()
            heartbeat_task = asyncio.create_task(heartbeat())
            
            logger.info("✅ Bridge fully operational. Waiting for AI activation.")
        else:
            is_broker_connected = False
            logger.error("❌ Failed to connect to Quotex WebSocket")
            await sio.emit("ssid_status", {"status": "ERROR", "message": "Falha na conexão WebSocket. SSID pode ter expirado."})
            await sio.emit("broker_status", {"connected": False, "ssid_captured": True})
            
    except Exception as e:
        is_broker_connected = False
        logger.exception(f"Connection error: {e}")
        await sio.emit("ssid_status", {"status": "ERROR", "message": f"Erro de conexão: {str(e)}"})
        await sio.emit("broker_status", {"connected": False, "ssid_captured": False})


@sio.event
async def disconnect(sid):
    logger.info(f"Frontend disconnected: {sid}")


# --- Socket Events for Dashboard Interaction ---
@sio.on('toggle_ai')
async def on_toggle_ai(sid, data):
    """Activates/Deactivates the Market Analyzer."""
    global analyzer, analysis_task, is_broker_connected
    active = data.get("active", False)
    timeframe = int(data.get("timeframe", 1))
    logger.info(f"🤖 AI toggle: {active} (Timeframe: M{timeframe})")
    
    if active and is_broker_connected and quotex_client:
        if not analyzer:
            analyzer = MarketAnalyzer(quotex_client)
        
        analyzer.timeframe = timeframe
        logger.info(f"⚙️ Configurando Analisador: Modo M{timeframe}")
        
        if not analysis_task or analysis_task.done():
            analysis_task = asyncio.create_task(analyzer.analyze())
            logger.info(f"🚀 Análise de Mercado INICIADA (Modo M{timeframe})!")
    elif not active:
        if analyzer:
            analyzer.stop()
        if analysis_task and not analysis_task.done():
            analysis_task.cancel()
            analysis_task = None
        logger.info("⏹️ Market analysis stopped.")

@sio.on('robot_state')
async def on_robot_state(sid, data):
    """Rebroadcast robot state for simulations/tests."""
    await sio.emit('robot_state', data)

@sio.on('confirmation')
async def on_confirmation(sid, data):
    """Rebroadcast confirmation for simulations/tests."""
    await sio.emit('confirmation', data)


async def check_playwright():
    try:
        logger.info("📡 Verificando drivers do Playwright...")
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "playwright", "install", "chromium",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        await proc.communicate()
        logger.success("✅ Drivers do navegador prontos.")
    except Exception as e:
        logger.warning(f"⚠️ Aviso ao instalar drivers: {e}")


if __name__ == "__main__":
    print("\n" + "="*55)
    print("    PROFITWAVE - BRIDGE v2.0 (SSID AUTO-CAPTURE)")
    print("="*55 + "\n")
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(check_playwright())
    
    config = Config(app=socket_app, host=HOST, port=PORT, log_level="info")
    server = Server(config)
    
    logger.info(f"🚀 Ponte iniciada em http://{HOST}:{PORT}")
    logger.info("Aguardando conexão do robô ProfitWave...")
    
    loop.run_until_complete(server.serve())
