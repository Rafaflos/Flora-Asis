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
python listener.py        # voz: di «Oye Flora»
```

macOS pedirá permiso de micrófono para la terminal la primera vez.

Android: la app compila con `./gradlew assembleDebug` (comprobado con SDK 35; el analizador
de Android no da errores). No se ha ejecutado en un teléfono real. Abre `android-app/` en Android Studio, copia `local.properties.example` a
`local.properties`, pon la IP de la Mac (`ipconfig getifaddr en0`) y el token, y ejecuta en el teléfono.
`setup-mac.sh` ya escribe ambos valores.

## Centinela

Las herramientas `critical=True` (`phone_call`, `send_message`, `run_mac_script`) no se
ejecutan desde el bucle del agente: se guardan en `pending_actions` y devuelven
`REQUIRES_CONFIRMATION`. Solo un mensaje `confirmation` de un cliente autenticado
(voz en la Mac, botón en la tarjeta de Android) las ejecuta, con la entrada guardada,
una sola vez y antes de 120 s. El modelo no tiene ninguna herramienta para aprobar.

## Palabra clave «Oye Flora»

El nodo de escritorio usa `desktop-node/models/oye_flora.onnx`, un modelo openWakeWord
entrenado solo con voz sintética (unos 1,000 hablantes). Es experimental. Medido con umbral
0.8 y dos cuadros seguidos:

- Voz mexicana no vista (medido en una versión entrenada sin esa voz; el modelo final sí la incluye): detectó 88 de 100 frases.
- Frases parecidas sin la palabra clave («oye Laura», «Flora llegó tarde»): 2 % de activaciones.
- 5.3 horas de audio real sin la palabra: unas 0.4 a 0.6 falsas activaciones por hora.

No se ha probado con voces humanas reales. Si se activa sola, sube `FLORA_WAKE_THRESHOLD`;
si no te oye, bájalo. Para volver a «hey Jarvis»: `FLORA_WAKEWORD=hey_jarvis`.
Los scripts con los que se entrenó están en `tools/wakeword-training/`.

La app Android usa el mismo modelo con ONNX Runtime (`WakeWordDetector.kt`, modelos en
`android-app/app/src/main/assets/`), sin cuentas ni claves de terceros.

Los modelos `melspectrogram.onnx` y `embedding_model.onnx` son de openWakeWord y se
distribuyen con licencia CC BY-NC-SA 4.0: uso personal, no comercial.
