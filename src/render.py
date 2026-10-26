"""Filma o vídeo: uma página HTML com todas as cenas, a legenda e a barra de
progresso, fotografada quadro a quadro pelo Chrome e enviada direto ao ffmpeg.

Tipografia, cor e margem saem de CSS, a mesma regra do Carousel_Plus: modelo
de imagem desenha imagem, nunca texto. O relógio das animações é o seek(t)
da página, então o mesmo roteiro sempre gera o mesmo vídeo.

Cada notícia é uma cena; cada frase depois da primeira acende um "destaque"
(número contando ou palavra-chave) sobre a imagem. É o que troca a tela a
cada 3-4 segundos.
"""
from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .util import ROOT, binario, log, nome_fonte

FPS = 30
LARGURA, ALTURA = 1080, 1920
LEAD = 0.35       # silêncio antes da primeira palavra: o 1º quadro fica limpo para virar capa
CAUDA = 1.4       # respiro depois da última palavra
ANTECIPA = 0.12   # a tela troca um instante antes da voz
TEMPLATES = ROOT / "templates"

# Sem verde e amarelo: precisam funcionar também sobre o off-white.
CORES = ["#DC0C9F", "#1291E2", "#FB5B12", "#7C16DB"]
ROTULOS = {"manchete": "Manchete", "secundaria": "Destaque", "sinal": "Sinal do dia"}
DIAS = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]
MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
# número solto, nunca grudado em letra: "3D", "4K" e "5G" não contam de zero
_NUM_TELA = re.compile(r"(?<!\w)(?:\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:,\d+)?)(?!\w)")


def destaque(texto: str) -> dict:
    """Separa o número da tela para a contagem animada: "US$ 10,3 bilhões" -> "US$ " + 10,3 + " bilhões"."""
    m = _NUM_TELA.search(texto)
    if not m:
        return {"texto": texto}
    inteiro, _, decimais = m.group(0).partition(",")
    valor = float(inteiro.replace(".", "") + (f".{decimais}" if decimais else ""))
    if not decimais and "." not in inteiro and 1900 <= valor <= 2100:
        return {"texto": texto}  # ano não conta de zero até 2030
    return {"pre": texto[:m.start()], "numero": m.group(0), "valor": valor, "casas": len(decimais),
            "suf": texto[m.end():]}


def montar_cenas(edicao: dict, itens: list[dict], rot: dict, alinhamento: dict,
                 imagens: dict[str, str]) -> tuple[list[dict], float]:
    """imagens: {id do item: arquivo na pasta do render}. Item sem imagem usa o número grande."""
    total = round(LEAD + alinhamento["duracao"] + CAUDA, 3)
    blocos = {b["id"]: b for b in alinhamento["blocos"]}
    roteiro_itens = {x["id"]: x for x in rot["itens"]}
    d = date.fromisoformat(edicao["data"])

    def inicio(bloco: str) -> float:
        return LEAD + blocos[bloco]["ini"] - ANTECIPA

    cenas = [{"tipo": "abertura", "tema": "escuro", "cor": "#E8F102", "titulo": rot["gancho"],
              "fundo": imagens.get(itens[0]["id"]),
              "data": f"{DIAS[d.weekday()]} · {d.day:02d} {MESES[d.month - 1]} {d.year}",
              "n_itens": len(itens), "_ini": 0.0}]
    for k, item in enumerate(itens):
        # temas alternam terminando em escuro, porque o fecho é claro
        tema = "claro" if (len(itens) - 1 - k) % 2 else "escuro"
        manchete = item["papel"] == "manchete"
        frases = roteiro_itens[item["id"]]["frases"]
        cenas.append({
            "tipo": "noticia", "tema": tema, "cor": CORES[k % len(CORES)], "manchete": manchete,
            "chip": "Manchete" if manchete else f"{k + 1:02d} · {ROTULOS[item['papel']]}",
            "num": f"{k + 1:02d}", "titulo": item["titulo"], "fonte": nome_fonte(item["link"]),
            "img": imagens.get(item["id"]), "_ini": inicio(f"{item['id']}#0"),
            "_beats": [(inicio(f"{item['id']}#{j}"), f["tela"]) for j, f in enumerate(frases) if j and f["tela"]],
        })
    cenas.append({"tipo": "fecho", "tema": "claro", "cor": "#E8F102", "_ini": inicio("fecho")})

    inicios = [c.pop("_ini") for c in cenas]
    for i in range(1, len(inicios)):
        inicios[i] = max(inicios[i], inicios[i - 1] + 0.5)
    for i, c in enumerate(cenas):
        c["ini"] = round(inicios[i], 3)
        c["fim"] = round(inicios[i + 1], 3) if i + 1 < len(cenas) else total
        c["dur_ms"] = int((c["fim"] - c["ini"]) * 1000)
        # destaque só entra se couber: nem colado na abertura da cena, nem no fim
        c["beats"] = [{**destaque(tela), "ini_ms": int((t - c["ini"]) * 1000)}
                      for t, tela in c.pop("_beats", []) if 0.4 < t - c["ini"] < c["fim"] - c["ini"] - 0.6]
    return cenas, total


