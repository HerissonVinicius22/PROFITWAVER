"""
Script que inicia o ngrok e exibe a URL pública para configurar no Vercel.
Execute ANTES do App se comportar corretamente no celular/vercel.
"""
import subprocess
import time
import urllib.request
import json
import sys
import os

BRIDGE_PORT = 5001

print("=" * 55)
print("  PROFITWAVER — Expositor de Ponte (ngrok)")
print("=" * 55)
print()
print("⏳ Iniciando ngrok na porta 5001...")

# Inicia ngrok em background
ngrok_proc = subprocess.Popen(
    ["ngrok", "http", str(BRIDGE_PORT), "--log", "stdout"],
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL
)

# Aguarda ngrok iniciar
time.sleep(3)

# Busca a URL pública via API local do ngrok
public_url = None
for attempt in range(10):
    try:
        req = urllib.request.Request("http://127.0.0.1:4040/api/tunnels")
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode())
            tunnels = data.get("tunnels", [])
            for t in tunnels:
                if t.get("proto") == "https":
                    public_url = t["public_url"]
                    break
        if public_url:
            break
    except Exception:
        pass
    time.sleep(1)

if not public_url:
    print("❌ Falha ao obter URL do ngrok.")
    print("   Verifique se o ngrok está instalado com: ngrok --version")
    ngrok_proc.terminate()
    sys.exit(1)

print()
print("✅ NGROK ATIVO!")
print()
print(f"  URL PÚBLICA DA PONTE:")
print(f"  ➜  {public_url}")
print()
print("=" * 55)
print("  COPIE A URL ACIMA E CONFIGURE NO VERCEL:")
print()
print("  1. Acesse: https://vercel.com/dashboard")
print("  2. Clique no seu projeto PROFITWAVER")
print("  3. Vá em Settings → Environment Variables")
print("  4. Adicione:")
print(f"     Nome: VITE_BRIDGE_URL")
print(f"     Valor: {public_url}")
print("  5. Clique em Save e depois Redeploy")
print("=" * 55)
print()
print("⚠️  Mantenha esta janela ABERTA enquanto o robô estiver rodando!")
print("   Fechar esta janela encerra o túnel e o painel perde conexão.")
print()
print("Pressione CTRL+C para encerrar o ngrok.")

try:
    ngrok_proc.wait()
except KeyboardInterrupt:
    print("\n🛑 Ngrok encerrado.")
    ngrok_proc.terminate()
