"""Travas do lado do vídeo, antes de qualquer coisa ir a público.

A news tem três defeitos conhecidos: link inventado (raiz de domínio ou
caminho que dá 404), matéria repetida em dias seguidos e nome ou número
trocado. Aqui: o link precisa abrir uma matéria de verdade, a matéria vira
base de conferência dos fatos, e um histórico próprio de URLs impede repetir
o que já saiu em vídeo.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from .util import ROOT, UA

HISTORICO = ROOT / "historico.json"
JANELA_DIAS = 7


def ler_fonte(link: str) -> dict:
    """Baixa a matéria original. ok=False diz por que ela não serve de base."""
    if not link:
        return {"ok": False, "motivo": "item sem link"}
    if urlparse(link).path.strip("/") == "":
        return {"ok": False, "motivo": "o link aponta para a página inicial do site, não para uma matéria"}
    try:
        r = requests.get(link, timeout=25, allow_redirects=True, headers={
            "User-Agent": UA, "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8"})
    except requests.RequestException as e:
        return {"ok": False, "motivo": f"a fonte não respondeu ({type(e).__name__})"}
    if r.status_code != 200:
        bloqueio = " (o site bloqueia robôs, não deu para conferir)" if r.status_code in (401, 403, 429) else ""
        return {"ok": False, "status": r.status_code, "motivo": f"a fonte respondeu HTTP {r.status_code}{bloqueio}"}
    if urlparse(r.url).path.strip("/") == "":
        return {"ok": False, "status": 200, "url_final": r.url, "motivo": "o link redireciona para a página inicial"}
    if "charset" not in r.headers.get("content-type", "").lower():
        r.encoding = r.apparent_encoding
    return {"ok": True, "status": 200, "url_final": r.url, "texto": _texto(r.text)}


def _texto(html: str) -> str:
    """Texto visível + metadados (og:description, JSON-LD), onde muita matéria com paywall guarda o lide."""
    sopa = BeautifulSoup(html, "html.parser")
    pedacos = [m["content"] for m in sopa.find_all("meta") if m.get("content")]
    pedacos += [s.get_text(" ") for s in sopa.find_all("script", type="application/ld+json")]
    for tag in sopa(["script", "style", "noscript", "svg"]):
        tag.decompose()
    pedacos.append(sopa.get_text(" "))
    return " ".join(" ".join(pedacos).split())


def urls_recentes(data: str) -> set[str]:
    """URLs normalizadas que já saíram em vídeo nos JANELA_DIAS dias anteriores a `data`."""
    if not HISTORICO.exists():
        return set()
    ref = date.fromisoformat(data)
    out: set[str] = set()
    for v in json.loads(HISTORICO.read_text("utf-8")).get("videos", []):
        if ref - timedelta(days=JANELA_DIAS) <= date.fromisoformat(v["data"]) < ref:
            out.update(v["urls"])
    return out


def registrar(data: str, urls: list[str]) -> None:
    hist = json.loads(HISTORICO.read_text("utf-8")) if HISTORICO.exists() else {"videos": []}
    hist["videos"] = [v for v in hist["videos"] if v["data"] != data] + [{"data": data, "urls": sorted(urls)}]
    hist["videos"].sort(key=lambda v: v["data"])
    HISTORICO.write_text(json.dumps(hist, ensure_ascii=False, indent=2), "utf-8")
