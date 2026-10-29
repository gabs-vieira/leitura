# Leitura

Página diária com uma leitura funda + pergunta, e as notícias de Backend, Databases, Ciência da Computação, IA e Carreira.

- Fontes: `feeds.toml` (adicionar feed = um bloco `[[feed]]`)
- Gerar local: `pip install -r requirements.txt && python build.py` → `site/index.html`
- Publicação: GitHub Actions roda todo dia às 06:00 (BRT) e publica no GitHub Pages
- Histórico das leituras: `data/history.json` (commitado pelo workflow)

Newsletter que só chega por email: gere um feed em https://kill-the-newsletter.com, assine com o email dele e cole a URL do feed no `feeds.toml`.
