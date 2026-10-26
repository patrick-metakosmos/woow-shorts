"""WooW! Daily Drops -> vídeo vertical curto (1080x1920, 50-60s).

    python woow_shorts.py                       # edição de hoje
    python woow_shorts.py --edicao 2026-09-10   # outra data
    python woow_shorts.py --refazer roteiro     # refaz do roteiro em diante
    python woow_shorts.py --refazer imagens     # gera as imagens de novo (roteiro e voz ficam)
    python woow_shorts.py --so-roteiro          # para depois do roteiro (revisão rápida)

Não publica nada: gera MP4, capa e o texto do post de cada rede em output/<data>/.
Código de saída: 0 vídeo pronto, 2 sem vídeo hoje (motivo no relatorio.json), 1 erro.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from pathlib import Path

import requests

from src import alinhamento, checagem, edicao as edicao_mod, imagens, montagem, narracao, render, roteiro
from src.util import ROOT, UA, hoje_brt, log, nome_fonte, normalizar_url

ETAPAS = ["edicao", "fontes", "roteiro", "narracao", "alinhamento", "imagens", "video"]
MIN_ITENS = 2
LINK_NEWS = os.environ.get("WOOW_LINK_NEWS", "COLE_O_LINK_AQUI")
HASHTAGS = "#WooWDailyDrops #metaKosmos #varejo #ecommerce #inteligenciaartificial #immersivecommerce"


class SemVideo(Exception):
    """Não há itens confiáveis suficientes: melhor nenhum vídeo que um vídeo errado."""


def salvar(caminho: Path, dados) -> None:
    caminho.write_text(json.dumps(dados, ensure_ascii=False, indent=2), "utf-8")


def carregar(caminho: Path):
    return json.loads(caminho.read_text("utf-8"))


def posts(edicao: dict, itens: list[dict], rot: dict, com_ia: bool) -> dict[str, str]:
    """Texto do post por rede. O vídeo é igual em todas; muda só onde o link funciona."""
    topicos = "\n".join(f"▸ {i['titulo']}" for i in itens)
    fontes = "Fontes: " + ", ".join(dict.fromkeys(nome_fonte(i["link"]) for i in itens))
    ia = "\nImagens ilustrativas geradas por IA." if com_ia else ""
    cta = "Curtiu? Compartilha com quem precisa ficar por dentro e segue pra não perder nenhum Drop."
    # Sem URL de inscrição, a linha inteira some: marcador não vai para post público.
    tem_link = LINK_NEWS.startswith("http")
    assina_yt = f"Receba a WooW! Daily Drops todo dia no seu e-mail: {LINK_NEWS}\n\n" if tem_link else ""
    assina_li = f"A edição completa chega todo dia no seu e-mail: {LINK_NEWS}\n\n" if tem_link else ""
    titulo_yt = f"{rot['gancho']} | WooW! Daily Drops"
    if len(titulo_yt) > 100:
        titulo_yt = rot["gancho"][:100]
    return {
        "instagram.txt": (f"{edicao['titulo']}\n\n{topicos}\n\n{cta}\n\n"
                          "A WooW! Daily Drops completa chega todo dia no seu e-mail: link na bio.\n\n"
                          f"{fontes}{ia}\n\n{HASHTAGS}\n"),
        "tiktok.txt": (f"{rot['gancho']}\n\n{cta}\n\n"
                       "News completa todo dia no e-mail: link no perfil.\n\n"
                       "#WooWDailyDrops #varejo #tecnologia #inteligenciaartificial\n"),
        "youtube.txt": (f"TÍTULO:\n{titulo_yt}\n\nDESCRIÇÃO:\n{edicao['titulo']}\n\n{topicos}\n\n"
                        f"{cta}\n\n{assina_yt}"
                        f"{fontes}{ia}\n\n#shorts {HASHTAGS}\n"),
        "linkedin.txt": (f"{edicao['titulo']}\n\nO giro de hoje da WooW! Daily Drops, em menos de 1 minuto:\n\n"
                         f"{topicos}\n\n{cta}\n\n{assina_li}"
                         f"{fontes}{ia}\n\n#varejo #ecommerce #inteligenciaartificial\n"),
    }


def executar(args, pasta: Path, rel: dict) -> None:
    data = args.edicao
    refazer_de = ETAPAS.index(args.refazer) if args.refazer else len(ETAPAS)
    sujo = False

    def precisa(etapa: str, *arquivos: Path) -> bool:
        """Refaz a etapa se pedida, se falta arquivo ou se uma etapa anterior foi refeita."""
        nonlocal sujo
        if sujo or ETAPAS.index(etapa) >= refazer_de or not all(a.exists() for a in arquivos):
            sujo = True
        return sujo

    # 1. edição
    f_edicao, f_imagem = pasta / "edicao.json", pasta / "manchete.jpg"
    if precisa("edicao", f_edicao):
        log(f"Lendo a edição {data}")
        dados = edicao_mod.ler(edicao_mod.baixar(data), data)
        manchete = next((i for i in dados["itens"] if i["papel"] == "manchete" and i["imagem"]), None)
        if manchete:
            r = requests.get(manchete["imagem"], headers={"User-Agent": UA}, timeout=30)
            r.raise_for_status()
            f_imagem.write_bytes(r.content)
        salvar(f_edicao, dados)
    dados = carregar(f_edicao)
    log(f"  \"{dados['titulo']}\" · {len(dados['itens'])} itens")

    # 2. matérias originais
    f_fontes = pasta / "fontes.json"
    if precisa("fontes", f_fontes):
        log("Conferindo as matérias originais")
        fontes = {i["id"]: checagem.ler_fonte(i["link"]) for i in dados["itens"]}
        salvar(f_fontes, fontes)
    fontes = carregar(f_fontes)

    usadas = set() if args.sem_historico else checagem.urls_recentes(data)
    descartados, candidatos = [], []
    for item in dados["itens"]:
        f = fontes[item["id"]]
        origem = nome_fonte(item["link"]) if item["link"] else "sem link"
        if not f["ok"]:
            descartados.append({"id": item["id"], "motivo": f["motivo"]})
            log(f"  X  {item['id']} ({origem}): {f['motivo']}")
        elif normalizar_url(item["link"]) in usadas:
            descartados.append({"id": item["id"], "motivo": "já saiu em vídeo nos últimos 7 dias"})
            log(f"  X  {item['id']} ({origem}): já saiu em vídeo nos últimos 7 dias")
        else:
            candidatos.append(item)
            log(f"  ok {item['id']} ({origem})")

    # 3. roteiro
    f_roteiro = pasta / "roteiro.json"
    if precisa("roteiro", f_roteiro):
        log("Escrevendo o roteiro")
        escolhidos, reserva = candidatos[:args.max_itens], candidatos[args.max_itens:]
        for _ in range(4):
            if len(escolhidos) < MIN_ITENS:
                rel["descartados"] = descartados
                raise SemVideo(f"só {len(escolhidos)} item(ns) passaram nas checagens (mínimo {MIN_ITENS})")
            rot = roteiro.escrever(escolhidos)
            reprovados = roteiro.conferir_fontes(rot, escolhidos, fontes)
            if not reprovados:
                break
            for iid, faltas in reprovados.items():
                motivo = "a matéria original não confirma " + ", ".join(faltas)
                descartados.append({"id": iid, "motivo": motivo})
                log(f"  X  {iid}: {motivo}")
            escolhidos = [i for i in escolhidos if i["id"] not in reprovados]
            while len(escolhidos) < args.max_itens and reserva:
                escolhidos.append(reserva.pop(0))
        else:
            raise RuntimeError("o roteiro não passou na conferência com as matérias em 4 tentativas")
        salvar(f_roteiro, {"itens_usados": [i["id"] for i in escolhidos], **rot,
                           "fecho": roteiro.FECHO, "descartados": descartados})
        for velha in pasta.glob("narracao_bruta*.wav"):  # narração de outro roteiro não serve para voz nenhuma
            velha.unlink()
    rot = carregar(f_roteiro)
    itens = [next(i for i in dados["itens"] if i["id"] == iid) for iid in rot["itens_usados"]]
    rel["itens_usados"] = rot["itens_usados"]
    rel["descartados"] = rot["descartados"]

    # cada frase é um bloco: é o tempo dela que dispara a troca de tela
    blocos = ([("gancho", rot["gancho"])]
              + [(f"{x['id']}#{k}", f["fala"]) for x in rot["itens"] for k, f in enumerate(x["frases"])]
              + [("fecho", rot["fecho"])])
    log(f"  roteiro: {sum(len(f.split()) for _, f in blocos)} palavras")
    telas = {f"{x['id']}#{k}": f["tela"] for x in rot["itens"] for k, f in enumerate(x["frases"])}
    for bid, fala in blocos:
        log(f"    [{bid}] {fala}" + (f"  → tela: {telas[bid]}" if telas.get(bid) else ""))
    if args.so_roteiro:
        rel["status"] = "roteiro"
        return

    # 4. narração: o TTS gera uma vez por motor e voz (alternar entre eles não paga de novo);
    #    a velocidade é aplicada depois e pode mudar sem custo
    voz = args.voz or (narracao.VOZ_PADRAO if args.motor == "google" else "")
    if not voz:
        raise RuntimeError('com --motor elevenlabs, diga a voz: --voz "nome ou id"')
    rotulo = "".join(c if c.isalnum() or c in "-_" else "_" for c in f"{args.motor}-{voz}")
    f_bruta = pasta / f"narracao_bruta-{rotulo}.wav"
    f_voz, f_meta = pasta / "narracao.wav", pasta / "narracao.json"
    if precisa("narracao", f_bruta):
        log(f"Narrando ({args.motor}, voz {voz})")
        narracao.narrar(" ".join(f for _, f in blocos), f_bruta, voz, args.motor)
    meta = {"motor": args.motor, "voz": voz, "velocidade": args.velocidade}
    if sujo or not f_voz.exists() or not f_meta.exists() or carregar(f_meta) != meta:
        sujo = True
        segundos = narracao.acelerar(f_bruta, f_voz, args.velocidade)
        salvar(f_meta, meta)
        log(f"  narração a {args.velocidade}x: {segundos:.1f}s")
    duracao = narracao.duracao(f_voz)
    rel["narracao"] = meta

    # 5. tempo de cada palavra
    f_alinhamento = pasta / "alinhamento.json"
    if precisa("alinhamento", f_alinhamento):
        log(f"Alinhando legenda (Whisper {args.whisper})")
        salvar(f_alinhamento, alinhamento.alinhar(f_voz, blocos, duracao, args.whisper))
    alin = carregar(f_alinhamento)

    # 6. imagens ilustrativas: a manchete usa a da news; as outras notícias ganham uma cena conceitual
    pasta_img = pasta / "img"
    pasta_img.mkdir(exist_ok=True)
    usa_manchete_news = f_imagem.exists() and any(i["papel"] == "manchete" for i in itens)
    prompts = {x["id"]: x["imagem"] for x in rot["itens"]}
    pedidos = [(prompts[item["id"]], pasta_img / f"{item['id']}.png", render.CORES[k % len(render.CORES)])
               for k, item in enumerate(itens) if not (item["papel"] == "manchete" and usa_manchete_news)]
    f_prompts = pasta_img / "prompts.json"
    ja_feitos = carregar(f_prompts) if f_prompts.exists() else {}
    forcar = refazer_de <= ETAPAS.index("imagens")
    faltam = [p for p in pedidos if forcar or not p[1].exists() or ja_feitos.get(p[1].name) != p[0]]
    if faltam:
        sujo = True
        log(f"Gerando {len(faltam)} imagem(ns) ilustrativa(s)")
        erros = imagens.gerar_lote(faltam)
        for prompt, destino, _ in faltam:
            if erros.get(destino):
                log(f"  X  {destino.name}: {erros[destino]} (a cena usa o número grande)")
            else:
                ja_feitos[destino.name] = prompt
                log(f"  ok {destino.name}")
        salvar(f_prompts, ja_feitos)
    nomes_img: dict[str, str] = {}
    arquivos_img: dict[str, Path] = {}
    if usa_manchete_news:
        nomes_img["manchete"], arquivos_img["manchete.jpg"] = "manchete.jpg", f_imagem
    for _, destino, _ in pedidos:
        if destino.exists():
            nomes_img[destino.stem], arquivos_img[destino.name] = destino.name, destino
    rel["imagens"] = sorted(arquivos_img)

    # 7. vídeo
    final = pasta / f"woow-daily-drops-{data}.mp4"
    if precisa("video", final):
        cenas, total = render.montar_cenas(dados, itens, rot, alin, nomes_img)
        n_destaques = sum(len(c.get("beats", [])) for c in cenas)
        log(f"Filmando {total:.1f}s em {len(cenas)} cenas e {n_destaques} destaques")
        mudo, _capa, estouros = render.filmar(pasta, dados, cenas, render.legendas(alin["palavras"]),
                                              total, arquivos_img)
        for texto in estouros:
            log(f"  AVISO: texto não coube nem no corpo mínimo: {texto}")
        musica = montagem.escolher_musica(data)
        log(f"Mixando áudio ({'trilha ' + musica.name if musica else 'sem trilha: pasta musica/ vazia'})")
        montagem.mixar(f_voz, pasta / "audio.m4a", total, render.LEAD, musica)
        montagem.juntar(mudo, pasta / "audio.m4a", final)
        mudo.unlink()
        rel["duracao"] = total
        rel["musica"] = musica.name if musica else None

    pasta_post = pasta / "post"
    pasta_post.mkdir(exist_ok=True)
    for nome, texto in posts(dados, itens, rot, bool(arquivos_img)).items():
        (pasta_post / nome).write_text(texto, "utf-8")

    # 8. publicação: sobe o MP4 e chama o cenário do Make. Só com --publicar,
    #    e o marcador .publicado.json impede o mesmo dia sair duas vezes.
    if args.publicar:
        from src import publicacao
        log("Publicando")
        rel["publicacao"] = publicacao.publicar(pasta, data, args.republicar)

    if not args.sem_historico:
        checagem.registrar(data, [normalizar_url(i["link"]) for i in itens])
    rel["status"] = "ok"
    rel["arquivo"] = str(final)
    log(f"Pronto: {final}")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="WooW! Daily Drops -> vídeo vertical curto")
    ap.add_argument("--edicao", default=hoje_brt(), help="data AAAA-MM-DD (padrão: hoje em Brasília)")
    ap.add_argument("--refazer", choices=ETAPAS, help="refaz desta etapa em diante")
    ap.add_argument("--so-roteiro", action="store_true", help="para depois do roteiro")
    ap.add_argument("--sem-historico", action="store_true",
                    help="não lê nem grava o histórico de URLs (para testes com edições antigas)")
    ap.add_argument("--max-itens", type=int, default=5)
    ap.add_argument("--velocidade", type=float, default=1.12, help="aceleração da narração (1.0 = original)")
    ap.add_argument("--motor", choices=["google", "elevenlabs"], default="google", help="motor da narração")
    ap.add_argument("--voz", help=f"voz do motor (google: padrão {narracao.VOZ_PADRAO}; elevenlabs: nome ou id)")
    ap.add_argument("--whisper", default="small")
    ap.add_argument("--publicar", action="store_true",
                    help="sobe o vídeo e dispara o cenário do Make (Instagram, YouTube, LinkedIn)")
    ap.add_argument("--republicar", action="store_true",
                    help="publica de novo um dia que já tem marcador .publicado.json")
    args = ap.parse_args()

    pasta = ROOT / "output" / args.edicao
    pasta.mkdir(parents=True, exist_ok=True)
    rel = {"edicao": args.edicao, "status": "erro"}
    try:
        executar(args, pasta, rel)
        return 0
    except (SemVideo, edicao_mod.EdicaoIndisponivel) as e:
        rel["status"], rel["motivo"] = "sem_video", str(e)
        log(f"Sem vídeo hoje: {e}")
        return 2
    except Exception as e:
        rel["motivo"] = f"{type(e).__name__}: {e}"
        traceback.print_exc()
        return 1
    finally:
        salvar(pasta / "relatorio.json", rel)


if __name__ == "__main__":
    sys.exit(main())
