"""Roteiro falado do vídeo, escrito por LLM e travado nos fatos.

Duas travas, nesta ordem:
1. fidelidade: todo nome próprio e número da fala tem que estar no texto do
   item na edição (senão o LLM inventou; ele reescreve com a lista de erros),
   e a tela de cada frase só pode usar nomes e números da própria frase;
2. fonte: os nomes e números da fala e do gancho têm que estar na matéria
   original (senão a própria news errou; o item sai do vídeo).

Cada notícia vem em frases, e cada frase vira uma tela: é isso que dá ritmo ao vídeo.
"""
from __future__ import annotations

import json
import re

from . import llm
from .util import GEOGRAFIA, log, mencoes_numericas, nomes_proprios, token, vocabulario

# Fecho fixo, igual em todas as redes. A pergunta de engajamento gerada por IA saiu
# em 2026-09-11: o público entendeu "anúncios na IA" como anúncio da própria marca.
FECHO = ("Se gostou desse conteúdo, já curte e compartilha com alguém que vai gostar de ver as notícias do dia. "
         "E já segue pra não perder nenhum Drop. Até amanhã!")
MAX_PALAVRAS = 150
MAX_GANCHO = 16
MAX_TELA = 5
ORCAMENTO = 130  # gancho + falas; com o fecho, a 1,12x dá ~55s de vídeo

INSTRUCOES = """Você escreve a NARRAÇÃO de um vídeo vertical de 50 a 60 segundos (Reels, Shorts, TikTok, LinkedIn) que resume a edição de hoje da WooW! Daily Drops, a newsletter diária da metaKosmos sobre varejo, e-commerce, IA e tecnologia imersiva. O vídeo muda de tela a cada frase, então você também decide o que aparece escrito e qual cena ilustra cada notícia.

ENTRADA: os itens da edição, na ordem em que vão aparecer no vídeo. Cada item tem id, papel, título e texto.

SAÍDA: somente um objeto JSON, sem markdown e sem comentário:
{"gancho": "...",
 "itens": [{"id": "<id do item>",
            "frases": [{"fala": "...", "tela": ""}, {"fala": "...", "tela": "..."}],
            "imagem": "..."}]}
Um objeto em "itens" para cada item recebido, na mesma ordem e com o mesmo id.

REGRAS DE FATO (inegociáveis: o vídeo é público e leva a marca):
1. Use SOMENTE o que está no título ou no texto do próprio item. Não acrescente contexto, cargo, data, preço, comparação, consequência ou número que não esteja lá, mesmo que você saiba que é verdade.
2. Nomes próprios e números com a grafia EXATA do texto. Números em algarismos, como no texto: se o texto diz "US$ 1.999", escreva "US$ 1.999"; se diz "76%", escreva "76%".
3. Não afirme mais do que o texto afirma: se o texto diz "promete", não escreva "faz"; se diz "cresceu", não escreva "disparou"; se diz "pode chegar a", não escreva "custa".

REGRAS DE FORMA:
4. "gancho": UMA frase de no máximo 14 palavras, sobre o primeiro item, que faça a pessoa parar de rolar a tela. Pergunta ou afirmação provocativa. Ela aparece escrita em letras enormes na primeira tela, então precisa se sustentar sozinha. Nada de "olá", "bom dia", "bem-vindo" nem nome da newsletter.
5. As frases de cada item, somadas: primeiro item __PRIMEIRO__ palavras; demais itens __OUTROS__ palavras cada. Gancho + todas as falas: no máximo __TOTAL__ palavras. É um giro rápido de notícias: vá direto ao fato mais surpreendente de cada item.
6. Frases curtas, uma ideia por frase. Voz da metaKosmos: coloquial, próxima, leve, confiante e com energia; provocativa sem desrespeito; zero jargão corporativo. Pode falar com "você".
7. A primeira frase de cada item precisa situar o assunto sozinha (quem fez o quê), porque abre uma tela nova. Sem "em seguida", "próxima notícia", "e mais".
8. Texto para ser FALADO por uma voz sintética: sem emoji, hashtag, parênteses, aspas, travessão, lista ou abreviação (siglas conhecidas como IA e EUA podem).
9. Não termine as falas com chamada para ação, pergunta ao público nem despedida: o fechamento do vídeo é fixo e vem depois.

REGRAS DE TELA E IMAGEM:
10. "frases": a fala de cada item dividida em 2 frases (o primeiro item pode ter 3). Cada frase vira uma tela diferente.
11. "tela": na PRIMEIRA frase de cada item, "" (a tela mostra o título da notícia). Nas outras: se a frase tem número, a tela é esse número com a unidade, exatamente como na fala ("US$ 10,3 bilhões", "620%"); se não tem, a ideia-chave da frase em 2 a 4 palavras, usando palavras da própria frase ("Anúncios no ChatGPT", "Loja vira experiência"). Máximo 5 palavras. Escreva em caixa normal de frase, com maiúscula só no início e em nomes próprios: o vídeo já mostra tudo em caixa alta.
12. "imagem": em inglês, uma ou duas frases descrevendo uma CENA CONCEITUAL que ilustre a notícia por metáfora ou contexto: objetos, ambientes, mãos, pessoas anônimas de costas ou desfocadas. PROIBIDO: nome de empresa, marca, produto, app ou pessoa; logotipos; texto, letras ou números na imagem; reproduzir um produto real. Descreva só a cena: o estilo visual é aplicado depois."""


