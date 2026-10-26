"""Lê a edição publicada no bucket público e devolve os itens estruturados.

Não passa pelo broker: o /queue exige login que expira em 12h e mataria a
rodada automática. O HTML do bucket é o mesmo que foi para a lista, e o
template marca cada seção com um comentário fixo (MANCHETE, SECUNDÁRIA n,
SINAL n). Se o template mudar, a leitura falha alto em vez de inventar.
"""
from __future__ import annotations

import re

import requests
from bs4 import BeautifulSoup

from .util import UA

URL = "https://storage.googleapis.com/mk-woow-news-public/nl/{data}.html"
MESES = {"janeiro": 1, "fevereiro": 2, "março": 3, "marco": 3, "abril": 4, "maio": 5, "junho": 6,
         "julho": 7, "agosto": 8, "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12}
_MARCADOR = re.compile(r"<!--\s*=+\s*(.+?)\s*=+\s*-->")
_SECAO_ITEM = re.compile(r"^(MANCHETE|SECUND[ÁA]RIA (\d)|SINAL (\d))$")


class EdicaoIndisponivel(Exception):
    """A edição do dia ainda não está no bucket."""


class TemplateMudou(Exception):
    """O HTML não tem a estrutura esperada."""


def _limpo(texto: str) -> str:
    texto = re.sub(r"\s+", " ", texto).strip()
    return re.sub(r"\s+([.,;:!?])", r"\1", texto)


def baixar(data: str) -> str:
    r = requests.get(URL.format(data=data), headers={"User-Agent": UA}, timeout=30)
    if r.status_code in (403, 404):  # o GCS responde 403 para objeto inexistente sem listagem pública
        raise EdicaoIndisponivel(f"a edição {data} não está no bucket (HTTP {r.status_code})")
    r.raise_for_status()
    return r.content.decode("utf-8")


def ler(html: str, data: str) -> dict:
    partes = _MARCADOR.split(html)
    secoes = dict(zip((p.strip() for p in partes[1::2]), partes[2::2]))

    cabecalho = BeautifulSoup(secoes.get("CABEÇALHO", ""), "html.parser").get_text(" ")
    m = re.search(r"(\d{1,2}) de (\w+) de (\d{4})", cabecalho)
    if not m or m.group(2).lower() not in MESES:
        raise TemplateMudou("cabeçalho sem data reconhecível")
    data_html = f"{m.group(3)}-{MESES[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"
    if data_html != data:
        raise TemplateMudou(f"pedi a edição {data}, mas o HTML diz {data_html}")

    h1 = BeautifulSoup(secoes.get("TÍTULO DA EDIÇÃO", ""), "html.parser").find("h1")
    if not h1:
        raise TemplateMudou("sem título da edição")

    itens = []
    for nome, trecho in secoes.items():
        m = _SECAO_ITEM.match(nome)
        if not m:
            continue
        sopa = BeautifulSoup(trecho, "html.parser")
        cabeca = sopa.find(["h2", "h3"])
        if not cabeca:
            continue
        if m.group(1) == "MANCHETE":
            papel, ident = "manchete", "manchete"
        elif m.group(2):
            papel, ident = "secundaria", f"secundaria-{m.group(2)}"
        else:
            papel, ident = "sinal", f"sinal-{m.group(3)}"
        link = sopa.find("a", href=True)
        img = sopa.find("img", src=True)
        itens.append({
            "id": ident,
            "papel": papel,
            "titulo": _limpo(cabeca.get_text(" ")),
            "texto": _limpo(" ".join(p.get_text(" ") for p in sopa.find_all("p"))),
            "link": link["href"] if link else "",
            "imagem": img["src"] if (img and papel == "manchete") else "",
        })
    if not itens:
        raise TemplateMudou("nenhuma seção de item encontrada")
    return {"data": data, "titulo": _limpo(h1.get_text(" ")), "url": URL.format(data=data), "itens": itens}
