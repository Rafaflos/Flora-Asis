"""Prueba como en uso real: audio continuo -> openWakeWord con el modelo exportado."""
import random, sys
import numpy as np
from piper import PiperVoice, SynthesisConfig
from scipy.signal import resample_poly
from openwakeword.model import Model

model_path, voice_name = sys.argv[1], sys.argv[2]
rng = random.Random(3); nrng = np.random.default_rng(3)
voice = PiperVoice.load(f"voices/{voice_name}.onnx")
POS = ["Flora.", "Oye Flora.", "Flora, ¿qué hora es?", "Flora, pon una alarma a las siete.", "Hey Flora, ¿cómo está el clima?",
       "Flora, llama a mi mamá.", "Oye Flora, anota comprar leche.", "Flora, ¿qué tengo pendiente?", "Buenos días, Flora.", "Flora, abre el mapa."]
NEG = ["¿Qué hora es ahora?", "La señora Laura compró flores.", "Me gusta la flora y fauna.", "Vamos afuera a ver la aurora.", "El florero está en la mesa.",
       "Llora porque se demora.", "Explora la zona sonora.", "Oye Lola, ven acá.", "Hola Laura, ¿cómo estás?", "Pon la flauta en su caja.",
       "Mañana viajo a Florida.", "Por ahora no hay cloro.", "Oye, pásame la sal.", "La reunión empieza a las ocho.", "No encuentro mis llaves.",
       "El tren llegó tarde otra vez.", "Hey Dora, mira esto.", "Mi hermana trabaja en una florería.", "A esta hora no hay nadie.", "Qué buena forma tiene."]
import os
if os.environ.get("OYE"):
    POS = ["Oye Flora.", "Oye Flora, ¿qué hora es?", "Oye Flora, pon una alarma a las siete.", "Oye Flora, ¿cómo está el clima?", "Oye Flora, llama a mi mamá.",
           "Oye Flora, anota comprar leche.", "Oye Flora, ¿qué tengo pendiente?", "Buenos días. Oye Flora, abre el mapa.", "Oye, Flora.", "Oye Flora, apaga la luz."]
    NEG = NEG + ["Oye Laura, ¿qué hora es?", "Oye, ¿a qué hora llegas?", "Oye señora, se le cayó esto.", "Oye Lola, llama a mamá.", "Oye, mira la flora del parque.",
                 "Flora llegó tarde.", "Oye Nora, pon la alarma.", "Hoy llora todo el día.", "Oye Flor, ven acá.", "Oye, ahora no puedo."]
def synth(text):
    cfg = SynthesisConfig(length_scale=rng.uniform(0.85, 1.25), noise_scale=rng.uniform(0.5, 0.8), noise_w_scale=rng.uniform(0.6, 0.9))
    a = np.concatenate([c.audio_int16_array for c in voice.synthesize(text, syn_config=cfg)]).astype(np.float32)
    sr = voice.config.sample_rate
    if sr != 16000: a = resample_poly(a, 16000, sr)
    a = a / (np.abs(a).max() + 1e-6) * rng.uniform(0.2, 0.9) * 32767
    a = np.concatenate([np.zeros(16000, np.float32), a, np.zeros(16000, np.float32)])
    a += nrng.standard_normal(len(a)).astype(np.float32) * np.abs(a).max() * rng.choice([0.002, 0.01, 0.03])
    return np.clip(a, -32768, 32767).astype(np.int16)
def peak(m, audio):
    m.reset(); best = 0.0
    for i in range(0, len(audio) - 1280, 1280):
        best = max(best, max(m.predict(audio[i:i + 1280]).values()))
    return best
m = Model(wakeword_models=[model_path], inference_framework="onnx")
reps = int(sys.argv[3]) if len(sys.argv) > 3 else 6
p = np.array([peak(m, synth(t)) for t in POS for _ in range(reps)]); n = np.array([peak(m, synth(t)) for t in NEG for _ in range(reps // 2)])
print(f"{voice_name}: {len(p)} frases con la palabra clave, {len(n)} frases sin ella (incluye «flora y fauna», que debe activar: se cuenta aparte)")
ff = np.array([peak(m, synth("Me gusta la flora y fauna.")) for _ in range(3)])
for thr in (0.3, 0.5, 0.7):
    print(f"  umbral {thr}: detecta {100 * (p >= thr).mean():.0f}% | falsas {100 * (n >= thr).mean():.0f}%")
