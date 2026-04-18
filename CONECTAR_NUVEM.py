import asyncio
import json
import os
import sys
import socketio
from loguru import logger

# --- Path Management ---
# Add local directory to path to find api_quotex package
sys.path.append(os.getcwd())
try:
    from api_quotex.login import get_ssid
    # Add console sink back because api_quotex.login removes it
    logger.add(sys.stderr, format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{message}</cyan>", colorize=True)
    logger.success("✅ Biblioteca API Quotex localizada!")
except ImportError:
    logger.error("❌ Erro: api_quotex não encontrada. Rode este script na pasta do projeto.")
    sys.exit(1)

CONFIG_FILE = "config_nuvem.json"

def load_config():
    if not os.path.exists(CONFIG_FILE):
        return {"render_url": "https://profitwaver.onrender.com", "email": "", "password": "", "is_demo": True}
    with open(CONFIG_FILE, "r") as f:
        return json.load(f)

def save_config(config):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=4)

async def main():
    logger.info("🤖 Iniciando Assistente de Login Automático (ProfitWave Cloud)...")
    
    config = load_config()
    
    email = config.get("email")
    password = config.get("password")
    render_url = config.get("render_url")
    is_demo = config.get("is_demo", True)

    if not email:
        email = input("📧 Digite seu e-mail da Quotex: ")
        config["email"] = email
    if not password:
        password = input("🔑 Digite sua senha da Quotex: ")
        config["password"] = password
    
    save_config(config)

    logger.info("🌐 Abrindo navegador para capturar SSID...")
    try:
        status, session_data = await get_ssid(email, password) # Let it detect naturally
        ssid = session_data.get("ssid") if session_data else None
        
        if not status or not ssid:
            logger.error("❌ Falha ao capturar SSID. Verifique suas credenciais.")
            return

        # Detect is_demo from the SSID string internal JSON
        actual_is_demo = True
        if '"isDemo":0' in ssid:
            actual_is_demo = False
            logger.info("💎 Conta REAL detectada.")
        else:
            logger.info("🧪 Conta DEMO detectada.")

        logger.success(f"🔑 SSID Capturado com sucesso!")
        
        # Now connect to Render
        sio = socketio.AsyncClient()
        connection_finished = asyncio.Event()
        
        @sio.event
        async def connect():
            logger.success(f"📡 Conectado ao servidor Cloud: {render_url}")
            logger.info("📤 Enviando chave de acesso para a nuvem...")
            await sio.emit('set_ssid', {"ssid": ssid, "is_demo": actual_is_demo})

        @sio.on('ssid_status')
        async def on_ssid_status(data):
            status = data.get("status")
            message = data.get("message")
            if status == "CONNECTED":
                logger.success(f"✅ SERVIDOR CONFIRMOU: {message}")
                connection_finished.set()
            elif status == "ERROR":
                logger.error(f"❌ SERVIDOR REJEITOU: {message}")
                connection_finished.set()

        try:
            await sio.connect(render_url, transports=['websocket', 'polling'])
            # Wait for specific server response or 30s timeout
            try:
                await asyncio.wait_for(connection_finished.wait(), timeout=30)
            except asyncio.TimeoutError:
                logger.warning("⏳ Tempo esgotado esperando confirmação do servidor.")
            
            await sio.disconnect()
            logger.success("✅ Processo finalizado.")
        except Exception as e:
            logger.error(f"❌ Erro ao conectar no Render: {e}")

    except Exception as e:
        logger.exception(f"Erro inesperado: {e}")

    input("\n[Pressione ENTER para fechar]")

if __name__ == "__main__":
    asyncio.run(main())
