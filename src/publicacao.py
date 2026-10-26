"""Sobe o vídeo do dia e avisa o cenário do Make, que publica nas redes.

O MP4 vai para um bucket público (mk-woow-shorts-videos, objeto expira em 30
dias) porque Instagram e LinkedIn baixam o vídeo de uma URL. O YouTube recebe
o arquivo em si, e quem baixa da URL é o próprio Make.

Trava de repetição: `output/<data>/.publicado.json`. Enquanto esse arquivo
existir, o dia NÃO é publicado de novo. O e-mail duplicado de 16/09 nasceu de
não existir uma trava assim, então aqui ela é a primeira coisa checada.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import requests

from .narracao import duracao
from .util import BRT, ROOT, log

BUCKET = os.environ.get("WOOW_BUCKET", "mk-woow-shorts-videos")
BASE_PUBLICA = f"https://storage.googleapis.com/{BUCKET}"
DURACAO_MIN, DURACAO_MAX = 20.0, 180.0   # Reels aceita de 3s a 15min; fora disso é bug nosso
TAMANHO_MAX = 900 * 1024 * 1024          # o limite do Instagram é 1 GB


def env(nome: str, padrao: str = "") -> str:
    """Variável de ambiente ou linha do .env (mesmo esquema da chave da ElevenLabs)."""
    valor = os.environ.get(nome, "").strip()
    arquivo = ROOT / ".env"
    if not valor and arquivo.exists():
        for linha in arquivo.read_text("utf-8").splitlines():
            chave, _, resto = linha.partition("=")
            if chave.strip() == nome:
                valor = resto.strip().strip("\"'")
    return valor or padrao


def _gcloud() -> str:
    achado = shutil.which("gcloud") or shutil.which("gcloud.cmd")
    if not achado:
        raise RuntimeError("gcloud não encontrado no PATH")
    return achado


def _textos(pasta: Path) -> dict:
    """Os textos por rede que o pipeline já gerou em post/."""
    post = pasta / "post"
    faltando = [n for n in ("instagram.txt", "linkedin.txt", "youtube.txt") if not (post / n).exists()]
    if faltando:
        raise RuntimeError(f"faltam textos do post: {', '.join(faltando)}")
    youtube = (post / "youtube.txt").read_text("utf-8")
    titulo, _, descricao = youtube.partition("DESCRIÇÃO:")
    return {
        "instagram": (post / "instagram.txt").read_text("utf-8").strip(),
        "linkedin": (post / "linkedin.txt").read_text("utf-8").strip(),
        "linkedin_titulo": "WooW! Daily Drops",
        "youtube_titulo": titulo.replace("TÍTULO:", "").strip()[:100],
        "youtube_descricao": descricao.strip()[:5000],
    }


def _conferir(mp4: Path) -> float:
    if not mp4.exists():
        raise RuntimeError(f"não achei o vídeo {mp4.name}")
    tamanho = mp4.stat().st_size
    if tamanho > TAMANHO_MAX:
        raise RuntimeError(f"o vídeo tem {tamanho / 1024 / 1024:.0f} MB; o teto é 900 MB")
    segundos = duracao(mp4)
    if not DURACAO_MIN <= segundos <= DURACAO_MAX:
        raise RuntimeError(f"o vídeo tem {segundos:.1f}s, fora da faixa de {DURACAO_MIN:.0f} a {DURACAO_MAX:.0f}s")
    return segundos


def subir(pasta: Path, data: str) -> dict:
    """Copia MP4 e capa para o bucket e devolve as URLs públicas."""
    mp4 = pasta / f"woow-daily-drops-{data}.mp4"
    capa = pasta / "capa.jpg"
    destino = f"gs://{BUCKET}/{data}/"
    arquivos = [str(mp4)] + ([str(capa)] if capa.exists() else [])
    # A conta vai explícita no comando: sem isso o gcloud usa a configuração ATIVA
    # da máquina, e qualquer outra automação que rode `gcloud config set account`
    # derruba o upload daqui. Foi o que travou o pipeline de 12/10 a 21/10/2026 —
    # a ativa virou uma conta de fora, com projeto de faturamento encerrado.
    conta = env("WOOW_GCLOUD_CONTA", "patrick@metakosmos.com.br")
    cmd = [_gcloud(), f"--account={conta}", "storage", "cp", *arquivos, destino]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=600)
    except subprocess.CalledProcessError as erro:
        # capture_output engole o stderr do gcloud: sem repassar, o log do dia só
        # mostrava "exit status 1" e o motivo real ficava invisível.
        raise RuntimeError(
            f"gcloud storage cp falhou (conta {conta}): "
            f"{(erro.stderr or '').strip() or 'sem stderr'}"
        ) from erro
    return {"video_url": f"{BASE_PUBLICA}/{data}/{mp4.name}",
            "capa_url": f"{BASE_PUBLICA}/{data}/{capa.name}" if capa.exists() else ""}


def publicar(pasta: Path, data: str, forcar: bool = False) -> dict:
    """Sobe o vídeo e dispara o cenário do Make. Devolve o que foi gravado no marcador."""
    marcador = pasta / ".publicado.json"
    if marcador.exists() and not forcar:
        anterior = json.loads(marcador.read_text("utf-8"))
        log(f"  já publicado em {anterior.get('quando')} — nada a fazer (use --republicar para forçar)")
        return anterior

    webhook = env("WOOW_MAKE_WEBHOOK")
    if not webhook:
        raise RuntimeError("falta WOOW_MAKE_WEBHOOK no .env")

    mp4 = pasta / f"woow-daily-drops-{data}.mp4"
    segundos = _conferir(mp4)
    log(f"  vídeo conferido: {segundos:.1f}s, {mp4.stat().st_size / 1024 / 1024:.1f} MB")

    urls = subir(pasta, data)
    log(f"  no bucket: {urls['video_url']}")

    payload = {"edicao": data, **urls, **_textos(pasta),
               "youtube_privacidade": env("WOOW_YOUTUBE_PRIVACIDADE", "unlisted")}
    # Rede listada em WOOW_PULAR_REDES sai do payload: sem o campo dela, o filtro
    # da rota no Make pula aquela publicação. É assim que o YouTube fica de fora
    # enquanto o upload dele não migra do Make para projeto próprio.
    for rede in (r.strip() for r in env("WOOW_PULAR_REDES").split(",") if r.strip()):
        for campo in [c for c in payload if c == rede or c.startswith(f"{rede}_")]:
            payload.pop(campo)
        log(f"  pulando {rede} (WOOW_PULAR_REDES)")
    resposta = requests.post(webhook, json=payload, timeout=120)
    if resposta.status_code != 200:
        raise RuntimeError(f"o Make respondeu HTTP {resposta.status_code}: {resposta.text[:200]}")

    registro = {"quando": datetime.now(BRT).isoformat(timespec="seconds"), **urls,
                "youtube_privacidade": payload["youtube_privacidade"],
                "resposta_make": resposta.text[:200]}
    marcador.write_text(json.dumps(registro, ensure_ascii=False, indent=2), "utf-8")
    log(f"  Make respondeu: {resposta.text[:80]}")
    return registro
