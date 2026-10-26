# WooW_Shorts

Transforma a edição do dia da **WooW! Daily Drops** num vídeo vertical de 45 a 60 s
(1080×1920, 30 fps) para Reels, Shorts e TikTok. Por enquanto só **gera**: não publica nada.

```powershell
$env:PYTHONIOENCODING = "utf-8"
python woow_shorts.py                        # edição de hoje (fuso de Brasília)
python woow_shorts.py --edicao 2026-09-10    # outra data
python woow_shorts.py --so-roteiro           # para no roteiro, sem gastar TTS
python woow_shorts.py --refazer video        # refaz só a filmagem (roteiro e voz ficam)
python woow_shorts.py --sem-historico        # teste com edição antiga, sem mexer no histórico
python tools\previa_cena.py --edicao 2026-09-11   # prévia de 1 cena em ~20s, para ajuste visual
```

Código de saída: `0` vídeo pronto · `2` sem vídeo hoje (motivo em `relatorio.json`) · `1` erro.

## O que sai em `output/<data>/`

| arquivo | o que é |
|---|---|
| `woow-daily-drops-<data>.mp4` | o vídeo |
| `capa.jpg` | 1º quadro (gancho em letras grandes), serve de capa |
| `post/instagram.txt`, `tiktok.txt`, `youtube.txt`, `linkedin.txt` | texto do post por rede. O vídeo é igual em todas; o link da news vai onde funciona: "link na bio" no Instagram/TikTok, URL no YouTube/LinkedIn (variável `WOOW_LINK_NEWS`, senão sai `COLE_O_LINK_AQUI`) |
| `relatorio.json` | status, itens usados, itens descartados e por quê |
| `edicao.json`, `fontes.json`, `roteiro.json`, `narracao.wav`, `alinhamento.json` | etapas intermediárias, reaproveitadas na próxima rodada |

## Etapas

1. **edição**: baixa o HTML público do bucket (`storage.googleapis.com/mk-woow-news-public/nl/<data>.html`).
   Não usa o broker, cujo login expira em 12 h. A data do cabeçalho tem que bater com a pedida.
2. **fontes**: abre a matéria original de cada item. Cai o item cujo link é raiz de domínio,
   dá erro ou bloqueia robôs. Cai também o que já saiu em vídeo nos últimos 7 dias (`historico.json`).
3. **roteiro**: Claude Sonnet (reserva: Gemini 2.5 Pro) escreve gancho + falas, com até 5 itens
   num orçamento fixo de ~130 palavras (mais itens = falas mais curtas).
   Duas travas: todo nome e número tem que estar no texto do item (senão reescreve)
   **e** na matéria original (senão o item sai do vídeo). Menos de 2 itens → não sai vídeo.
   O fecho é fixo e igual em todas as redes (`roteiro.FECHO`: curte, compartilha, segue, até amanhã).
   Pergunta de engajamento gerada por IA foi testada e saiu: confundiu o público.
4. **narração**: Google Gemini-TTS (`--motor google`, voz `Puck`, reserva Chirp3-HD) ou ElevenLabs
   (`--motor elevenlabs --voz <id>`, chave em `.env`). Gerada uma vez por motor e voz em
   `narracao_bruta-<motor>-<voz>.wav` e acelerada sem mudar o tom (`--velocidade`, padrão 1.12):
   trocar velocidade ou voltar a uma voz já usada não paga de novo.
   Para escolher voz sem gerar vídeo: `python tools\amostras_voz.py --voz google:Puck --voz elevenlabs:<id>`
   (mesmo trecho em cada voz, em `output\amostras-voz\`).
5. **alinhamento**: faster-whisper dá o tempo de cada palavra; o texto da legenda vem do roteiro.
   Cada frase é um bloco, e é o tempo dela que dispara a troca de tela.
6. **imagens**: a manchete usa a imagem da news; cada outra notícia ganha uma cena conceitual
   gerada pelo Vertex (`gemini-2.5-flash-image`, 3:2) a partir do prompt que o roteiro escreveu.
   Regra dura na frente do prompt: sem texto, tela, documento, pessoa real, marca ou produto.
   O prompt não pode citar marca do item (trava no roteiro). Falhou → a cena usa o número grande.
   `img/prompts.json` evita gerar de novo o que não mudou; `--refazer imagens` força.
7. **vídeo**: `templates/video.html` é filmado quadro a quadro pelo Chrome (Playwright) e
   codificado pelo ffmpeg. Cada frase depois da primeira acende um destaque sobre a imagem
   (número contando até o valor ou palavra-chave, vindos do campo `tela` do roteiro).
   Trilha com ducking, áudio final em −14 LUFS.

## Trilha

O acervo em `musica/` é gerado uma vez pelo Lyria (Vertex AI) e reaproveitado:

```powershell
python tools\gerar_trilhas.py --quantas 15   # pula as que já existem
```

Cada faixa são ~30s do Lyria emendados 3× com crossfade (~86s), normalizados em −18 LUFS.
`musica/trilhas.json` guarda modelo, prompt e semente de cada uma (procedência, caso alguma
rede questione direitos). Também dá para soltar faixas licenciadas próprias (mp3/wav/m4a) na pasta.
O programa alterna uma por dia; pasta vazia = vídeo só com a voz.

## Requisitos

Python 3.13, `pip install -r requirements.txt`, ffmpeg com libass, Chrome instalado,
credencial Google (`gcloud auth application-default login`) e Claude CLI logado.

## Pendente

- URL de inscrição da news (`WOOW_LINK_NEWS`), contas e redes de destino, voz definitiva;
- hospedar o MP4 em URL pública (bucket próprio) e publicar via cenário do Make;
- tarefa agendada (padrão do blog: Agendador do Windows + trava diária entre as duas máquinas).