def legendas(palavras: list[dict], max_palavras: int = 3, max_letras: int = 18) -> list[dict]:
    """Blocos de até 3 palavras, quebrando na pontuação e na troca de frase.

    Gancho e fecho não levam legenda: o texto deles já está escrito grande na tela.
    """
    grupos: list[list[dict]] = []
    atual: list[dict] = []
    for p in palavras:
        if p["bloco"] in ("gancho", "fecho"):
            continue
        texto = p["t"].strip(".,;:—–\"“”'()")
        if not texto:
            continue
        cheio = (len(atual) >= max_palavras or sum(len(x["t"]) + 1 for x in atual) + len(texto) > max_letras)
        if atual and (cheio or atual[-1]["bloco"] != p["bloco"]):
            grupos.append(atual)
            atual = []
        atual.append({"t": texto, "ini": round(p["ini"] + LEAD, 3), "fim": round(p["fim"] + LEAD, 3),
                      "bloco": p["bloco"]})
        if re.search(r"[.!?;:]$", p["t"]):
            grupos.append(atual)
            atual = []
    if atual:
        grupos.append(atual)

    out = []
    for i, g in enumerate(grupos):
        fim = g[-1]["fim"] + 0.3
        if i + 1 < len(grupos):
            proximo = grupos[i + 1][0]["ini"]
            fim = proximo if proximo - g[-1]["fim"] < 0.7 else min(fim, proximo)
        out.append({"ini": g[0]["ini"], "fim": round(fim, 3),
                    "palavras": [{"t": x["t"], "ini": x["ini"]} for x in g]})
    return out


def _abrir_navegador(p):
    opcoes = {"args": ["--font-render-hinting=none", "--disable-lcd-text", "--allow-file-access-from-files"]}
    if not Path(p.chromium.executable_path).is_file():
        opcoes["channel"] = "chrome"  # sem o Chromium do Playwright, usa o Chrome instalado
    return p.chromium.launch(**opcoes)


def filmar(pasta: Path, edicao: dict, cenas: list[dict], blocos_legenda: list[dict], total: float,
           arquivos: dict[str, Path], trecho: tuple[float, float] | None = None,
           destino: Path | None = None) -> tuple[Path, Path | None, list[str]]:
    """arquivos: {nome usado no HTML: caminho de origem} das imagens da edição.

    trecho=(ini, fim) filma só esse pedaço, numa pasta de render própria e sem
    capa: é o que a prévia de cena usa, e pode rodar junto com o vídeo inteiro.
    """
    from playwright.sync_api import sync_playwright

    render_dir = pasta / ("render" if trecho is None else "render-trecho")
    render_dir.mkdir(exist_ok=True)
    for f in (TEMPLATES / "fonts").iterdir():
        shutil.copy2(f, render_dir / f.name)
    for nome, origem in arquivos.items():
        shutil.copy2(origem, render_dir / nome)

    dados = {"duracao": total, "legendas": blocos_legenda,
             "cenas": [{k: c[k] for k in ("tipo", "tema", "ini", "fim")} for c in cenas]}
    env = Environment(loader=FileSystemLoader(str(TEMPLATES)), autoescape=select_autoescape(["html"]))
    html = env.get_template("video.html").render(
        data=edicao["data"], cenas=cenas,
        dados_json=json.dumps(dados, ensure_ascii=False).replace("</", "<\\/"))
    pagina = render_dir / "video.html"
    pagina.write_text(html, "utf-8")

    mudo = destino or pasta / "_mudo.mp4"
    capa = None if trecho else pasta / "capa.jpg"
    primeiro, ultimo = ((math.floor(trecho[0] * FPS), math.ceil(trecho[1] * FPS)) if trecho
                        else (0, math.ceil(total * FPS)))
    with sync_playwright() as p:
        navegador = _abrir_navegador(p)
        try:
            pag = navegador.new_page(viewport={"width": LARGURA, "height": ALTURA}, device_scale_factor=1)
            pag.goto(pagina.as_uri())
            pag.wait_for_function("window.__pronto === true", timeout=60000)
            if not pag.evaluate("window.__fontes.anton"):
                raise RuntimeError("a fonte Anton não carregou; o vídeo sairia com fonte errada")
            if not pag.evaluate("window.__imagens"):
                raise RuntimeError("alguma imagem não carregou")
            estouros = pag.evaluate("window.__estouros")

            if capa:
                pag.evaluate("t => seek(t)", 0)
                pag.screenshot(path=str(capa), type="jpeg", quality=95)

            ffmpeg = subprocess.Popen(
                [binario("ffmpeg"), "-y", "-loglevel", "error",
                 "-f", "image2pipe", "-framerate", str(FPS), "-c:v", "mjpeg", "-i", "-",
                 "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-profile:v", "high",
                 "-pix_fmt", "yuv420p", "-r", str(FPS), str(mudo)],
                stdin=subprocess.PIPE)
            try:
                marco = max(1, (ultimo - primeiro) // 5)
                for n in range(primeiro, ultimo):
                    pag.evaluate("t => seek(t)", n / FPS)
                    ffmpeg.stdin.write(pag.screenshot(type="jpeg", quality=94))
                    feitos = n - primeiro
                    if feitos and feitos % marco == 0:
                        log(f"  quadro {feitos}/{ultimo - primeiro}")
            finally:
                ffmpeg.stdin.close()
                codigo = ffmpeg.wait()
            if codigo != 0:
                raise RuntimeError(f"ffmpeg terminou com código {codigo}")
        finally:
            navegador.close()
    return mudo, capa, estouros
