"""Tempo de cada palavra do roteiro dentro da narração.

O texto da legenda vem do roteiro (grafia certa, "US$ 1.999"); o Whisper só
diz QUANDO cada palavra foi falada. As duas sequências são casadas por
difflib, e palavra sem par ganha tempo interpolado entre as vizinhas.
"""
from __future__ import annotations

import difflib
from pathlib import Path

from .util import log, token


def _distribuir(roteiro: list[dict], tempos: list, i1: int, i2: int, ini: float, fim: float) -> None:
    """Reparte [ini, fim] entre as palavras i1..i2, proporcional ao tamanho de cada uma."""
    pesos = [len(roteiro[i]["k"]) + 1 for i in range(i1, i2)]
    total, t = sum(pesos), ini
    for i, peso in zip(range(i1, i2), pesos):
        d = (fim - ini) * peso / total
        tempos[i] = (t, t + d)
        t += d


def alinhar(audio: Path, blocos: list[tuple[str, str]], duracao: float, modelo: str = "small") -> dict:
    from faster_whisper import WhisperModel

    roteiro = [{"t": w, "k": token(w), "bloco": bid} for bid, fala in blocos for w in fala.split()]
    roteiro = [r for r in roteiro if r["k"]]  # travessão e reticências soltas não são palavra

    whisper = WhisperModel(modelo, device="cpu", compute_type="int8")
    segmentos, _ = whisper.transcribe(
        str(audio), language="pt", word_timestamps=True, vad_filter=False,
        condition_on_previous_text=False, initial_prompt=" ".join(f for _, f in blocos))
    ouvidas = [{"k": token(w.word), "ini": w.start, "fim": w.end}
               for s in segmentos for w in (s.words or []) if token(w.word)]

    a, b = [r["k"] for r in roteiro], [o["k"] for o in ouvidas]
    tempos: list = [None] * len(a)
    casadas = 0
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            for d in range(i2 - i1):
                tempos[i1 + d] = (ouvidas[j1 + d]["ini"], ouvidas[j1 + d]["fim"])
            casadas += i2 - i1
        elif op == "replace":  # grafia diferente do mesmo trecho: "1.999" x "mil novecentos..."
            _distribuir(roteiro, tempos, i1, i2, ouvidas[j1]["ini"], ouvidas[j2 - 1]["fim"])

    i = 0
    while i < len(a):  # palavras que o Whisper não ouviu: entre a vizinha anterior e a seguinte
        if tempos[i] is not None:
            i += 1
            continue
        j = i
        while j < len(a) and tempos[j] is None:
            j += 1
        ini = tempos[i - 1][1] if i > 0 else 0.0
        fim = tempos[j][0] if j < len(a) else duracao
        _distribuir(roteiro, tempos, i, j, ini, max(fim, ini))
        i = j

    for i in range(1, len(tempos)):  # nunca volta no tempo
        ini = max(tempos[i][0], tempos[i - 1][0])
        tempos[i] = (ini, max(tempos[i][1], ini))

    taxa = casadas / max(1, len(a))
    log(f"  alinhamento: {casadas}/{len(a)} palavras casadas com o áudio ({taxa:.0%})")
    if taxa < 0.6:
        log("  AVISO: casamento baixo, a legenda pode sair fora de tempo")

    palavras = [{"t": r["t"], "bloco": r["bloco"], "ini": round(t[0], 3), "fim": round(t[1], 3)}
                for r, t in zip(roteiro, tempos)]
    faixas = []
    for bid, _ in blocos:
        doBloco = [p for p in palavras if p["bloco"] == bid]
        faixas.append({"id": bid, "ini": doBloco[0]["ini"], "fim": doBloco[-1]["fim"]})
    return {"duracao": duracao, "casamento": round(taxa, 3), "palavras": palavras, "blocos": faixas}
