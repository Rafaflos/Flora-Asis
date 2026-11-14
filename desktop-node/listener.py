"""
Flora · Nodo de escucha de escritorio (macOS)
=============================================
Micrófono -> palabra clave (openWakeWord) -> VAD (webrtcvad) -> faster-whisper
-> WebSocket al Cerebro Central -> respuesta hablada (edge-tts + afplay).

Uso:
  python listener.py           modo voz
  python listener.py --text    modo texto (sin micrófono ni modelos; para probar el backend)

Variables (.env en esta carpeta o entorno):
  FLORA_TOKEN          mismo token que el backend (obligatorio)
  FLORA_SERVER         ws://127.0.0.1:8765/ws
  FLORA_DEVICE_ID      mac-escritorio
  FLORA_WAKEWORD       ruta a un .onnx o nombre preentrenado (por defecto models/oye_flora.onnx)
  FLORA_WAKE_THRESHOLD 0.8 con el modelo propio, 0.5 con los preentrenados
  FLORA_WHISPER_MODEL  small
  FLORA_VOICE          es-MX-DaliaNeural
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import tempfile
from pathlib import Path

import websockets


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))


_load_dotenv(Path(__file__).resolve().parent / ".env")

SERVER = os.environ.get("FLORA_SERVER", "ws://127.0.0.1:8765/ws")
TOKEN = os.environ.get("FLORA_TOKEN", "")
DEVICE_ID = os.environ.get("FLORA_DEVICE_ID", "mac-escritorio")
# Palabra clave: el modelo propio «Oye Flora» si está en models/; si no, el preentrenado "hey_jarvis".
_FLORA_MODEL = Path(__file__).resolve().parent / "models" / "oye_flora.onnx"
WAKEWORD = os.environ.get("FLORA_WAKEWORD") or (str(_FLORA_MODEL) if _FLORA_MODEL.exists() else "hey_jarvis")
WAKEWORD_NAME = Path(WAKEWORD).stem.replace("_", " ")
_CUSTOM = WAKEWORD.endswith(".onnx")
# El modelo propio se midió con umbral 0.8 y 2 cuadros seguidos (80 ms cada uno) por encima.
WAKE_THRESHOLD = float(os.environ.get("FLORA_WAKE_THRESHOLD", "0.8" if _CUSTOM else "0.5"))
WAKE_FRAMES = int(os.environ.get("FLORA_WAKE_FRAMES", "2" if _CUSTOM else "1"))
WHISPER_MODEL = os.environ.get("FLORA_WHISPER_MODEL", "small")
VOICE = os.environ.get("FLORA_VOICE", "es-MX-DaliaNeural")

SAMPLE_RATE = 16000
FRAME_SAMPLES = 1280          # 80 ms: tamaño que espera openWakeWord
VAD_FRAME_BYTES = 320 * 2     # 20 ms en PCM16
END_SILENCE_MS = 800          # silencio que cierra la frase
MAX_UTTERANCE_MS = 15000
NO_SPEECH_TIMEOUT_MS = 4000   # tras la palabra clave, si no dices nada

YES = re.compile(r"\b(s[ií]|confirm[oa]|adelante|hazlo|dale|claro|okey|ok|procede|correcto)\b", re.I)
NO = re.compile(r"\b(no|cancel[ao]|cancelar|det[eé]n|olv[ií]dalo|espera|mejor no)\b", re.I)


def parse_yes_no(text: str) -> bool | None:
    if NO.search(text):
        return False
    if YES.search(text):
        return True
    return None


class FloraLink:
    """Conexión WebSocket con reconexión automática."""

    def __init__(self, on_message) -> None:
        self.on_message = on_message
        self.ws = None

    async def run(self) -> None:
        async for ws in websockets.connect(SERVER, ping_interval=20):
            try:
                await ws.send(json.dumps({"type": "hello", "token": TOKEN, "device_id": DEVICE_ID, "kind": "mac"}))
                self.ws = ws
                async for raw in ws:
                    await self.on_message(json.loads(raw))
            except websockets.ConnectionClosed as exc:
                if exc.rcvd and exc.rcvd.code == 4401:
                    raise SystemExit("Token rechazado por el backend: revisa FLORA_TOKEN.")
            finally:
                self.ws = None
            print("· Conexión perdida; reintentando…", flush=True)

    async def send(self, payload: dict) -> bool:
        if self.ws is None:
            return False
        try:
            await self.ws.send(json.dumps(payload))
            return True
        except websockets.ConnectionClosed:
            return False


# ───────────────────────────── Modo texto ─────────────────────────────


async def run_text_mode() -> None:
    pending: dict[str, str | None] = {"id": None}

    async def on_message(msg: dict) -> None:
        if msg["type"] == "ready":
            print("· Conectada. Escribe y pulsa Enter.", flush=True)
        elif msg["type"] == "reply":
            print(f"Flora: {msg['text']}", flush=True)
        elif msg["type"] == "confirmation_request":
            pending["id"] = msg["action_id"]
            print(f"[CONFIRMAR] {msg['summary']}  (responde sí / no)", flush=True)
        elif msg["type"] == "confirmation_resolved" and pending["id"] == msg["action_id"]:
            pending["id"] = None

    link = FloraLink(on_message)
    link_task = asyncio.create_task(link.run())
    loop = asyncio.get_running_loop()
    while True:
        line = await loop.run_in_executor(None, sys.stdin.readline)
        if not line or link_task.done():
            break
        text = line.strip()
        if not text:
            continue
        answer = parse_yes_no(text) if pending["id"] else None
        if answer is not None:
            payload = {"type": "confirmation", "action_id": pending["id"], "approved": answer}
        else:
            payload = {"type": "utterance", "text": text}
        if not await link.send(payload):
            print("· Sin conexión con el Cerebro Central.", flush=True)
    await asyncio.sleep(0.2)
    link_task.cancel()


# ───────────────────────────── Modo voz ─────────────────────────────


class VoiceNode:
    def __init__(self) -> None:
        # Imports pesados solo en modo voz.
        import numpy as np
        import openwakeword
        import sounddevice as sd
        import webrtcvad
        from faster_whisper import WhisperModel
        from openwakeword.model import Model as WakeModel

        self.np, self.sd = np, sd
        print("· Cargando modelos (la primera vez descarga varios cientos de MB)…", flush=True)
        openwakeword.utils.download_models()
        self.wake = WakeModel(wakeword_models=[WAKEWORD], inference_framework="onnx")
        self.vad = webrtcvad.Vad(2)
        self.whisper = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")

        self.audio_q: asyncio.Queue[bytes] = asyncio.Queue()
        self.speak_q: asyncio.Queue[str] = asyncio.Queue()
        self.link = FloraLink(self.on_message)
        self.speaking = False
        self.wake_streak = 0
        self.pending_confirmation: str | None = None
        self.listen_now = False  # abrir el micro sin palabra clave (respuesta a una confirmación)

    # ── Captura ──
    def _flush_audio(self) -> None:
        while not self.audio_q.empty():
            self.audio_q.get_nowait()
        self.wake.reset()
        self.wake_streak = 0

    def _has_speech(self, frame: bytes) -> bool:
        chunks = (frame[i:i + VAD_FRAME_BYTES] for i in range(0, len(frame), VAD_FRAME_BYTES))
        return any(len(c) == VAD_FRAME_BYTES and self.vad.is_speech(c, SAMPLE_RATE) for c in chunks)

    def _wake_detected(self, frame: bytes) -> bool:
        scores = self.wake.predict(self.np.frombuffer(frame, dtype=self.np.int16))
        self.wake_streak = self.wake_streak + 1 if max(scores.values()) >= WAKE_THRESHOLD else 0
        return self.wake_streak >= WAKE_FRAMES

    async def _record_utterance(self) -> bytes | None:
        """Graba hasta detectar fin de voz. Devuelve None si nadie habló."""
        frames: list[bytes] = []
        frame_ms = FRAME_SAMPLES * 1000 // SAMPLE_RATE
        elapsed = silence = 0
        heard = False
        while elapsed < MAX_UTTERANCE_MS:
            frame = await self.audio_q.get()
            frames.append(frame)
            elapsed += frame_ms
            if self._has_speech(frame):
                heard, silence = True, 0
            else:
                silence += frame_ms
            if heard and silence >= END_SILENCE_MS:
                break
            if not heard and elapsed >= NO_SPEECH_TIMEOUT_MS:
                return None
        return b"".join(frames) if heard else None

    def _transcribe(self, pcm: bytes) -> str:
        audio = self.np.frombuffer(pcm, dtype=self.np.int16).astype(self.np.float32) / 32768.0
        segments, _ = self.whisper.transcribe(audio, language="es", vad_filter=True)
        return " ".join(s.text.strip() for s in segments).strip()

    async def _chime(self, name: str) -> None:
        proc = await asyncio.create_subprocess_exec("afplay", f"/System/Library/Sounds/{name}.aiff")
        await proc.wait()

    async def listen_loop(self) -> None:
        print(f"· Escuchando. Di «{WAKEWORD_NAME}».", flush=True)
        while True:
            frame = await self.audio_q.get()
            if self.speaking:
                continue  # no escucharse a sí misma
            if not (self.listen_now or self._wake_detected(frame)):
                continue
            self.listen_now = False
            await self._chime("Tink")
            self._flush_audio()
            pcm = await self._record_utterance()
            if pcm is None:
                self._flush_audio()
                continue
            text = await asyncio.to_thread(self._transcribe, pcm)
            self._flush_audio()
            if text:
                print(f"Tú: {text}", flush=True)
                await self._dispatch(text)

    async def _dispatch(self, text: str) -> None:
        if self.pending_confirmation:
            answer = parse_yes_no(text)
            if answer is None:
                self.listen_now = True
                await self.speak_q.put("No te entendí. ¿Confirmas, sí o no?")
                return
            payload = {"type": "confirmation", "action_id": self.pending_confirmation, "approved": answer}
            self.pending_confirmation = None
        else:
            payload = {"type": "utterance", "text": text}
        if not await self.link.send(payload):
            await self.speak_q.put("No tengo conexión con mi cerebro central.")

    # ── Mensajes del backend ──
    async def on_message(self, msg: dict) -> None:
        mtype = msg.get("type")
        if mtype == "ready":
            print("· Conectada al Cerebro Central.", flush=True)
        elif mtype == "reply":
            print(f"Flora: {msg['text']}", flush=True)
            await self.speak_q.put(msg["text"])
        elif mtype == "confirmation_request" and msg.get("origin") == DEVICE_ID:
            # La respuesta de Flora que llega enseguida hace la pregunta; al terminar se abre el micro.
            self.pending_confirmation = msg["action_id"]
        elif mtype == "confirmation_resolved" and msg.get("action_id") == self.pending_confirmation:
            self.pending_confirmation = None  # se resolvió desde el teléfono
        elif mtype == "error":
            print(f"· Error del backend: {msg.get('detail')}", flush=True)

    # ── Voz ──
    async def speak_loop(self) -> None:
        import edge_tts

        while True:
            text = await self.speak_q.get()
            self.speaking = True
            path = tempfile.mktemp(suffix=".mp3")
            try:
                await edge_tts.Communicate(text, VOICE).save(path)
                proc = await asyncio.create_subprocess_exec("afplay", path)
                await proc.wait()
            except Exception as exc:
                print(f"· Fallo de TTS: {exc}", flush=True)
            finally:
                if os.path.exists(path):
                    os.unlink(path)
                if self.speak_q.empty():
                    self._flush_audio()
                    self.speaking = False
                    if self.pending_confirmation:
                        self.listen_now = True

    async def run(self) -> None:
        loop = asyncio.get_running_loop()

        def callback(indata, frames, time_info, status) -> None:
            loop.call_soon_threadsafe(self.audio_q.put_nowait, bytes(indata))

        stream = self.sd.RawInputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16",
                                        blocksize=FRAME_SAMPLES, callback=callback)
        with stream:
            await asyncio.gather(self.link.run(), self.listen_loop(), self.speak_loop())


def main() -> None:
    parser = argparse.ArgumentParser(description="Nodo de escucha de Flora")
    parser.add_argument("--text", action="store_true", help="modo texto, sin micrófono")
    args = parser.parse_args()
    if not TOKEN:
        raise SystemExit("Define FLORA_TOKEN (desktop-node/.env).")
    try:
        asyncio.run(run_text_mode() if args.text else VoiceNode().run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