def _metas(n_itens: int) -> tuple[str, str]:
    """Palavras por item: o orçamento total é fixo, então mais notícias = falas mais curtas."""
    outros = min(30, (ORCAMENTO - 12 - 32) // max(1, n_itens - 1))
    return "28 a 36", f"{outros - 4} a {outros}"


def _contar(texto: str) -> int:
    return len(texto.split())


def fala_do_item(x: dict) -> str:
    return " ".join(f["fala"].strip() for f in x["frases"])


def _sem_base(fala: str, referencia: str) -> list[str]:
    """Nomes e números que a fala cita e a referência não tem."""
    vocab = vocabulario(referencia)
    numeros_ref = set().union(*(formas for _, formas in mencoes_numericas(referencia)))
    faltas = [bruto for bruto, formas in mencoes_numericas(fala) if not formas & numeros_ref]
    faltas += [grafia for t, grafia in nomes_proprios(fala).items() if t not in vocab]
    return faltas


def _marcas_no_prompt(prompt: str, referencia: str) -> list[str]:
    """Nomes do item que aparecem com maiúscula no prompt de imagem (em inglês, marca vem capitalizada)."""
    marcas = {t for t in nomes_proprios(referencia) if t not in GEOGRAFIA}
    return [w for w in re.findall(r"\w[\w'’-]*", prompt) if w[0].isupper() and token(w) in marcas]


def _estrutura(rot: dict, itens: list[dict]) -> list[str]:
    if not (isinstance(rot.get("gancho"), str) and rot["gancho"].strip()) or not isinstance(rot.get("itens"), list):
        return ["o JSON precisa ter 'gancho' (texto) e 'itens' (lista)"]
    esperado = [i["id"] for i in itens]
    veio = [x.get("id") for x in rot["itens"] if isinstance(x, dict)]
    if veio != esperado:
        return [f"'itens' precisa ter exatamente os ids {esperado}, nesta ordem (veio {veio})"]
    for x in rot["itens"]:
        frases = x.get("frases")
        if not isinstance(frases, list) or not frases or not all(
                isinstance(f, dict) and isinstance(f.get("fala"), str) and f["fala"].strip()
                and isinstance(f.get("tela", ""), str) for f in frases):
            return [f"o item {x['id']} precisa de 'frases': lista de objetos com 'fala' e 'tela'"]
        if not isinstance(x.get("imagem"), str) or not x["imagem"].strip():
            return [f"o item {x['id']} precisa de 'imagem' (prompt da cena, em inglês)"]
    return []


def validar(rot: dict, itens: list[dict]) -> list[str]:
    problemas = _estrutura(rot, itens)
    if problemas:
        return problemas

    n_gancho = _contar(rot["gancho"])
    if n_gancho > MAX_GANCHO:
        problemas.append(f"o gancho tem {n_gancho} palavras; o máximo é {MAX_GANCHO}")
    total = n_gancho + sum(_contar(fala_do_item(x)) for x in rot["itens"])
    if total > MAX_PALAVRAS:
        problemas.append(f"o roteiro tem {total} palavras; o máximo é {MAX_PALAVRAS}")

    primeiro = itens[0]
    for falta in _sem_base(rot["gancho"], f"{primeiro['titulo']} {primeiro['texto']}"):
        problemas.append(f"o gancho cita '{falta}', que não está no texto do item {primeiro['id']}")
    for item, x in zip(itens, rot["itens"]):
        ref = f"{item['titulo']} {item['texto']}"
        n_frases = len(x["frases"])
        if not 2 <= n_frases <= 3:
            problemas.append(f"o item {item['id']} tem {n_frases} frase(s); precisa de 2 (o primeiro pode ter 3)")
        for falta in _sem_base(fala_do_item(x), ref):
            problemas.append(f"a fala de {item['id']} cita '{falta}', que não está no texto do item")
        # a tela resume a própria frase: nome e número dela têm que vir de lá (a frase já é checada)
        for f in x["frases"][1:]:
            tela = f.get("tela", "").strip()
            if _contar(tela) > MAX_TELA:
                problemas.append(f"a tela '{tela}' tem mais de {MAX_TELA} palavras")
            for falta in _sem_base(tela, f["fala"]):
                problemas.append(f"a tela '{tela}' tem '{falta}', que não está na própria frase "
                                 "(use caixa normal e só palavras da frase)")
        citadas = _marcas_no_prompt(x["imagem"], ref)
        if citadas:
            problemas.append(f"o prompt de imagem de {item['id']} cita {', '.join(citadas)}: "
                             "descreva a cena sem marca, produto ou pessoa")
    return problemas


def escrever(itens: list[dict], tentativas: int = 3) -> dict:
    primeiro, outros = _metas(len(itens))
    instrucoes = (INSTRUCOES.replace("__PRIMEIRO__", primeiro).replace("__OUTROS__", outros)
                  .replace("__TOTAL__", str(ORCAMENTO)))
    entrada = [{k: i[k] for k in ("id", "papel", "titulo", "texto")} for i in itens]
    prompt = f"{instrucoes}\n\nITENS:\n{json.dumps(entrada, ensure_ascii=False, indent=2)}"
    pedido, problemas = prompt, []
    for n in range(1, tentativas + 1):
        rot = llm.gerar_json(pedido)
        problemas = validar(rot, itens)
        if not problemas:
            saida = []
            for x in rot["itens"]:
                frases = [{"fala": f["fala"].strip(), "tela": f.get("tela", "").strip()} for f in x["frases"]]
                saida.append({"id": x["id"], "frases": frases, "imagem": x["imagem"].strip(),
                              "fala": " ".join(f["fala"] for f in frases)})
            return {"gancho": rot["gancho"].strip(), "itens": saida}
        log(f"  roteiro {n}/{tentativas} reprovado: " + "; ".join(problemas))
        pedido = (f"{prompt}\n\nSUA VERSÃO ANTERIOR:\n{json.dumps(rot, ensure_ascii=False)}\n\n"
                  "PROBLEMAS (corrija todos e devolva o JSON completo):\n- " + "\n- ".join(problemas))
    raise RuntimeError(f"roteiro reprovado {tentativas} vezes: " + "; ".join(problemas))


def _nao_confirmado(texto: str, fonte: str) -> list[str]:
    return [f for f in _sem_base(texto, fonte) if token(f) not in GEOGRAFIA]


def conferir_fontes(rot: dict, itens: list[dict], fontes: dict) -> dict[str, list[str]]:
    """{id do item: nomes/números da fala (ou do gancho, no 1º item) que a matéria original não confirma}.

    Cada texto é checado separado: colados, o começo de um vira meio de frase do
    outro e palavra comum com maiúscula passa por nome próprio. A tela não entra:
    ela só pode repetir o que a frase já diz, e a frase é checada aqui.
    """
    reprovados = {}
    for item, x in zip(itens, rot["itens"]):
        fonte = fontes[item["id"]]["texto"]
        faltas = _nao_confirmado(x["fala"], fonte)
        if item is itens[0]:
            faltas += _nao_confirmado(rot["gancho"], fonte)
        if faltas:
            reprovados[item["id"]] = list(dict.fromkeys(faltas))
    return reprovados
