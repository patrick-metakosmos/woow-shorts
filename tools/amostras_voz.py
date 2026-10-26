"""Compara vozes com o MESMO trecho curto, sem gerar vídeo.

    python tools/amostras_voz.py --voz google:Puck --voz elevenlabs:BfVTsMbf1qKjW9oiRow9
    python tools/amostras_voz.py --listar            # vozes da conta ElevenLabs (chave com Voices: Read)

Cada voz lê o gancho e a 1ª frase da manchete de 2026-09-11, já acelerada como
no vídeo (--velocidade, padrão 1.12). Em output/amostras-voz/ fica só uma
amostra por voz (<motor>-<voz>.m4a). A narração crua fica em output/_cache-voz/,
então repetir a comparação não paga de novo.
"""
from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src import elevenlabs, narracao  # noqa: E402
from src.util import ROOT, binario, log  # noqa: E402

TRECHO = ("E se o ChatGPT tentasse te vender alguma coisa no meio da conversa? "
          "A Amazon fechou parceria com a OpenAI para vender anúncios no ChatGPT.")
PASTA = ROOT / "output" / "amostras-voz"
CACHE = ROOT / "output" / "_cache-voz"


def _rotulo(motor: str, voz: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in f"{motor}-{voz}")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--voz", action="append", default=[], help="motor:voz, ex. google:Puck ou elevenlabs:<id>")
    ap.add_argument("--velocidade", type=float, default=1.12)
    ap.add_argument("--listar", action="store_true")
    args = ap.parse_args()

    if args.listar:
        for v in sorted(elevenlabs.vozes(), key=lambda v: (v.get("category", ""), v["name"])):
            rotulos = ", ".join(f"{k}: {val}" for k, val in (v.get("labels") or {}).items() if val)
            print(f"{v['name']:<28} {v.get('category', ''):<12} {v['voice_id']}  {rotulos}")
        return 0
    if not args.voz:
        ap.error("diga ao menos uma --voz motor:voz")

    PASTA.mkdir(parents=True, exist_ok=True)
    CACHE.mkdir(parents=True, exist_ok=True)
    marca = hashlib.sha1(TRECHO.encode("utf-8")).hexdigest()[:8]
    for pedido in args.voz:
        motor, _, voz = pedido.partition(":")
        if motor not in ("google", "elevenlabs") or not voz:
            ap.error(f"'{pedido}' não é motor:voz (motor = google ou elevenlabs)")
        rotulo = _rotulo(motor, voz)
        crua = CACHE / f"{rotulo}-{marca}.wav"
        if not crua.exists():
            log(f"narrando {rotulo}")
            narracao.narrar(TRECHO, crua, voz, motor)
        acelerada = CACHE / f"{rotulo}-acelerada.wav"
        narracao.acelerar(crua, acelerada, args.velocidade)
        final = PASTA / f"{rotulo}.m4a"
        subprocess.run([binario("ffmpeg"), "-y", "-loglevel", "error", "-i", str(acelerada),
                        "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-ar", "48000", "-c:a", "aac", "-b:a", "192k",
                        str(final)], check=True)
        acelerada.unlink()
        log(f"  {final.name}: {narracao.duracao(final):.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
