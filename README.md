# Flora · Fase 1

Asistente personal autónomo en tu red privada. El cerebro corre en la Mac; escucha
desde el micrófono de la Mac y desde el teléfono Android.

```
flora/
├── setup-mac.sh            configuración en un paso
├── .vscode/tasks.json      tareas de VS Code para configurar y arrancar
├── backend-mac/            Cerebro Central (FastAPI + WebSockets + Claude + SQLite)
│   ├── server.py           agente, memoria, Centinela, hub de dispositivos
│   ├── panel.html          panel en vivo (http://127.0.0.1:8765/panel)
│   ├── smart_home.py       SmartHomeController (esqueleto Fase 2)
│   ├── scripts/            únicos scripts que Flora puede ejecutar en la Mac
│   ├── requirements.txt
│   └── .env.example
├── desktop-node/           Nodo de escucha de la Mac
│   ├── listener.py         palabra clave -> VAD -> whisper -> WS -> TTS
│   ├── requirements.txt
│   └── .env.example
└── android-app/            App nativa (Kotlin)
    ├── local.properties.example
    └── app/src/main/
        ├── AndroidManifest.xml
        ├── res/xml/{network_security_config,accessibility_config}.xml
        └── java/com/flora/assistant/
            ├── WebSocketManager.kt
            ├── ActionExecutor.kt
            ├── FloraListenerService.kt
            ├── FloraAccessibilityService.kt
            └── MainActivity.kt
```

## Instalación rápida en macOS

```bash
./setup-mac.sh
```

Instala todo, genera el token compartido y pide la clave de la API de Claude con entrada
oculta. En VS Code: Terminal > Run Task > "Flora: 1 · Configurar". Después arranca el
Cerebro (tarea 2) y abre el panel en vivo en http://127.0.0.1:8765/panel con el `FLORA_TOKEN`.

## Instalación manual en macOS

```bash
brew install python@3.11 portaudio ffmpeg
```

Backend:

```bash
cd backend-mac
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
openssl rand -hex 24      # pégalo como FLORA_TOKEN en .env, junto a tu ANTHROPIC_API_KEY
python server.py
```

Nodo de escritorio (otra terminal):

```bash
cd desktop-node
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # mismo FLORA_TOKEN
python listener.py --text # prueba por teclado, sin micrófono
python listener.py        # voz: di "hey Jarvis"
```

macOS pedirá permiso de micrófono para la terminal la primera vez.

Android: abre `android-app/` en Android Studio, copia `local.properties.example` a
`local.properties`, pon la IP de la Mac (`ipconfig getifaddr en0`), el token y tu
AccessKey gratuita de console.picovoice.ai, y ejecuta en el teléfono.

## Centinela

Las herramientas `critical=True` (`phone_call`, `send_message`, `run_mac_script`) no se
ejecutan desde el bucle del agente: se guardan en `pending_actions` y devuelven
`REQUIRES_CONFIRMATION`. Solo un mensaje `confirmation` de un cliente autenticado
(voz en la Mac, botón en la tarjeta de Android) las ejecuta, con la entrada guardada,
una sola vez y antes de 120 s. El modelo no tiene ninguna herramienta para aprobar.

## Palabra clave "Flora"

Los dos nodos usan "Jarvis" (modelos preentrenados). Para "Flora": entrena un modelo
openWakeWord y pon su ruta en `FLORA_WAKEWORD`; en Android, entrena un `.ppn` en la
consola de Picovoice (ver comentario en `FloraListenerService.kt`).
