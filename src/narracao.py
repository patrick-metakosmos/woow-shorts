"""Narração com Gemini-TTS (Google Cloud Text-to-Speech).

Mesmo motor do Video_Image_Plus; troca a persona: sai o documentarista
contemplativo, entra quem apresenta a news do dia em menos de um minuto.
"""
from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path

from .util import binario, log

VOZ_PADRAO = "Puck"
MODELO = "gemini-2.5-pro-tts"
ESTILO = (
    "You are the host of a fast daily news short for Instagram Reels and YouTube Shorts, "
    "speaking native Brazilian Portuguese. You cover retail, e-commerce, AI and immersive tech.\n\n"
    "ENERGY: confident, warm and curious, with a light smile in the voice, like a smart friend "
    "telling you the most interesting things that happened today. Never a radio-announcer cliche, "
    "never shouting, never exaggerated drama.\n\n"
    "PACE: brisk, around 165 words per minute, but every word crystal clear. Tiny breaths at commas, "
    "a clear beat at periods. The very first sentence is the hook: deliver it with extra punch so it "
    "grabs attention in the first second.\n\n"
    "EMPHASIS: lean into company names, numbers and the surprising part of each story. "
    "When a new story starts, reset the energy slightly so the change of topic is audible.\n\n"
    "The text contains only words to be spoken. Trust the punctuation."
)


def para_fala(texto: str) -> str:
    """Valores monetários por extenso da moeda: o TTS lê "US$" de jeito imprevisível."""
    texto = re.sub(r"US\$\s*([\d.,]+)", r"\1 dólares", texto)
    return re.sub(r"R\$\s*([\d.,]+)", r"\1 reais", texto)


def duracao(caminho: Path) -> float:
    r = subprocess.run([binario("ffprobe"), "-v", "quiet", "-show_entries", "format=duration",
                        "-of", "csv=p=0", str(caminho)], capture_output=True, text=True, check=True)
    return float(r.stdout.strip())


def acelerar(bruta: Path, destino: Path, velocidade: float) -> float:
    """Acelera sem mudar o tom (atempo). Pedir ao TTS para "falar mais rápido" nem sempre obedece."""
    subprocess.run([binario("ffmpeg"), "-y", "-loglevel", "error", "-i", str(bruta),
                    "-af", f"atempo={velocidade:.3f}", str(destino)], check=True)
    return duracao(destino)


def _narrar_elevenlabs(texto: str, destino: Path, voz: str) -> float:
    from . import elevenlabs
    voice_id, nome = elevenlabs.resolver_voz(voz)
    mp3 = destino.with_suffix(".mp3")
    mp3.write_bytes(elevenlabs.falar(para_fala(texto), voice_id))
    subprocess.run([binario("ffmpeg"), "-y", "-loglevel", "error", "-i", str(mp3), "-ar", "48000", str(destino)],
                   check=True)
    mp3.unlink()
    segundos = duracao(destino)
    log(f"  narração ElevenLabs ({nome}): {segundos:.1f}s")
    return segundos


def narrar(texto: str, destino: Path, voz: str = VOZ_PADRAO, motor: str = "google") -> float:
    if motor == "elevenlabs":
        return _narrar_elevenlabs(texto, destino, voz)
    from google.cloud import texttospeech as tts

    cliente = tts.TextToSpeechClient()
    fala = para_fala(texto)
    audio = tts.AudioConfig(audio_encoding=tts.AudioEncoding.LINEAR16, sample_rate_hertz=48000)
    motores = [
        ("Gemini-TTS", tts.SynthesisInput(text=fala, prompt=ESTILO),
         tts.VoiceSelectionParams(language_code="pt-BR", name=voz, model_name=MODELO)),
        ("Chirp3-HD", tts.SynthesisInput(text=fala),
         tts.VoiceSelectionParams(language_code="pt-BR", name=f"pt-BR-Chirp3-HD-{voz}")),
    ]
    ultimo_erro: Exception | None = None
    for nome, entrada, voz_params in motores:
        for tentativa in range(3):
            try:
                resp = cliente.synthesize_speech(input=entrada, voice=voz_params, audio_config=audio, timeout=300)
                destino.write_bytes(resp.audio_content)
                segundos = duracao(destino)
                log(f"  narração {nome} ({voz}): {segundos:.1f}s")
                return segundos
            except Exception as e:
                ultimo_erro = e
                log(f"  {nome} falhou (tentativa {tentativa + 1}/3): {str(e)[:160]}")
                time.sleep(10 * (tentativa + 1))
    raise RuntimeError(f"TTS indisponível: {ultimo_erro}")
