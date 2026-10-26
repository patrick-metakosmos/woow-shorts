"""Gera trilhas instrumentais com Lyria (Vertex AI) para a pasta musica/.

Cada chamada devolve ~30s. O script emenda 3 cópias com crossfade (~86s,
sobra para qualquer vídeo), normaliza em -18 LUFS e grava em M4A. Roda uma
vez para montar o acervo; o pipeline só reaproveita.

    python tools/gerar_trilhas.py --quantas 1    # teste
    python tools/gerar_trilhas.py --quantas 15
"""
from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

import google.auth
import requests
from google.auth.transport.requests import Request

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.llm import GCP_LOCATION, GCP_PROJECT  # noqa: E402
from src.util import ROOT, binario, log  # noqa: E402

MODELO = "lyria-002"
PASTA = ROOT / "musica"
NEGATIVO = "vocals, singing, voice, spoken words, lyrics, choir, heavy distortion, long silence, abrupt ending"
BASE = "Instrumental background bed for a fast daily tech and retail news video, sits under a voice-over, loopable"

ESTILOS = [
    ("minimal-pulse", "upbeat minimal electronic, 120 BPM, crisp hi-hats, soft sub bass, bright synth plucks, optimistic and modern"),
    ("synthwave", "driving synthwave pulse, 110 BPM, arpeggiated analog synths, steady kick, confident tech-launch energy"),
    ("bossa-house", "Brazilian electronic bossa groove, 118 BPM, light nylon guitar chops, shaker, deep house kick, warm and sophisticated"),
    ("future-garage", "future garage beat, half-time feel, airy pads, chopped percussion, sleek night-city vibe"),
    ("lofi-house", "lo-fi house, 122 BPM, dusty drums, mellow electric piano chords, relaxed but moving"),
    ("minimal-techno", "minimal techno groove, 124 BPM, tight kick and clap, hypnotic synth stab, clean and focused"),
    ("nu-disco", "funky nu-disco, 116 BPM, synth bass, disco hi-hats, playful and positive"),
    ("afro-house", "afro house percussion bed, 120 BPM, organic congas and shakers, subtle marimba, energetic and warm"),
    ("tech-pulse", "cinematic tech pulse, 100 BPM, ticking percussion, evolving synth textures, curious and positive"),
    ("chillhop", "chillhop beat, 90 BPM, soft boom-bap drums, jazzy keys, smooth and curious"),
    ("electro-pop", "electro pop, 118 BPM, bouncy bass, glossy synth chords, bright and youthful"),
    ("uk-garage", "UK garage shuffle, 130 BPM, swung hi-hats, warm organ stabs, fresh and urban"),
    ("funk-br", "Brazilian funk inspired light percussion groove, tamborzao rhythm, clean synth bass, fun and energetic"),
    ("ambient-pulse", "ambient electronic pulse, 105 BPM, glassy plucks, soft kick, calm and premium"),
    ("indie-electronic", "indie electronic groove, 112 BPM, live-feel drums, clean guitar arpeggio, optimistic and human"),
]


def gerar(prompt: str, seed: int) -> bytes:
    cred, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    cred.refresh(Request())
    url = (f"https://{GCP_LOCATION}-aiplatform.googleapis.com/v1/projects/{GCP_PROJECT}"
           f"/locations/{GCP_LOCATION}/publishers/google/models/{MODELO}:predict")
    r = requests.post(url, timeout=300, headers={
        "Authorization": f"Bearer {cred.token}", "x-goog-user-project": GCP_PROJECT},
        json={"instances": [{"prompt": prompt, "negative_prompt": NEGATIVO, "seed": seed}], "parameters": {}})
    if r.status_code != 200:
        raise RuntimeError(f"Lyria respondeu HTTP {r.status_code}: {r.text[:400]}")
    pred = r.json()["predictions"][0]
    conteudo = pred.get("bytesBase64Encoded") or pred.get("audioContent")
    if not conteudo:
        raise RuntimeError(f"resposta sem áudio; chaves: {list(pred)}")
    return base64.b64decode(conteudo)


def estender(wav: Path, destino: Path) -> None:
    filtro = ("[0:a][1:a]acrossfade=d=2:c1=tri:c2=tri[a];[a][2:a]acrossfade=d=2:c1=tri:c2=tri,"
              "loudnorm=I=-18:TP=-2:LRA=11")
    subprocess.run([binario("ffmpeg"), "-y", "-loglevel", "error", "-i", str(wav), "-i", str(wav), "-i", str(wav),
                    "-filter_complex", filtro, "-ar", "48000", "-c:a", "aac", "-b:a", "192k", str(destino)],
                   check=True)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--quantas", type=int, default=len(ESTILOS))
    args = ap.parse_args()

    PASTA.mkdir(exist_ok=True)
    registro_path = PASTA / "trilhas.json"
    registro = json.loads(registro_path.read_text("utf-8")) if registro_path.exists() else {}
    for n, (nome, estilo) in enumerate(ESTILOS[:args.quantas], start=1):
        destino = PASTA / f"trilha-{n:02d}-{nome}.m4a"
        if destino.exists():
            log(f"já existe: {destino.name}")
            continue
        log(f"gerando {destino.name}")
        # O Lyria às vezes devolve 500 "try a different prompt": troca a semente e, depois, enxuga o prompt.
        tentativas = [(f"{BASE}. {estilo}.", 1000 + n), (f"{BASE}. {estilo}.", 2000 + n),
                      (f"Instrumental {estilo}.", 3000 + n)]
        audio = None
        for prompt, seed in tentativas:
            try:
                audio = gerar(prompt, seed)
                break
            except RuntimeError as e:
                log(f"  falhou (seed {seed}): {str(e)[:120]}")
        if audio is None:
            log(f"  pulando {destino.name}")
            continue
        with tempfile.TemporaryDirectory() as tmp:
            wav = Path(tmp) / "clip.wav"
            wav.write_bytes(audio)
            estender(wav, destino)
        # procedência, para responder "de onde veio essa música?" se alguma rede perguntar
        registro[destino.name] = {"modelo": f"Vertex AI {MODELO}", "prompt": prompt, "seed": seed,
                                  "gerado_em": date.today().isoformat()}
        registro_path.write_text(json.dumps(registro, ensure_ascii=False, indent=2), "utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
