"""Áudio final (voz + trilha com ducking, -14 LUFS) e o MP4 entregue."""
from __future__ import annotations

import subprocess
from pathlib import Path

from .util import ROOT, binario

EXTENSOES_AUDIO = {".mp3", ".wav", ".m4a", ".ogg", ".flac"}


def escolher_musica(data: str) -> Path | None:
    """Uma faixa da pasta musica/, alternando por dia. Sem faixa, o vídeo sai só com a voz."""
    pasta = ROOT / "musica"
    faixas = sorted(p for p in pasta.iterdir() if p.suffix.lower() in EXTENSOES_AUDIO) if pasta.exists() else []
    return faixas[int(data.replace("-", "")) % len(faixas)] if faixas else None


def mixar(narracao: Path, destino: Path, total: float, lead: float, musica: Path | None) -> None:
    atraso = int(lead * 1000)
    voz = (f"[0:a]aformat=sample_rates=48000:channel_layouts=stereo,adelay={atraso}:all=1,"
           f"apad,atrim=0:{total:.3f}")
    if musica:
        filtro = (f"{voz},asplit=2[voz][chave];"
                  f"[1:a]aformat=sample_rates=48000:channel_layouts=stereo,atrim=0:{total:.3f},"
                  f"volume=0.30,afade=t=in:d=0.6,afade=t=out:st={max(0.0, total - 1.5):.3f}:d=1.5[trilha];"
                  "[trilha][chave]sidechaincompress=threshold=0.02:ratio=10:attack=15:release=350[fundo];"
                  "[voz][fundo]amix=inputs=2:duration=first:normalize=0,"
                  "loudnorm=I=-14:TP=-1.5:LRA=11[saida]")
        entradas = ["-i", str(narracao), "-stream_loop", "-1", "-i", str(musica)]
    else:
        filtro = f"{voz},loudnorm=I=-14:TP=-1.5:LRA=11[saida]"
        entradas = ["-i", str(narracao)]
    subprocess.run([binario("ffmpeg"), "-y", "-loglevel", "error", *entradas,
                    "-filter_complex", filtro, "-map", "[saida]", "-t", f"{total:.3f}",
                    "-ar", "48000", "-c:a", "aac", "-b:a", "192k", str(destino)], check=True)


def juntar(video_mudo: Path, audio: Path, destino: Path) -> None:
    subprocess.run([binario("ffmpeg"), "-y", "-loglevel", "error", "-i", str(video_mudo), "-i", str(audio),
                    "-map", "0:v", "-map", "1:a", "-c", "copy", "-shortest", "-movflags", "+faststart",
                    str(destino)], check=True)
