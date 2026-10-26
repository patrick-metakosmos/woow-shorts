"""Utilidades comuns: log, fuso de Brasília, ffmpeg, normalização de texto e nomes de fonte."""
from __future__ import annotations

import glob
import os
import re
import shutil
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

ROOT = Path(__file__).resolve().parent.parent
BRT = timezone(timedelta(hours=-3))  # o Brasil não tem horário de verão desde 2019

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")

NOMES_FONTE = {
    "meioemensagem.com.br": "Meio & Mensagem",
    "fastcompany.com": "Fast Company",
    "digitalcommerce360.com": "Digital Commerce 360",
    "arinsider.co": "AR Insider",
    "glossy.co": "Glossy",
    "retaildive.com": "Retail Dive",
    "practicalecommerce.com": "Practical Ecommerce",
    "marketingdive.com": "Marketing Dive",
    "digiday.com": "Digiday",
    "roadtovr.com": "Road to VR",
    "uploadvr.com": "UploadVR",
    "propmark.com.br": "Propmark",
    "consumidormoderno.com.br": "Consumidor Moderno",
    "venturebeat.com": "VentureBeat",
    "businessoffashion.com": "Business of Fashion",
    "modernretail.co": "Modern Retail",
    "techcrunch.com": "TechCrunch",
    "theverge.com": "The Verge",
}

# Palavras com maiúscula que não são fato checável: a marca da própria news e siglas genéricas.
IGNORAR = {"woow", "daily", "drops", "drop", "metakosmos", "ia", "ai", "vr", "ar", "xr", "ceo", "app", "apps",
           "2d", "3d", "4k", "5g"}

# Nomes geográficos mudam na tradução (EUA x U.S.): são checados contra a edição, não contra a fonte.
GEOGRAFIA = {
    "estados", "unidos", "eua", "brasil", "brasileiro", "brasileira", "brasileiros", "brasileiras",
    "china", "chines", "chinesa", "chineses", "europa", "europeu", "europeia", "japao", "japones",
    "coreia", "coreano", "coreana", "asia", "asiatico", "asiatica", "india", "mexico", "alemanha",
    "franca", "reino", "unido", "america", "latina", "norte", "sul",
}

MULTIPLICADORES = {
    "mil": 1e3, "thousand": 1e3,
    "milhao": 1e6, "milhoes": 1e6, "million": 1e6,
    "bilhao": 1e9, "bilhoes": 1e9, "billion": 1e9,
    "trilhao": 1e12, "trilhoes": 1e12, "trillion": 1e12,
}
_NUMERO = re.compile(
    r"(\d[\d.,]*\d|\d)(\s*(?:mil|milh[õo]es|milh[ãa]o|bilh[õo]es|bilh[ãa]o|trilh[õo]es|trilh[ãa]o"
    r"|thousand|million|billion|trillion)\b)?",
    re.IGNORECASE)
_FRASE = re.compile(r"(?<=[.!?:])\s+|\n+")
_PALAVRA = re.compile(r"\w[\w'’-]*")


def log(msg: str) -> None:
    print(f"[{datetime.now(BRT):%H:%M:%S}] {msg}", flush=True)


def hoje_brt() -> str:
    return datetime.now(BRT).strftime("%Y-%m-%d")


def binario(nome: str) -> str:
    """ffmpeg/ffprobe: variável FFMPEG_BIN/FFPROBE_BIN, PATH ou o build solto em Downloads."""
    env = os.environ.get(f"{nome.upper()}_BIN")
    if env:
        return env
    achado = shutil.which(nome)
    if achado:
        return achado
    for candidato in glob.glob(str(Path.home() / "Downloads" / "ffmpeg-*" / "**" / "bin" / f"{nome}.exe"),
                               recursive=True):
        return candidato
    raise RuntimeError(f"{nome} não encontrado (defina {nome.upper()}_BIN)")


def sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def token(palavra: str) -> str:
    """Forma de comparação: minúscula, sem acento, sem pontuação; 1.999 e 1,999 viram 1999."""
    s = sem_acento(palavra.lower())
    s = re.sub(r"(?<=\d)[.,](?=\d)", "", s)
    return re.sub(r"\W", "", s)


def vocabulario(texto: str) -> set[str]:
    """Todas as formas de comparação de um texto. "Apple's" entra como apples, apple e s."""
    out = set()
    for w in texto.split():
        out.add(token(w))
        base = re.sub(r"(?<=\d)[.,](?=\d)", "", sem_acento(w.lower()))
        out.update(p for p in re.split(r"\W+", base) if p)
    out.discard("")
    return out


def mencoes_numericas(texto: str) -> list[tuple[str, set[str]]]:
    """Cada número citado, com as formas equivalentes: "US$ 3 mil" -> {"3", "3000"}."""
    out = []
    for m in _NUMERO.finditer(texto):
        bruto = m.group(1)
        digitos = re.sub(r"[.,]", "", bruto)
        formas = {digitos}
        if m.group(2):
            mult = MULTIPLICADORES.get(sem_acento(m.group(2).strip().lower()))
            if mult:
                decimal = re.fullmatch(r"(\d+)[.,](\d{1,2})", bruto)
                valor = float(f"{decimal.group(1)}.{decimal.group(2)}") if decimal else float(digitos)
                formas.add(str(round(valor * mult)))
        out.append((m.group(0).strip(), formas))
    return out


def nomes_proprios(texto: str) -> dict[str, str]:
    """Palavras com maiúscula fora do início de frase, mais siglas e grafias como iPhone.

    Início de frase é ambíguo ("Apple" x "Agora"), então ali só conta palavra
    com maiúscula interna. Devolve {forma de comparação: grafia original}.
    """
    out: dict[str, str] = {}
    for frase in _FRASE.split(texto):
        for i, w in enumerate(_PALAVRA.findall(frase)):
            if not any(c.isupper() for c in w):
                continue
            if i == 0 and w[0].isupper() and w[1:] == w[1:].lower():
                continue
            t = token(w)
            if len(t) >= 2 and t not in IGNORAR and not t.isdigit():
                out.setdefault(t, w)
    return out


def normalizar_url(url: str) -> str:
    """Chave estável de uma matéria: sem www, sem utm_*, sem barra final."""
    p = urlparse(url.strip())
    host = p.netloc.lower().removeprefix("www.")
    query = urlencode([(k, v) for k, v in parse_qsl(p.query) if not k.lower().startswith("utm_")])
    return urlunparse(("https", host, p.path.rstrip("/") or "/", "", query, ""))


def dominio(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def nome_fonte(url: str) -> str:
    d = dominio(url)
    return NOMES_FONTE.get(d, d)
