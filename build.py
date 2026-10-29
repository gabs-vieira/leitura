"""Gera site/index.html a partir dos feeds em feeds.toml."""

import calendar
import html
import json
import re
import tomllib
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo

import feedparser

ROOT = Path(__file__).parent
SITE = ROOT / "site"
HISTORY = ROOT / "data" / "history.json"
DIAS = ROOT / "data" / "dias"
TZ = ZoneInfo("America/Sao_Paulo")
USER_AGENT = "Mozilla/5.0 (leitura; +https://github.com/gabs-vieira/leitura)"

PERGUNTAS = [
    "Qual problema o autor está resolvendo, e qual trade-off ele aceitou pra resolver?",
    "Explique a ideia central em 3 frases, como se fosse pra um colega júnior.",
    "Onde isso apareceria no código que você mantém hoje? O que mudaria?",
    "Qual afirmação do texto você mais duvida? Que evidência a sustentaria ou derrubaria?",
    "Se fosse aplicar isso amanhã, qual seria o primeiro passo, e o primeiro risco?",
    "Que conceito do texto você não conseguiria explicar sem consultar? Anote e pesquise.",
    "O que isso muda (ou confirma) no que você já sabia sobre o assunto?",
]


def load_config():
    with open(ROOT / "feeds.toml", "rb") as f:
        return tomllib.load(f)


def fetch(feed):
    parsed = feedparser.parse(feed["url"], agent=USER_AGENT)
    if parsed.bozo and not parsed.entries:
        print(f"  falhou: {feed['nome']} ({parsed.get('bozo_exception')})")
        return []
    items = []
    for e in parsed.entries:
        t = e.get("published_parsed") or e.get("updated_parsed")
        if not t or not e.get("link"):
            continue
        body = ""
        if e.get("content"):
            body = e.content[0].get("value", "")
        body = body or e.get("summary", "")
        text = strip_html(body)
        items.append(
            {
                "titulo": strip_html(e.get("title", "(sem título)")),
                "link": e.link,
                "data": datetime.fromtimestamp(calendar.timegm(t), timezone.utc),
                "resumo": truncate(text, 220),
                "palavras": len(text.split()),
                "fonte": feed["nome"],
                "tema": feed["tema"],
                "tipo": feed["tipo"],
            }
        )
    return items


def strip_html(s):
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def truncate(s, n):
    return s if len(s) <= n else s[:n].rsplit(" ", 1)[0] + "…"


def norm_url(u):
    p = urlsplit(u)
    return urlunsplit((p.scheme, p.netloc.removeprefix("www."), p.path.rstrip("/"), "", ""))


def norm_title(t):
    return re.sub(r"[^\w]+", " ", t.lower()).strip()


def dedupe(items):
    seen, out = set(), []
    for it in sorted(items, key=lambda i: i["tipo"] != "funda"):
        keys = {norm_url(it["link"]), norm_title(it["titulo"])}
        if keys & seen:
            continue
        seen |= keys
        out.append(it)
    return out


def load_history():
    if HISTORY.exists():
        return json.loads(HISTORY.read_text())
    return []


def pick_deep(items, temas, history, hoje):
    for h in history:
        if h["data"] == hoje.isoformat():
            return h
    lidos = {norm_url(h["link"]) for h in history}
    pool = [i for i in items if i["tipo"] == "funda" and norm_url(i["link"]) not in lidos]
    if not pool:
        return None
    ordinal = hoje.toordinal()
    tema_do_dia = temas[ordinal % len(temas)]
    candidatos = [i for i in pool if i["tema"] == tema_do_dia] or pool
    # Prefere textos com corpo de verdade no feed; senão, o mais recente.
    candidatos.sort(key=lambda i: (i["palavras"] >= 600, i["data"]), reverse=True)
    escolhido = candidatos[0]
    entry = {
        "data": hoje.isoformat(),
        "titulo": escolhido["titulo"],
        "link": escolhido["link"],
        "fonte": escolhido["fonte"],
        "tema": escolhido["tema"],
        "resumo": escolhido["resumo"],
        "minutos": round(escolhido["palavras"] / 230) if escolhido["palavras"] >= 400 else None,
        "pergunta": PERGUNTAS[ordinal % len(PERGUNTAS)],
    }
    history.insert(0, entry)
    return entry


def e(s):
    return html.escape(s or "", quote=True)


def fmt_data(d):
    return d.astimezone(TZ).strftime("%d/%m %H:%M")


