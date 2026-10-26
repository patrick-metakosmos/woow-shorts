"""ElevenLabs como motor alternativo de narração.

A chave vem de ELEVENLABS_API_KEY no ambiente ou no arquivo .env da raiz do
projeto (fora do git). Ela nunca é impressa nem gravada em log.
"""
from __future__ import annotations

import os
import re

import requests

from .util import ROOT

API = "https://api.elevenlabs.io/v1"
MODELO_PADRAO = "eleven_multilingual_v2"
# Estabilidade média: expressiva o bastante para news, sem variar o timbre entre frases.
AJUSTES = {"stability": 0.45, "similarity_boost": 0.8, "style": 0.25, "use_speaker_boost": True}


def chave() -> str:
    valor = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    arquivo = ROOT / ".env"
    if not valor and arquivo.exists():
        for linha in arquivo.read_text("utf-8").splitlines():
            nome, _, resto = linha.partition("=")
            if nome.strip() == "ELEVENLABS_API_KEY":
                valor = resto.strip().strip("\"'")
    if not valor:
        raise RuntimeError("falta a chave: cole ELEVENLABS_API_KEY no arquivo .env da pasta WooW_Shorts")
    return valor


def _erro(r: requests.Response) -> RuntimeError:
    return RuntimeError(f"ElevenLabs respondeu HTTP {r.status_code}: {r.text[:300]}")


def vozes() -> list[dict]:
    r = requests.get(f"{API}/voices", headers={"xi-api-key": chave()}, timeout=30)
    if r.status_code != 200:
        raise _erro(r)
    return r.json().get("voices", [])


def resolver_voz(voz: str) -> tuple[str, str]:
    """Aceita id ou nome (inteiro ou parte, sem diferenciar maiúscula). Devolve (id, nome)."""
    try:
        lista = vozes()
    except RuntimeError:
        # chave sem permissão de listar vozes: se parece um id, usa direto
        if re.fullmatch(r"[A-Za-z0-9]{16,}", voz):
            return voz, voz
        raise
    for v in lista:
        if voz == v["voice_id"] or voz.lower() == v["name"].lower():
            return v["voice_id"], v["name"]
    parecidas = [v for v in lista if voz.lower() in v["name"].lower()]
    if len(parecidas) == 1:
        return parecidas[0]["voice_id"], parecidas[0]["name"]
    nomes = ", ".join(v["name"] for v in (parecidas or lista))
    raise RuntimeError(f"voz '{voz}' não encontrada (ou ambígua) na conta ElevenLabs. Opções: {nomes}")


def falar(texto: str, voice_id: str, modelo: str = MODELO_PADRAO) -> bytes:
    """MP3 44,1 kHz 128 kbps: o formato que qualquer plano da ElevenLabs entrega."""
    r = requests.post(f"{API}/text-to-speech/{voice_id}", params={"output_format": "mp3_44100_128"},
                      headers={"xi-api-key": chave(), "Accept": "audio/mpeg"},
                      json={"text": texto, "model_id": modelo, "voice_settings": AJUSTES}, timeout=180)
    if r.status_code != 200:
        raise _erro(r)
    return r.content
