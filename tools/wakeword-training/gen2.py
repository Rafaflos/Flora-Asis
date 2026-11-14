"""Más hablantes: voces multi-hablante y romances sintetizando fonemas del español."""
import pickle, random, sys
from multiprocessing import Pool
import numpy as np
from scipy.signal import resample_poly
from gen import POS, ADV, SUBJ, VERB, TAIL, PREFIX

EN = {"o": ["ɔ", "oʊ", "ɔː"], "a": ["ɑ", "ɐ", "ɑː", "ə"], "e": ["ɛ", "eɪ"], "ʝ": ["j"], "ɲ": ["n", "j"], "β": ["b"], "ɣ": ["ɡ"],
      "x": ["h"], "r": ["ɹ", "ɾ"], "ʎ": ["j"], "ɾ": ["ɾ", "ɾ", "ɹ"]}

def phon_ids(voice, phonemes, english, rng):
    out = []
    for p in phonemes:
        if english and p in EN:
            sub = EN[p]
            out += sub if p == "ɲ" else list(rng.choice(sub))
        else:
            out.append(p)
    return voice.phonemes_to_ids(out)

def run(job):
    name, speakers, tag, n_pos, n_adv, n_sent, texts = job
    from piper import PiperVoice, SynthesisConfig
    rng = random.Random(hash(tag) & 0xffff)
    voice = PiperVoice.load(f"voices/{name}.onnx"); english = name.startswith("en_")
    sr = voice.config.sample_rate
    def synth(phonemes, spk):
        cfg = SynthesisConfig(length_scale=rng.uniform(0.8, 1.35), noise_scale=rng.uniform(0.4, 0.9), noise_w_scale=rng.uniform(0.5, 1.0), speaker_id=spk)
        a = voice.phoneme_ids_to_audio(phon_ids(voice, phonemes, english, rng), cfg)
        a = np.asarray(a, dtype=np.float32)
        if np.abs(a).max() <= 1.5: a = a * 32767
        if sr != 16000: a = resample_poly(a, 16000, sr)
        return np.clip(a, -32768, 32767).astype(np.int16)
    out = {"pos": [], "adv": [], "sent": []}
    for spk in speakers:
        for kind, n in (("pos", n_pos), ("adv", n_adv), ("sent", n_sent)):
            for _ in range(n):
                out[kind].append(synth(rng.choice(texts[kind]), spk))
    pickle.dump(out, open(f"data/raw_{PREFIX}{tag}.pkl", "wb"))
    return tag, {k: len(v) for k, v in out.items()}

if __name__ == "__main__":
    from piper import PiperVoice
    es = PiperVoice.load("voices/es_MX-claude-high.onnx"); rng = random.Random(1)
    ph = lambda t: [p for s in es.phonemize(t) for p in s]
    sents = [f"{rng.choice(SUBJ)} {rng.choice(VERB)} {rng.choice(TAIL)}".strip() + "." for _ in range(300)]
    texts = {"pos": [ph(t) for t in POS], "adv": [ph(t) for t in ADV], "sent": [ph(t) for t in sents]}
    jobs = []
    for lo in range(0, 850, 50):
        jobs.append(("en_US-libritts_r-medium", list(range(lo, lo + 50)), f"libri_{lo:03d}", 3, 4, 1, texts))
    jobs.append(("en_US-libritts_r-medium", list(range(850, 904)), "HELD_libri", 5, 6, 1, texts))
    for lo in range(0, 109, 37):
        jobs.append(("en_GB-vctk-medium", list(range(lo, min(109, lo + 37))), f"vctk_{lo:03d}", 8, 10, 2, texts))
    jobs.append(("en_US-l2arctic-medium", list(range(24)), "l2arctic", 20, 25, 5, texts))
    for name in ["it_IT-paola-medium", "it_IT-riccardo-x_low", "pt_BR-faber-medium", "pt_BR-cadu-medium", "pt_BR-jeff-medium"]:
        jobs.append((name, [None], name, 250, 300, 80, texts))
    if len(sys.argv) > 1: jobs = [(j[0], j[1][:2], "TEST_" + j[2], 2, 1, 1, texts) for j in jobs[:1] + jobs[-7:-6] + jobs[-1:]]
    with Pool(4) as p:
        for r in p.imap_unordered(run, jobs): print(r, flush=True)