def render(cfg, dia, deep, news, dias, gerado, raiz):
    c = cfg["config"]
    if deep:
        meta = f"{e(deep['fonte'])} · {e(deep['tema'])}"
        if deep.get("minutos"):
            meta += f" · ~{deep['minutos']} min"
        deep_html = f"""
    <section class="deep">
      <p class="label">Leitura do dia</p>
      <h2><a href="{e(deep['link'])}" target="_blank" rel="noopener">{e(deep['titulo'])}</a></h2>
      <p class="meta">{meta}</p>
      <p class="resumo">{e(deep['resumo'])}</p>
      <div class="pergunta">
        <p><strong>Pergunta:</strong> {e(deep['pergunta'])}</p>
        <textarea id="resposta" data-key="resposta-{e(deep['data'])}" placeholder="Sua resposta (fica salva neste navegador)"></textarea>
      </div>
    </section>"""
    else:
        deep_html = '<section class="deep"><p>Sem leitura nova neste dia.</p></section>'

    nav = " ".join(f'<a href="#{slug(t)}">{e(t)}</a>' for t in c["temas"] if news.get(t))
    secoes = []
    for tema in c["temas"]:
        lista = news.get(tema)
        if not lista:
            continue
        lis = "\n".join(
            f"""        <li>
          <a href="{e(i['link'])}" target="_blank" rel="noopener">{e(i['titulo'])}</a>
          <span class="meta">{e(i['fonte'])} · {fmt_data(datetime.fromisoformat(i['data']))}</span>
        </li>"""
            for i in lista
        )
        secoes.append(f'    <section id="{slug(tema)}">\n      <h3>{e(tema)}</h3>\n      <ul>\n{lis}\n      </ul>\n    </section>')

    prefixo = "dias/" if raiz else ""
    anteriores = "\n".join(
        f'        <li><a href="{prefixo}{d}.html">{fmt_dia(d)}</a> '
        f'<span class="meta">{e(titulo)}</span></li>'
        for d, titulo in dias
        if d != dia.isoformat()
    )
    voltar = "" if raiz else '<a href="../">← Hoje</a> · '

    template = (ROOT / "template.html").read_text()
    return (
        template.replace("{{titulo}}", e(c["titulo"]))
        .replace("{{data}}", dia.strftime("%d/%m/%Y"))
        .replace("{{voltar}}", voltar)
        .replace("{{gerado}}", gerado.strftime("%d/%m/%Y %H:%M"))
        .replace("{{deep}}", deep_html)
        .replace("{{nav}}", nav)
        .replace("{{secoes}}", "\n".join(secoes))
        .replace("{{anteriores}}", anteriores or "        <li>Nada ainda.</li>")
    )


def fmt_dia(iso):
    return f"{iso[8:10]}/{iso[5:7]}/{iso[:4]}"


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower().encode("ascii", "ignore").decode()).strip("-")


def main():
    cfg = load_config()
    c = cfg["config"]
    agora = datetime.now(TZ)
    print(f"Buscando {len(cfg['feed'])} feeds…")
    with ThreadPoolExecutor(16) as ex:
        items = [i for lote in ex.map(fetch, cfg["feed"]) for i in lote]
    items = dedupe(items)

    limite_funda = agora - timedelta(days=c["dias_funda"])
    history = load_history()
    deep = pick_deep([i for i in items if i["data"] >= limite_funda], c["temas"], history, agora.date())

    limite_noticia = agora - timedelta(days=c["dias_noticia"])
    news = {}
    for i in sorted(items, key=lambda i: i["data"], reverse=True):
        if i["data"] < limite_noticia or (deep and norm_url(i["link"]) == norm_url(deep["link"])):
            continue
        lista = news.setdefault(i["tema"], [])
        if len(lista) < c["max_por_tema"]:
            lista.append(i)

    hoje = agora.date().isoformat()
    DIAS.mkdir(parents=True, exist_ok=True)
    snapshot = {
        "deep": deep,
        "news": {
            tema: [{k: i[k] for k in ("titulo", "link", "fonte")} | {"data": i["data"].isoformat()} for i in lista]
            for tema, lista in news.items()
        },
    }
    (DIAS / f"{hoje}.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n")
    HISTORY.write_text(json.dumps(history[:365], ensure_ascii=False, indent=2) + "\n")

    snapshots = {f.stem: json.loads(f.read_text()) for f in sorted(DIAS.glob("*.json"), reverse=True)}
    dias = [(d, (s["deep"] or {}).get("titulo", "")) for d, s in snapshots.items()]
    (SITE / "dias").mkdir(parents=True, exist_ok=True)
    for d, snap in snapshots.items():
        dia = date.fromisoformat(d)
        (SITE / "dias" / f"{d}.html").write_text(render(cfg, dia, snap["deep"], snap["news"], dias, agora, raiz=False))
    hoje_snap = snapshots[hoje]
    (SITE / "index.html").write_text(render(cfg, agora.date(), hoje_snap["deep"], hoje_snap["news"], dias, agora, raiz=True))
    print(f"OK: {sum(map(len, news.values()))} notícias, leitura: {deep['titulo'] if deep else '-'}, {len(dias)} dias no arquivo")


if __name__ == "__main__":
    main()
