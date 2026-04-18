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
        # get_ssid is a standalone function in api_quotex.login
        status, session_data = await get_ssid(email, password, is_demo=is_demo)
        ssid = session_data.get("ssid") if session_data else None
        
        if not status or not ssid:
            logger.error("❌ Falha ao capturar SSID. Verifique suas credenciais.")
            return

        logger.success(f"🔑 SSID Capturado com sucesso!")
        
        # Now connect to Render
        sio = socketio.AsyncClient()
        
        @sio.event
        async def connect():
            logger.success(f"📡 Conectado ao servidor Cloud: {render_url}")
            # Send the SSID to the cloud bridge
            logger.info("📤 Enviando chave de acesso para a nuvem...")
            await sio.emit('set_ssid', {"ssid": ssid, "is_demo": is_demo})
            await asyncio.sleep(2) # Give it a moment
            await sio.disconnect()

        @sio.event
        async def disconnect():
            logger.info("🔌 Desconectado do servidor Cloud.")

        try:
            await sio.connect(render_url, transports=['websocket', 'polling'])
            await sio.wait()
            logger.success("✅ Login concluído! Seu robô na nuvem já está operando.")
        except Exception as e:
            logger.error(f"❌ Erro ao conectar no Render: {e}")
            logger.warning("Verifique se a URL do Render está correta e se o servidor está online.")

    except Exception as e:
        logger.exception(f"Erro inesperado: {e}")

    input("\n[Pressione ENTER para fechar]")

if __name__ == "__main__":
    asyncio.run(main())
