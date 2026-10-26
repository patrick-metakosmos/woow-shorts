"""Chamada de LLM: Claude CLI (Sonnet) primeiro, Gemini no Vertex como reserva.

Mesmo arranjo do llm_wrapper do Video_Image_Plus, reduzido ao que o roteiro precisa.
"""
from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess

from .util import log

GCP_PROJECT = os.environ.get("WOOW_GCP_PROJECT", "project-2751c84b-a77b-4b78-89b")
GCP_LOCATION = "us-central1"


def _claude_bin() -> str | None:
    env = os.environ.get("CLAUDE_BIN")
    if env and os.path.isfile(env):
        return env
    achado = shutil.which("claude")
    if achado:
        return achado
    extensao = sorted(glob.glob(os.path.expanduser(
        r"~\.vscode\extensions\anthropic.claude-code-*\resources\native-binary\claude.exe")), reverse=True)
    return extensao[0] if extensao else None


def _claude(prompt: str, timeout: int = 240) -> str:
    binario = _claude_bin()
    if not binario:
        raise RuntimeError("claude CLI não encontrado")
    env = dict(os.environ)
    env.pop("CLAUDECODE", None)  # permite rodar de dentro de uma sessão do Claude Code
    r = subprocess.run([binario, "-p", "--model", "sonnet", "--output-format", "text"],
                       input=prompt, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=timeout, env=env)
    if r.returncode != 0 or not r.stdout.strip():
        raise RuntimeError(f"saiu com {r.returncode}: {(r.stderr or r.stdout).strip()[:300]}")
    return r.stdout


def _gemini(prompt: str) -> str:
    from google import genai
    from google.genai import types
    cliente = genai.Client(vertexai=True, project=GCP_PROJECT, location=GCP_LOCATION)
    resp = cliente.models.generate_content(
        model="gemini-2.5-pro", contents=prompt,
        config=types.GenerateContentConfig(temperature=0.6, response_mime_type="application/json"))
    return resp.text


def _extrair_json(texto: str) -> dict:
    ini, fim = texto.find("{"), texto.rfind("}")
    if ini < 0 or fim < ini:
        raise ValueError("resposta sem JSON")
    return json.loads(texto[ini:fim + 1])


def gerar_json(prompt: str) -> dict:
    erros = []
    for nome, chamar in (("Claude", _claude), ("Gemini", _gemini)):
        try:
            dados = _extrair_json(chamar(prompt))
            log(f"  resposta via {nome}")
            return dados
        except Exception as e:
            erros.append(f"{nome}: {e}")
            log(f"  {nome} falhou: {str(e)[:200]}")
    raise RuntimeError("nenhum LLM respondeu — " + " | ".join(erros))
