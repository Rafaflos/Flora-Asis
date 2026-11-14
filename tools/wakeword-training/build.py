"""Aumenta el audio crudo y extrae las características de openWakeWord (N, 16, 96)."""
import glob, os, pickle, sys
import numpy as np
from scipy.signal import resample_poly, fftconvolve
import openwakeword
from openwakeword.utils import AudioFeatures

SR, CLIP = 16000, 32000
rng = np.random.default_rng(7)

def trim(a, thr=0.02):
    x = np.abs(a.astype(np.float32)) / 32768
    idx = np.where(x > thr * max(x.max(), 1e-6) / 0.5 * 0.5)[0]
    return a[max(0, idx[0] - 400): idx[-1] + 800] if len(idx) else a

def noise(n):
    w = rng.standard_normal(n).astype(np.float32)
    kind = rng.integers(3)
    if kind == 1:   # rosa aproximado
        w = np.cumsum(w); w -= np.linspace(w[0], w[-1], n); w = w * 0.3 + rng.standard_normal(n) * 0.7
    elif kind == 2: # zumbido + ruido
        t = np.arange(n) / SR; w = w * 0.5 + np.sin(2 * np.pi * rng.uniform(50, 400) * t) * 1.5
    return w / (np.abs(w).std() + 1e-6)

def augment(a, end_aligned, bg=None):
    x = a.astype(np.float32) / 32768
    f = rng.uniform(0.88, 1.14)                       # velocidad/tono
    x = resample_poly(x, int(1000 * f), 1000)
    if rng.random() < 0.4:                            # reverberación sintética
        n = int(SR * rng.uniform(0.1, 0.4)); ir = rng.standard_normal(n) * np.exp(-np.arange(n) / (n / 5))
        wet = fftconvolve(x, ir / np.sqrt((ir ** 2).sum()))[: len(x)]
        x = x + wet * rng.uniform(0.2, 0.7)
    x = x / (np.abs(x).max() + 1e-6) * rng.uniform(0.15, 0.95)
    out = np.zeros(CLIP, np.float32)
    if bg is not None and rng.random() < 0.5:         # habla de fondo/previa
        b = bg.astype(np.float32) / 32768; s = rng.integers(0, max(1, len(b) - CLIP)); b = b[s: s + CLIP]
        out[: len(b)] += b * rng.uniform(0.1, 0.5)
    if end_aligned:                                   # la palabra termina cerca del final de la ventana
        x = x[-CLIP:]; end = CLIP - rng.integers(0, int(0.25 * SR)); start = max(0, end - len(x))
        if bg is not None: out[start:end] *= 0.3
        out[start:end] += x[: end - start] if start else x[-end:]
    else:
        s = rng.integers(0, max(1, len(x) - CLIP)); seg = x[s: s + CLIP]; o = rng.integers(0, CLIP - len(seg) + 1)
        out[o: o + len(seg)] += seg
    p = np.sqrt((x ** 2).mean() + 1e-9)
    out += noise(CLIP) * p / (10 ** (rng.uniform(3, 30) / 20))
    return (np.clip(out, -1, 1) * 32767).astype(np.int16)

if __name__ == "__main__":
    n_aug = int(sys.argv[1])
    openwakeword.utils.download_models(model_names=["hey_jarvis"])
    F = AudioFeatures(inference_framework="onnx", ncpu=4)
    for path in sorted(glob.glob("data/raw_*.pkl")):
        tag = path[9:-4]
        if os.path.exists(f"data/feat_{tag}.npz"): continue
        raw = pickle.load(open(path, "rb"))
        pos = [t for t in map(trim, raw["pos"]) if (0.45 if tag.startswith("oye") else 0.25) * SR < len(t) < (1.9 if tag.startswith("oye") else 1.3) * SR]
        adv = [t for t in map(trim, raw["adv"]) if len(t) > 0.15 * SR]
        sent = raw["sent"]
        P = np.stack([augment(a, True, sent[rng.integers(len(sent))]) for a in pos for _ in range(n_aug)])
        A = np.stack([augment(a, True, sent[rng.integers(len(sent))]) for a in adv for _ in range(n_aug)])
        Sx = np.stack([augment(a, False) for a in sent for _ in range(n_aug * 2)])
        N = np.concatenate([A, Sx])
        fp, fn = F.embed_clips(P, batch_size=128, ncpu=4), F.embed_clips(N, batch_size=128, ncpu=4)
        np.savez(f"data/feat_{tag}.npz", pos=fp.astype(np.float32), neg=fn.astype(np.float32))
        print(tag, "pos válidos", len(pos), "/", len(raw["pos"]), fp.shape, fn.shape, flush=True)
