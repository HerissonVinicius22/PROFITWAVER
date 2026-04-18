# 🚀 Guia de Conexão (Vercel + Ngrok)

Para usar o ProfitWave no Vercel ou compartilhar com outras pessoas, você precisa expor sua ponte local para a internet. Siga estes passos:

## 1. Prepare a Ponte no seu PC
1. Certifique-se que o Quotex está aberto em algum navegador ou que você tem os dados de login à mão.
2. Execute o arquivo `INICIAR_PONTE.bat`. Isso abrirá o servidor da ponte na porta 5001.

## 2. Inicie o Ngrok
1. Execute o arquivo `INICIAR_NGROK.bat`.
2. Uma janela de terminal vai abrir e, após alguns segundos, ela mostrará uma **URL PÚBLICA** (ex: `https://abcd-123.ngrok-free.app`).
3. **Copie essa URL completa.**

## 3. Configure no Site (Vercel)
1. Abra o link do seu site no Vercel.
2. Você verá um botão vermelho escrito **"Configurar Ponte (ngrok)"** no centro da tela (ou clique no ícone de engrenagem ⚙️ no topo direito).
3. Cole a URL que você copiou no campo **"URL da Ponte"**.
4. Clique em **"Salvar e Fechar"**.

## 4. Conecte a Corretora
1. O status da ponte deve mudar para **"Ponte ON"** (verde).
2. Clique no botão **"Conectar Quotex"** na parte inferior.
3. Um navegador vai abrir no seu PC. Faça o login na Quotex normalmente.
4. Assim que o login for detectado, o site no Vercel mostrará **"Quotex Conectado"**.

---
### ⚠️ Importante
- Mantenha os terminais da **Ponte** e do **Ngrok** abertos no seu PC enquanto estiver usando o robô.
- Se você fechar o Ngrok e abrir de novo, a URL vai mudar e você precisará colar a nova no site.
