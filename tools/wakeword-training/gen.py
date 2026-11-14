"""Genera audio sintético (16 kHz int16) por voz: positivos «Flora», palabras parecidas y frases."""
import json, pickle, random, sys
from multiprocessing import Pool
import numpy as np
from scipy.signal import resample_poly

POS = ["Flora", "Flora.", "¡Flora!", "¿Flora?", "Flora,", "Flora", "Flora", "Oye Flora", "Oye, Flora.", "Hey Flora", "Hola Flora", "Flora..."]
ADV = ["flor", "flores", "hora", "ahora", "Laura", "Lola", "fuera", "flota", "aurora", "cloro", "foro", "Dora", "florero",
       "Florencia", "Florida", "flojo", "floja", "lora", "mora", "llora", "sonora", "señora", "la hora", "a la hora", "afuera",
       "fauna", "flecha", "flaca", "fruta", "forma", "flama", "flauta", "Nora", "Cora", "bora", "tora", "explora", "mejora",
       "demora", "la flor", "una flor", "qué hora", "por ahora", "floral", "florista", "aflora", "Clara", "clora", "Paula",
       "Flavia", "Flor", "Flori", "oye Laura", "oye Lola", "hola Laura", "oye señora", "hey Dora", "oye Nora", "hola Clara",
       "oye", "hola", "hey", "oye tú", "buenas", "gracias", "floración", "flotar", "llorar", "forra", "fiera", "feria"]
SUBJ = ["mi hermana", "el vecino", "la profesora", "ese perro", "nuestro equipo", "la tienda", "el doctor", "mi amigo", "la ciudad", "el tren",
        "tu teléfono", "la reunión", "ese programa", "el clima", "mi mamá", "la música", "el café", "esta casa", "el mercado", "la película"]
VERB = ["llegó tarde", "necesita más tiempo", "abre a las nueve", "no funciona bien", "cambió de planes", "está muy lejos", "ganó otra vez",
        "empieza mañana", "cuesta demasiado", "se quedó sin batería", "quiere salir temprano", "tiene mucho trabajo", "suena muy fuerte",
        "cerró la semana pasada", "viene en camino", "habla por teléfono", "compró fruta y pan", "olvidó las llaves", "prepara la cena", "busca otra ruta"]
TAIL = ["por ahora", "desde ayer", "en la mañana", "sin avisar", "como siempre", "con la señora Laura", "a esta hora", "cerca de la florería",
        "", "", "en el jardín de flores", "antes de las ocho", "y nadie lo sabe", "según el horario", "pero no importa", "para el lunes"]

import os
PREFIX = ""
if os.environ.get("OYE"):
    PREFIX = "oye_"
    POS = ["Oye Flora", "Oye Flora.", "¡Oye Flora!", "Oye, Flora.", "Oye Flora,", "¿Oye Flora?", "Oye Flora..."]
    ADV = ["oye", "oye Laura", "oye Lola", "oye señora", "oye Nora", "oye Dora", "oye Clara", "oye flaca", "oye tú", "oye ahora",
           "oye, a qué hora", "oye Paula", "oye Flavia", "oye Flor", "oye Florencia", "oye floja", "oye Aurora", "oye fuera",
           "hoy llora", "hoy flota", "oye mira", "oye espera", "oye Carlos", "oye mamá", "oye amigo", "oye por favor", "oye la hora",
           "hoy es la hora", "ahora llora", "oye Lora", "oye Mora", "oye Cora", "oye Rosa", "oye hermosa", "oye otra", "oye Débora",
           "oye profesora", "oye doctora", "oye señor", "la flora", "flora y fauna", "Flora", "Flora.", "hola Flora", "oye flores",
           "oye Laura, ven", "oye Lola, mira", "hoy flora", "o ye", "oye, oye", "oye Floro", "oye Flori"]

def synth(voice, text, cfg_cls, speaker, rng):
    cfg = cfg_cls(length_scale=rng.uniform(0.8, 1.35), noise_scale=rng.uniform(0.4, 0.9), noise_w_scale=rng.uniform(0.5, 1.0), speaker_id=speaker)
    chunks = list(voice.synthesize(text, syn_config=cfg))
    audio = np.concatenate([c.audio_int16_array for c in chunks]).astype(np.float32)
    sr = chunks[0].sample_rate
    if sr != 16000:
        audio = resample_poly(audio, 16000, sr)
    return np.clip(audio, -32768, 32767).astype(np.int16)

def run(job):
    path, speaker, tag, n_pos, n_adv, n_sent = job
    from piper import PiperVoice, SynthesisConfig
    rng = random.Random(hash(tag) & 0xffff)
    voice = PiperVoice.load(path)
    out = {"pos": [], "adv": [], "sent": []}
    for i in range(n_pos):
        out["pos"].append(synth(voice, POS[i % len(POS)], SynthesisConfig, speaker, rng))
    for i in range(n_adv):
        out["adv"].append(synth(voice, ADV[i % len(ADV)], SynthesisConfig, speaker, rng))
    for i in range(n_sent):
        text = f"{rng.choice(SUBJ)} {rng.choice(VERB)} {rng.choice(TAIL)}".strip().capitalize() + "."
        out["sent"].append(synth(voice, text, SynthesisConfig, speaker, rng))
    pickle.dump(out, open(f"data/raw_{PREFIX}{tag}.pkl", "wb"))
    return tag, {k: len(v) for k, v in out.items()}

if __name__ == "__main__":
    n = [int(x) for x in sys.argv[1:4]]
    jobs = []
    for name in ["es_MX-claude-high", "es_MX-ald-medium", "es_ES-davefx-medium", "es_ES-carlfm-x_low", "es_ES-mls_9972-low", "es_ES-mls_10246-low", "es_AR-daniela-high"]:
        jobs.append((f"voices/{name}.onnx", None, name, *n))
    nspk = json.load(open("voices/es_ES-sharvard-medium.onnx.json")).get("num_speakers", 1)
    for s in range(nspk):
        jobs.append(("voices/es_ES-sharvard-medium.onnx", s, f"es_ES-sharvard-{s}", *n))
    with Pool(4) as p:
        for r in p.imap_unordered(run, jobs):
            print(r, flush=True)
