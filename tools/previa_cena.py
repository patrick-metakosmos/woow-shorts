"""Prévia rápida de uma cena, no template atual, sem refilmar o vídeo inteiro.

    python tools/previa_cena.py --edicao 2026-09-11            # 1ª notícia com destaque depois da manchete
    python tools/previa_cena.py --edicao 2026-09-11 --cena 3

Reaproveita roteiro, voz, alinhamento e imagens (nada é pago de novo) e grava
em output/<data>/previa/: cena.mp4, com o áudio do trecho, e cena.png com dois
momentos lado a lado, a 1ª frase e o destaque. Serve para testar ajuste visual
em ~20s; filma numa pasta própria, então pode rodar junto com o vídeo inteiro.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src import render  # noqa: E402
from src.util import ROOT, binario, log  # noqa: E402

LARGURA_QUADRO = 540


def _quadro(video: Path, segundo: float, destino: Path) -> Image.Image:
    subprocess.run([binario("ffmpeg"), "-y", "-loglevel", "error", "-ss", f"{segundo:.3f}", "-i", str(video),
                    "-frames:v", "1", str(destino)], check=True)
    with Image.open(destino) as img:
        return img.convert("RGB").resize((LARGURA_QUADRO, LARGURA_QUADRO * 16 // 9), Image.LANCZOS)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--edicao", required=True)
    ap.add_argument("--cena", type=int, default=0,
                    help="índice da cena; 0 = primeira notícia com destaque depois da manchete")
    args = ap.parse_args()

    pasta = ROOT / "output" / args.edicao
    ler = lambda nome: json.loads((pasta / nome).read_text("utf-8"))  # noqa: E731
    dados, rot, alin = ler("edicao.json"), ler("roteiro.json"), ler("alinhamento.json")
    itens = [next(i for i in dados["itens"] if i["id"] == iid) for iid in rot["itens_usados"]]

    nomes, arquivos = {}, {}
    if (pasta / "manchete.jpg").exists() and any(i["papel"] == "manchete" for i in itens):
        nomes["manchete"], arquivos["manchete.jpg"] = "manchete.jpg", pasta / "manchete.jpg"
    for png in sorted((pasta / "img").glob("*.png")):
        nomes[png.stem], arquivos[png.name] = png.name, png

    cenas, total = render.montar_cenas(dados, itens, rot, alin, nomes)
    cena = cenas[args.cena] if args.cena else next(
        c for c in cenas if c["tipo"] == "noticia" and not c["manchete"] and c["beats"])
    ini, fim = cena["ini"], cena["fim"]
    log(f"cena \"{cena.get('titulo', cena['tipo'])}\": {ini:.1f}s a {fim:.1f}s")

    saida = pasta / "previa"
    saida.mkdir(exist_ok=True)
    mudo = saida / "_mudo.mp4"
    render.filmar(pasta, dados, cenas, render.legendas(alin["palavras"]), total, arquivos,
                  trecho=(ini, fim), destino=mudo)
    video = saida / "cena.mp4"
    subprocess.run([binario("ffmpeg"), "-y", "-loglevel", "error", "-i", str(mudo),
                    "-ss", f"{ini:.3f}", "-t", f"{fim - ini:.3f}", "-i", str(pasta / "audio.m4a"),
                    "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-shortest", str(video)],
                   check=True)
    mudo.unlink()

    momentos = [1.2]
    if cena.get("beats"):
        momentos.append(cena["beats"][0]["ini_ms"] / 1000 + 1.0)
    margem, altura = 16, LARGURA_QUADRO * 16 // 9
    folha = Image.new("RGB", (len(momentos) * (LARGURA_QUADRO + margem) + margem, altura + 2 * margem),
                      (40, 40, 40))
    for n, segundo in enumerate(momentos):
        tmp = saida / f"_q{n}.png"
        folha.paste(_quadro(video, segundo, tmp), (margem + n * (LARGURA_QUADRO + margem), margem))
        tmp.unlink()
    folha.save(saida / "cena.png")
    log(f"pronto: {saida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
