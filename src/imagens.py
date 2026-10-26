"""Imagens ilustrativas das notícias, geradas pelo Vertex (gemini-2.5-flash-image).

Mesma chamada e mesmas travas do Carousel_Plus (src/imagens_ia.py): a regra
dura vai na FRENTE do prompt (esse modelo segue instrução; negativo no fim
perde para o assunto), e nada de texto, tela, documento ou pessoa pública.
Aqui a imagem ilustra notícia real, então a trava extra é não reproduzir
produto nem marca: cena conceitual, sempre com o selo "Imagem ilustrativa · IA".
"""
from __future__ import annotations

import io
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image, ImageFilter

from .llm import GCP_PROJECT

MODELO = "gemini-2.5-flash-image"
LOCAL = "global"   # único local em que esse publisher responde no projeto (medido no Carousel_Plus)
ASPECTO = "3:2"    # a faixa da notícia é 1080x720
LARGURA, ALTURA = 1080, 720
NOMES_COR = {"#DC0C9F": "magenta", "#1291E2": "electric blue", "#FB5B12": "orange",
             "#7C16DB": "violet", "#E8F102": "neon yellow"}

REGRAS = (
    "STRICT RULES, these override everything that follows.\n"
    "1. Render NO text of any kind: no letters, no words, no numbers, no captions, no signage, "
    "no logos, no watermarks, no brand marks.\n"
    "2. Never depict a document, screenshot, phone screen or user interface. If the brief suggests one, "
    "photograph the scene AROUND it instead.\n"
    "3. Never depict a real, identifiable person or public figure, and never reproduce a real branded "
    "product. People appear only as anonymous figures seen from behind, in silhouette or out of focus.\n"
    "Now produce this photograph:\n\n"
)

# O visual_dna da marca mK (Carousel_Plus/brands/mk/brand.json), com a cor da notícia como luz de destaque.
ESTILO = (
    "\n\nStyle: photorealistic editorial photography, cinematic, high-end tech aesthetic. "
    "Dramatic directional light, deep shadows, strong contrast, dark scene. Predominantly black "
    "background with a single saturated {cor} accent light. Fine film grain, crisp micro-detail, "
    "35mm lens, shallow depth of field. Wide 3:2 composition, subject near the center."
)

_cliente = None
_trava = threading.Lock()


def _projeto() -> str:
    """Projeto GCP: VERTEX_PROJECT, o quota_project da credencial padrão, ou o dos pipelines de vídeo."""
    if os.environ.get("VERTEX_PROJECT"):
        return os.environ["VERTEX_PROJECT"]
    adc = Path(os.environ.get("APPDATA", "")) / "gcloud" / "application_default_credentials.json"
    if adc.exists():
        try:
            quota = json.loads(adc.read_text(encoding="utf-8")).get("quota_project_id")
            if quota:
                return quota
        except (OSError, ValueError):
            pass
    return GCP_PROJECT


def _obter_cliente():
    """Cliente num global: sem uma referência viva, o coletor fecha o Client no meio da chamada."""
    global _cliente
    with _trava:
        if _cliente is None:
            from google import genai
            _cliente = genai.Client(vertexai=True, project=_projeto(), location=LOCAL)
        return _cliente


def _extrair(resposta) -> bytes:
    candidatos = getattr(resposta, "candidates", None) or []
    if not candidatos:
        raise RuntimeError("o modelo não respondeu nada")
    textos = []
    for parte in (candidatos[0].content.parts or []) if candidatos[0].content else []:
        dado = getattr(parte, "inline_data", None)
        if dado is not None and dado.data:
            return dado.data
        if getattr(parte, "text", None):
            textos.append(parte.text.strip())
    motivo = getattr(candidatos[0], "finish_reason", None)
    raise RuntimeError("sem imagem" + (f" (motivo: {motivo})" if motivo else "")
                       + (f": {' '.join(textos)[:200]}" if textos else ", provavelmente recusa"))


def gerar(cena: str, cor: str) -> bytes:
    from google.genai import types
    prompt = REGRAS + cena.strip() + ESTILO.format(cor=NOMES_COR.get(cor.upper(), "neon"))
    resposta = _obter_cliente().models.generate_content(
        model=MODELO, contents=prompt,
        config=types.GenerateContentConfig(response_modalities=["TEXT", "IMAGE"],
                                           image_config=types.ImageConfig(aspect_ratio=ASPECTO)))
    return _extrair(resposta)


def _salvar(dados: bytes, destino: Path) -> None:
    """Grava PNG; só amplia (Lanczos + nitidez leve) se vier menor que a faixa."""
    with Image.open(io.BytesIO(dados)) as img:
        img = img.convert("RGB")
        escala = max(LARGURA / img.width, ALTURA / img.height)
        if escala > 1.02:
            img = img.resize((round(img.width * escala), round(img.height * escala)), Image.LANCZOS)
            img = img.filter(ImageFilter.UnsharpMask(radius=1.2, percent=60, threshold=2))
        img.save(destino, "PNG")


def gerar_lote(pedidos: list[tuple[str, Path, str]], tentativas: int = 2) -> dict[Path, str]:
    """pedidos: (cena, destino, cor). Devolve {destino: erro} só das que falharam."""
    _obter_cliente()

    def uma(pedido: tuple[str, Path, str]) -> tuple[Path, str]:
        cena, destino, cor = pedido
        erro = ""
        for _ in range(tentativas):
            try:
                _salvar(gerar(cena, cor), destino)
                return destino, ""
            except Exception as e:
                erro = f"{type(e).__name__}: {str(e)[:200]}"
        return destino, erro

    with ThreadPoolExecutor(max_workers=4) as pool:
        return {destino: erro for destino, erro in pool.map(uma, pedidos) if erro}
