"""Entrena el detector la palabra clave sobre características de openWakeWord y lo exporta a ONNX."""
import glob, os, sys
PEN = float(os.environ.get("PEN", 30)); DIM = int(os.environ.get("DIM", 96))
import numpy as np, torch, torch.nn as nn

torch.manual_seed(0); np.random.seed(0)
HOLDOUT = sys.argv[1] if len(sys.argv) > 1 else ""      # voz que se deja fuera para evaluar
OUT = sys.argv[2] if len(sys.argv) > 2 else "flora.onnx"

pos_tr, neg_tr, pos_te, neg_te = [], [], [], []
for path in sorted(glob.glob("data/feat_*.npz")):
    d = np.load(path); held = any(h and h in path for h in HOLDOUT.split(","))
    oye = "feat_oye_" in path
    if oye or not os.environ.get("OYE"): (pos_te if held else pos_tr).append(d["pos"])
    (neg_te if held else neg_tr).append(d["neg"])
pos_tr, neg_tts = np.concatenate(pos_tr), np.concatenate(neg_tr)

acav = np.memmap("data/acav_part.bin", dtype=np.float16, mode="r", offset=128, shape=(500000, 16, 96))
val = np.load("data/val.npy", mmap_mode="r")            # 10,7 h de audio real, cuadros continuos
n_val = len(val) - 16
split = n_val // 2                                      # 1ª mitad: negativos duros para entrenar; 2ª: prueba
def val_windows(lo, hi, step=1):
    idx = np.arange(lo, hi, step)[:, None] + np.arange(16)[None]
    return np.asarray(val)[idx]

class Net(nn.Module):
    def __init__(self, dim=96):
        super().__init__()
        self.net = nn.Sequential(nn.Flatten(), nn.Linear(16 * 96, dim), nn.LayerNorm(dim), nn.ReLU(), nn.Dropout(0.2),
                                 nn.Linear(dim, dim), nn.LayerNorm(dim), nn.ReLU(), nn.Linear(dim, 1), nn.Sigmoid())
    def forward(self, x): return self.net(x)

model = Net(DIM); opt = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-2)
P = torch.tensor(pos_tr); NT = torch.tensor(neg_tts)
hard = torch.tensor(val_windows(0, split, 4))           # ventanas reales de la mitad de entrenamiento
STEPS, B = int(os.environ.get("STEPS", 12000)), 512
sched = torch.optim.lr_scheduler.OneCycleLR(opt, 2e-3, total_steps=STEPS)
print(f"pos {len(P)}  neg TTS {len(NT)}  neg reales {len(acav)} + {len(hard)}", flush=True)
for step in range(STEPS):
    model.train()
    ip = torch.randint(len(P), (B // 4,)); it = torch.randint(len(NT), (B // 4,)); ih = torch.randint(len(hard), (B // 8,))
    ia = np.sort(np.random.randint(0, len(acav), B * 3 // 8))
    xa = torch.tensor(np.asarray(acav[ia], dtype=np.float32))
    x = torch.cat([P[ip], NT[it], hard[ih], xa]); y = torch.cat([torch.ones(len(ip)), torch.zeros(len(x) - len(ip))])
    x = x + torch.randn_like(x) * 0.1
    x = x * (torch.rand(len(x), 16, 1) > 0.05)            # apaga cuadros al azar (regularización)
    p = model(x).squeeze(1)
    w = torch.where(y == 1, 1.0, 1.0 + PEN * min(1.0, step / (STEPS * 0.6)) * (p.detach() > 0.3))  # castiga falsos positivos
    loss = (nn.functional.binary_cross_entropy(p, y, reduction="none") * w).mean()
    opt.zero_grad(); loss.backward(); opt.step(); sched.step()
    if step % 2000 == 0: print(step, round(loss.item(), 4), flush=True)

model.eval()
@torch.no_grad()
def score(x, bs=8192): return np.concatenate([model(torch.tensor(np.asarray(x[i:i + bs], dtype=np.float32))).squeeze(1).numpy() for i in range(0, len(x), bs)])
print("recall en entrenamiento @0.5:", round(float((score(pos_tr) >= 0.5).mean()), 3))
if pos_te:
    for q in pos_te: pass
test = score(val_windows(split, n_val))                 # deslizante, como en uso real
hours = len(test) * 0.08 / 3600
def events(s, thr):                                     # activaciones separadas por al menos 2 s
    hits = np.where(s >= thr)[0]; return 0 if not len(hits) else 1 + int((np.diff(hits) > 25).sum())
if pos_te:
    sp, sn = score(np.concatenate(pos_te)), score(np.concatenate(neg_te))
print(f"\nPrueba: {hours:.1f} h de audio real no visto" + (f", voz no vista {HOLDOUT} ({len(sp)} la palabra clave, {len(sn)} parecidas/frases)" if pos_te else ""))
for thr in (0.3, 0.5, 0.7, 0.9):
    line = f"umbral {thr}: falsas activaciones/h {events(test, thr) / hours:.2f}"
    if pos_te: line += f" | detecta la palabra clave {100 * (sp >= thr).mean():.1f}% | confunde parecidas {100 * (sn >= thr).mean():.2f}%"
    print(line)
torch.onnx.export(model, torch.zeros(1, 16, 96), OUT, input_names=["x"], output_names=["score"], opset_version=13, dynamo=False)
print("exportado", OUT)
