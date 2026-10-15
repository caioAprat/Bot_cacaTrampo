"""Caçador de clientes: vigia o 99Freelas e o Workana e avisa no Telegram com rascunho de proposta.

Uso:
  python cacador.py             roda uma vez (é o que a nuvem faz a cada 10 min)
  python cacador.py --teste     mostra os alertas na tela, sem mandar nem salvar nada
  python cacador.py --chat-id   descobre o seu chat_id do Telegram
  python cacador.py --ping      manda uma mensagem de teste para o Telegram
"""

import html
import json
import os
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path

PASTA = Path(__file__).parent
ARQ_VISTOS = PASTA / "vistos.json"
BASE = "https://www.99freelas.com.br"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36"

# Listas lidas a cada rodada (mais recentes primeiro)
LISTAS = [
    "/projects?categoria=web-mobile-e-software",
    "/projects?categoria=web-mobile-e-software&page=2",
    "/projects?categoria=web-mobile-e-software&page=3",
    "/projects?categoria=administracao-e-contabilidade",
    "/projects?categoria=suporte-administrativo",
    "/projects",
]

WORKANA = "https://www.workana.com/jobs?language=pt&category=it-programming"
LISTAS_WORKANA = [WORKANA, WORKANA + "&page=2"]

# IA grátis (Google Gemini, plano gratuito). Sem a chave, usa os modelos de texto.
MODELOS_IA = ["gemini-flash-latest", "gemini-2.5-flash", "gemini-flash-lite-latest"]

MAX_ALERTAS_POR_RODADA = 8
IDADE_MAX_HORAS = 12          # ignora projeto publicado há mais tempo que isso
NOTA_MINIMA = 7               # só avisa a partir desta nota (0 a 10)
DIAS_GUARDAR_VISTOS = 30

# ---------------------------------------------------------------- serviços

SERVICOS = {
    "planilhas": {
        "nome": "Planilhas e Apps Script",
        "palavras": {
            "planilha": 3, "excel": 3, "google sheets": 3, "sheets": 2, "apps script": 4,
            "appscript": 4, "vba": 3, "macro": 3, "formula": 2, "dashboard": 2,
            "google forms": 2, "looker": 1, "relatorio": 1,
        },
    },
    "automacao": {
        "nome": "Bots e automações",
        "palavras": {
            "bot": 3, "chatbot": 3, "automacao": 3, "automatizar": 3, "automatizacao": 3,
            "robo": 3, "rpa": 3, "scraping": 3, "raspagem": 3, "web scraping": 3, "python": 2,
            "integracao": 2, "integrar": 2, "api": 1, "webhook": 2, "n8n": 3, "make.com": 2,
            "zapier": 2, "telegram": 2, "whatsapp": 2, "selenium": 2, "playwright": 2,
        },
    },
    "sistemas": {
        "nome": "Sistemas web",
        "palavras": {
            "sistema": 2, "painel": 2, "gestao": 2, "crm": 2, "erp": 1, "saas": 3,
            "plataforma": 1, "next.js": 3, "nextjs": 3, "react": 2, "supabase": 4,
            "firebase": 2, "cadastro": 1, "controle de": 2, "agendamento": 2, "chamados": 3,
            "aplicativo web": 2, "app web": 2, "web app": 2, "mvp": 2, "node": 1,
        },
    },
    "sites": {
        "nome": "Sites e landing pages",
        "palavras": {
            "landing page": 4, "landing": 3, "site": 2, "pagina": 1, "institucional": 3,
            "portfolio": 2, "html": 1, "css": 1, "one page": 3, "pagina de vendas": 3,
        },
    },
}

# Coisas fora do seu perfil: tiram pontos
FORA_DO_PERFIL = {
    "android nativo": 3, "ios nativo": 3, "swift": 3, "kotlin": 3, "flutter": 2,
    "react native": 2, "unity": 4, "jogo": 3, "game": 3, "blockchain": 4, "cripto": 3,
    "solidity": 4, "smart contract": 4, "delphi": 4, "c#": 3, ".net": 3, "java ": 2,
    "magento": 3, "sap": 3, "logo": 3, "logotipo": 4, "edicao de video": 4, "video": 2,
    "traducao": 4, "artigo": 2, "redacao": 3, "ligacoes": 4, "telemarketing": 4,
    "cold call": 4, "sdr": 4, "prospeccao": 2, "trafego pago": 3, "social media": 3,
    "android": 2, "play store": 3, "google play": 3, "app store": 3, "woocommerce": 1,
}

# Se aparecer no título, o projeto é descartado na hora (não é programação)
VETO_TITULO = [
    "trafego", "marketing", "aquisicao de clientes", "geracao de leads", "leads", "anuncio",
    "gestor de", "copywriter", "copywriting", "seo", "social media", "instagram", "tiktok",
    "logo", "logotipo", "identidade visual", "design grafico", "ux", "ui/ux", "video",
    "editor", "edicao", "fotografia", "traducao", "redacao", "artigo", "ligacoes",
    "prospeccao", "vendedor", "vendas", "sdr", "cold call", "jogo", "game", "unity",
    "play store", "google play", "app store", "android", "ios", "cripto", "sinais",
    "redes sociais", "marketplaces", "gestao de marketplace", "atendente", "assistente virtual",
]

# O que você já sabe fazer: ganha bônus e aparece como "fácil pra você"
FACIL_PRA_VOCE = [
    "planilha", "excel", "google sheets", "apps script", "vba", "macro", "dashboard",
    "bot", "chatbot", "whatsapp", "telegram", "automacao", "automatizar", "robo",
    "landing page", "landing", "site institucional", "one page", "pagina de vendas",
    "formulario", "relatorio automatico",
]

# Faixas de preço que EU estimei (não é dado de mercado verificado).
# pequeno / médio / grande, em reais. Ajuste conforme fechar projetos de verdade.
PRECOS = {
    "planilhas": [(150, 400), (400, 1200), (1200, 3000)],
    "automacao": [(300, 800), (800, 2500), (2500, 6000)],
    "sistemas":  [(1500, 4000), (4000, 10000), (10000, 25000)],
    "sites":     [(300, 900), (900, 2500), (2500, 6000)],
}

# Sinais de que o projeto é maior
SINAIS_DE_PORTE = [
    "login", "usuarios", "perfis", "painel", "dashboard", "integracao", "integrar", "api",
    "pagamento", "assinatura", "relatorios", "banco de dados", "multi", "ia ", "inteligencia artificial",
    "aplicativo", "app", "notificacoes", "agendamento", "estoque", "financeiro", "telas",
]


def sem_acento(texto):
    texto = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in texto if not unicodedata.combining(c))


def conta(texto, palavra):
    return len(re.findall(r"(?<![a-z0-9])" + re.escape(palavra) + r"(?![a-z0-9])", texto))


def pontuar_servicos(projeto):
    """Devolve (serviço principal, pontos por serviço)."""
    titulo = sem_acento(projeto["titulo"])
    corpo = sem_acento(projeto["descricao"] + " " + " ".join(projeto["habilidades"]))
    pontos = {}
    for chave, serv in SERVICOS.items():
        total = 0
        for palavra, peso in serv["palavras"].items():
            if conta(titulo, palavra):
                total += peso * 2          # no título vale o dobro
            if conta(corpo, palavra):
                total += peso
        pontos[chave] = total
    penalidade = 0
    for palavra, peso in FORA_DO_PERFIL.items():
        if conta(titulo, palavra):
            penalidade += peso * 2
        elif conta(corpo, palavra):
            penalidade += peso
    principal = max(pontos, key=pontos.get)
    return principal, pontos, penalidade


def e_facil(projeto):
    titulo = sem_acento(projeto["titulo"])
    return any(conta(titulo, p) for p in FACIL_PRA_VOCE)


def porte_do_projeto(projeto):
    """0 = pequeno, 1 = médio, 2 = grande."""
    texto = sem_acento(projeto["titulo"] + " " + projeto["descricao"])
    sinais = sum(1 for s in SINAIS_DE_PORTE if conta(texto, s.strip()))
    if len(projeto["descricao"]) > 1200:
        sinais += 2
    elif len(projeto["descricao"]) > 600:
        sinais += 1
    return 0 if sinais <= 2 else 1 if sinais <= 5 else 2


def valor_citado(projeto):
    """Valor em R$ que o próprio cliente escreveu na descrição, se tiver."""
    valores = re.findall(r"R\$\s?(\d{1,3}(?:\.\d{3})*(?:,\d{2})?|\d+)", projeto["descricao"])
    numeros = []
    for v in valores:
        n = float(v.replace(".", "").replace(",", "."))
        if n >= 50:
            numeros.append(n)
    return numeros


def reais(n):
    return "R$ " + f"{n:,.0f}".replace(",", ".")


def preco_do_projeto(projeto, servico, orcamento):
    """Texto do preço: o que o cliente informou ou a minha estimativa."""
    if orcamento and orcamento.lower() not in ("aberto", "não informado", "nao informado"):
        if "USD" in orcamento and cotacao_dolar():
            numeros = [float(n.replace(".", "").replace(",", ".")) for n in re.findall(r"\d[\d.,]*\d|\d", orcamento)]
            if numeros:
                em_reais = " a ".join(reais(n * cotacao_dolar()) for n in numeros)
                if orcamento.lower().startswith("menos"):
                    em_reais = "menos de " + em_reais
                elif orcamento.lower().startswith("mais"):
                    em_reais = "mais de " + em_reais
                if "hora" in orcamento.lower():
                    em_reais += " por hora"
                return f"Cliente: {orcamento} (≈ {em_reais})"
        return f"Cliente: {orcamento}"
    citados = valor_citado(projeto)
    if citados:
        return "Cliente citou: " + " / ".join(reais(n) for n in citados[:2])
    minimo, maximo = PRECOS[servico][porte_do_projeto(projeto)]
    return f"Estimativa: {reais(minimo)} a {reais(maximo)}"


def nota_do_projeto(projeto):
    """Nota de 0 a 10 dizendo se vale a pena, com os motivos."""
    titulo = sem_acento(projeto["titulo"])
    if any(conta(titulo, v) for v in VETO_TITULO):
        return 0, "sistemas", ["não é programação"]

    principal, pontos, penalidade = pontuar_servicos(projeto)
    encaixe = pontos[principal] - penalidade
    motivos = []

    if encaixe <= 0:
        return 0, principal, ["fora do seu perfil"]

    nota = min(encaixe, 10) / 10 * 6           # até 6 pontos pelo encaixe
    motivos.append(f"encaixa em {SERVICOS[principal]['nome'].lower()}")

    if e_facil(projeto):
        nota += 1.5; motivos.append("você já sabe fazer")

    p = projeto["propostas"]
    if p is not None:
        if p <= 3:
            nota += 3; motivos.append("quase ninguém mandou proposta")
        elif p <= 10:
            nota += 2; motivos.append("poucas propostas")
        elif p <= 25:
            nota += 1
        elif p >= 50:
            nota -= 2; motivos.append("concorrência alta")

    idade_min = projeto["idade_min"]
    if idade_min is not None and idade_min <= 60:
        nota += 1; motivos.append("acabou de sair")

    if projeto["cliente_nota"] and projeto["cliente_avaliacoes"]:
        if projeto["cliente_nota"] >= 4.5:
            nota += 1; motivos.append("cliente bem avaliado")
        elif projeto["cliente_nota"] < 3.5:
            nota -= 1; motivos.append("cliente com nota baixa")

    if projeto["urgente"]:
        nota += 0.5; motivos.append("urgente")

    if projeto["pagamento_verificado"]:
        nota += 0.5; motivos.append("pagamento verificado")

    return max(0, min(10, round(nota))), principal, motivos


# ---------------------------------------------------------------- leitura do site

def baixar(url, tentativas=3):
    for i in range(tentativas):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "pt-BR"})
            with urllib.request.urlopen(req, timeout=30) as r:
                bruto = r.read()
            try:
                return bruto.decode("utf-8")
            except UnicodeDecodeError:
                return bruto.decode("cp1252", errors="replace")
        except Exception as e:
            if i == tentativas - 1:
                print(f"[erro] {url}: {e}")
                return ""
            time.sleep(3)


def limpar(texto):
    texto = re.sub(r"<br\s*/?>", "\n", texto)
    texto = re.sub(r"<[^>]+>", "", texto)
    texto = html.unescape(texto)
    texto = re.sub(r"[ \t]+", " ", texto)
    return re.sub(r"\n{3,}", "\n\n", texto).strip()


def ler_lista(caminho):
    pagina = baixar(BASE + caminho)
    projetos = []
    blocos = re.split(r'<li class="[^"]*result-item[^"]*"', pagina)[1:]
    agora = time.time()
    for bloco in blocos:
        m_id = re.search(r'data-id="(\d+)"', bloco)
        m_link = re.search(r'<h1 class="title">.*?<a href="([^"]+)">(.*?)</a>', bloco, re.S)
        if not m_id or not m_link:
            continue
        info = re.search(r'<p class="item-text information">(.*?)</hgroup>', bloco, re.S)
        info_txt = limpar(info.group(1)) if info else ""
        partes = [x.strip() for x in info_txt.split("|")]
        m_pub = re.search(r'Publicado:\s*<b class="datetime" cp-datetime="(\d+)"', bloco)
        m_prop = re.search(r"Propostas:\s*<b>(\d+)</b>", bloco)
        m_desc = re.search(r'class="item-text description[^"]*" data-content="([^"]*)"', bloco, re.S)
        m_cli = re.search(r'<b>Cliente: </b>\s*<a [^>]*>([^<]*)</a>', bloco)
        m_nota = re.search(r'data-score="([\d.]+)"', bloco)
        m_aval = re.search(r'avaliacoes-text">\s*\(?(\d+)', bloco)
        publicado = int(m_pub.group(1)) / 1000 if m_pub else None
        link = m_link.group(1).split("?")[0]
        projetos.append({
            "id": m_id.group(1),
            "titulo": limpar(m_link.group(2)),
            "link": BASE + link,
            "subcategoria": partes[0] if partes else "",
            "nivel": partes[1] if len(partes) > 1 else "",
            "publicado": publicado,
            "idade_min": round((agora - publicado) / 60) if publicado else None,
            "propostas": int(m_prop.group(1)) if m_prop else None,
            "descricao": limpar(m_desc.group(1)) if m_desc else "",
            "habilidades": [limpar(h) for h in re.findall(r'<a class="habilidade">(.*?)</a>', bloco)],
            "cliente": limpar(m_cli.group(1)) if m_cli else "",
            "cliente_nota": float(m_nota.group(1)) if m_nota else None,
            "cliente_avaliacoes": int(m_aval.group(1)) if m_aval else 0,
            "urgente": "flag_project_urgent" in bloco,
            "plataforma": "99Freelas",
            "orcamento": None,
            "pagamento_verificado": False,
        })
    return projetos


def idade_workana(texto):
    """'há 21 minutos', 'Há quase uma hora', 'há 2 horas', 'há 1 dia' -> minutos."""
    t = sem_acento(texto).replace("publicado:", "").strip()
    if "agora" in t or "segundo" in t:
        return 0
    if "quase uma hora" in t:
        return 55
    m = re.search(r"(\d+|uma|um)\s+(minuto|hora|dia|semana|mes)", t)
    if not m:
        return None
    n = 1 if m.group(1) in ("um", "uma") else int(m.group(1))
    return n * {"minuto": 1, "hora": 60, "dia": 1440, "semana": 10080, "mes": 43200}[m.group(2)]


def ler_workana(url):
    pagina = baixar(url)
    m = re.search(r":results-initials='([^']+)'", pagina)
    if not m:
        print(f"[aviso] Workana sem resultados em {url}")
        return []
    try:
        dados = json.loads(html.unescape(m.group(1)))
    except ValueError:
        return []
    projetos = []
    for r in dados.get("results", []):
        m_tit = re.search(r'<span title="([^"]+)"', r.get("title", ""))
        titulo = limpar(m_tit.group(1)) if m_tit else limpar(r.get("title", ""))
        descricao = limpar(r.get("description", "")).split("Categoria:")[0].strip()
        m_prop = re.search(r"(\d+)", r.get("totalBids", ""))
        try:
            nota_cliente = float((r.get("rating") or {}).get("value") or 0) or None
        except ValueError:
            nota_cliente = None
        projetos.append({
            "id": "wk:" + r["slug"],
            "titulo": titulo,
            "link": "https://www.workana.com/job/" + r["slug"],
            "subcategoria": "",
            "nivel": "",
            "publicado": None,
            "idade_min": idade_workana(r.get("postedDate", "")),
            "propostas": int(m_prop.group(1)) if m_prop else None,
            "descricao": descricao,
            "habilidades": [h.get("anchorText", "") for h in r.get("skills", [])],
            "cliente": r.get("authorName", ""),
            "cliente_nota": nota_cliente,
            "cliente_avaliacoes": 0,
            "urgente": bool(r.get("isUrgent")),
            "plataforma": "Workana",
            "orcamento": limpar(r.get("budget", "")) or None,
            "pagamento_verificado": bool(r.get("hasVerifiedPaymentMethod")),
        })
    return projetos


_cotacao = {}


def cotacao_dolar():
    if "usd" not in _cotacao:
        try:
            dados = json.loads(baixar("https://economia.awesomeapi.com.br/json/last/USD-BRL", tentativas=2))
            _cotacao["usd"] = float(dados["USDBRL"]["bid"])
        except Exception:
            _cotacao["usd"] = None
    return _cotacao["usd"]


def ler_orcamento(projeto):
    pagina = baixar(projeto["link"])
    m = re.search(r"<th>Or(?:ç|&ccedil;)amento:</th>\s*<td>(.*?)</td>", pagina, re.S)
    return limpar(m.group(1)) if m else "não informado"


# ---------------------------------------------------------------- proposta

EXPERIENCIA = {
    "planilhas": "Recentemente automatizei a planilha de operação de uma transportadora de containers "
                 "(Google Sheets + Apps Script): geração de documentos em PDF com um clique, integração "
                 "entre planilhas e correção de travamentos em horário de pico.",
    "automacao": "Tenho um robô em produção que entra num sistema web, baixa o relatório do dia, gera "
                 "imagens com os indicadores e envia por e-mail sozinho, em horário agendado.",
    "sistemas": "Entreguei há pouco um sistema web sob medida de abertura e acompanhamento de chamados, "
                "com login por perfil, painel, histórico e anexos, publicado na nuvem e acessível pelo celular.",
    "sites": "Desenvolvo páginas modernas, rápidas e responsivas, com foco em ficar bonitas no celular "
             "e levar o visitante até o contato (WhatsApp, formulário ou compra).",
}

COMO_FARIA = {
    "planilhas": [
        "entender o seu processo atual e onde está a dor (o que hoje é manual ou trava)",
        "montar a automação numa cópia, sem mexer no que já funciona",
        "testar com você e só depois passar para a versão oficial",
    ],
    "automacao": [
        "mapear o passo a passo que hoje é feito na mão",
        "construir o robô e rodar com você acompanhando os primeiros resultados",
        "deixar agendado, com aviso caso algo falhe",
    ],
    "sistemas": [
        "fechar com você as telas e o fluxo principal",
        "te mostrar um protótipo navegável logo nos primeiros dias",
        "ajustar com o seu retorno e publicar, com acesso pelo computador e pelo celular",
    ],
    "sites": [
        "alinhar o objetivo da página e o público",
        "te mostrar uma primeira versão rápida para você aprovar o visual",
        "ajustar, publicar e deixar pronta para receber contatos",
    ],
}

PERGUNTA = {
    "planilhas": "Hoje a planilha é no Google Sheets ou no Excel, e quantas pessoas usam ao mesmo tempo?",
    "automacao": "O sistema de onde vêm os dados tem login? E com que frequência a tarefa precisa rodar?",
    "sistemas": "Quantas pessoas vão usar e quais tipos de usuário (ex.: administrador, funcionário, cliente)?",
    "sites": "Você já tem textos, logo e fotos, ou prefere que eu proponha uma estrutura?",
}


def montar_proposta(projeto, servico):
    nome = projeto["cliente"].split(" ")[0] if projeto["cliente"] else ""
    if nome.endswith(".") or len(nome) <= 2:   # nome abreviado, ex.: "C. M."
        nome = ""
    saudacao = f"Olá, {nome}! Tudo bem?" if nome else "Olá! Tudo bem?"
    passos = "\n".join(f"{i}. {p[0].upper() + p[1:]};" for i, p in enumerate(COMO_FARIA[servico], 1))
    passos = passos[:-1] + "."
    return (
        f"{saudacao}\n\n"
        f"Li o seu projeto \"{projeto['titulo']}\" e consigo te ajudar.\n\n"
        f"{EXPERIENCIA[servico]}\n\n"
        f"Como eu faria:\n{passos}\n\n"
        f"Uma pergunta para eu te passar prazo e valor fechados: {PERGUNTA[servico]}\n\n"
        f"Fico à disposição para conversarmos.\n"
        f"Abraço,\nCaio"
    )


SOBRE_O_CAIO = """
- Sistema web sob medida de abertura e acompanhamento de chamados (Next.js + Supabase), com login por perfil,
  painel, histórico e anexos, publicado na nuvem e acessível pelo celular.
- Automação da planilha de operação de uma transportadora de containers (Google Sheets + Apps Script):
  documentos em PDF com um clique, integração entre planilhas, correção de travamentos em horário de pico.
- Robô em Python que entra num sistema web, baixa o relatório do dia, gera imagens com indicadores e envia
  por e-mail sozinho, em horário agendado.
- Robô que vigia sites e manda alertas no Telegram.
- Trabalha com IA para entregar rápido.
"""


def gerar_com_ia(projeto, servico):
    """Pede ao Gemini (grátis) um resumo e a proposta. Devolve None se não der."""
    chave = env("GEMINI_API_KEY")
    if not chave:
        return None
    prompt = f"""Você ajuda o Caio, freelancer brasileiro, a responder projetos em plataformas de freela.

O que o Caio já fez de verdade (use só isto como experiência, nunca invente outras):
{SOBRE_O_CAIO}

Projeto ({projeto['plataforma']}):
Título: {projeto['titulo']}
Cliente: {projeto['cliente'] or 'não informado'}
Habilidades pedidas: {', '.join(projeto['habilidades']) or 'não informado'}
Descrição:
{projeto['descricao'][:3000]}

Responda em JSON com duas chaves:
"resumo": uma frase curta e simples (máx. 20 palavras) explicando o que o cliente quer, para alguém leigo.
"proposta": a proposta em português do Brasil, de 90 a 160 palavras, tom profissional e próximo, que:
  - cumprimenta pelo primeiro nome do cliente, se houver (ignore abreviações como "R. A. B.");
  - mostra que leu o projeto, citando 1 ou 2 detalhes específicos dele;
  - cita a experiência do Caio mais parecida com o projeto (só as reais acima);
  - explica em 2 ou 3 passos curtos como ele faria;
  - faz 1 pergunta específica que o projeto não respondeu;
  - não fala preço nem prazo, não usa emojis, não promete nada que não está no projeto;
  - termina com "Abraço,\nCaio".
"""
    corpo = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.6},
    }).encode("utf-8")
    for modelo in MODELOS_IA:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"
        req = urllib.request.Request(url, data=corpo, headers={"Content-Type": "application/json", "x-goog-api-key": chave})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                resposta = json.loads(r.read())
            texto = resposta["candidates"][0]["content"]["parts"][0]["text"]
            dados = json.loads(texto)
            if dados.get("proposta"):
                return dados
        except urllib.error.HTTPError as erro:
            print(f"[ia] {modelo}: {erro.code} {erro.read().decode('utf-8', 'replace')[:200]}")
        except Exception as erro:
            print(f"[ia] {modelo}: {erro}")
    return None


# ---------------------------------------------------------------- telegram

def env(nome):
    valor = os.environ.get(nome)
    if valor:
        return valor
    arq = PASTA / ".env"
    if arq.exists():
        for linha in arq.read_text(encoding="utf-8").splitlines():
            if linha.strip().startswith(nome + "="):
                return linha.split("=", 1)[1].strip().strip('"')
    return None


def telegram(metodo, dados):
    token = env("TELEGRAM_TOKEN")
    if not token:
        sys.exit("Falta o TELEGRAM_TOKEN (no .env ou nos Secrets do GitHub).")
    url = f"https://api.telegram.org/bot{token}/{metodo}"
    corpo = json.dumps(dados).encode("utf-8")
    req = urllib.request.Request(url, data=corpo, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        print(f"[erro telegram] {e.code}: {e.read().decode('utf-8', 'replace')}")
        return None


def enviar(texto, botao=None, silencioso=False):
    dados = {
        "chat_id": env("TELEGRAM_CHAT_ID"),
        "text": texto,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
        "disable_notification": silencioso,
    }
    if botao:
        dados["reply_markup"] = {"inline_keyboard": [[{"text": botao[0], "url": botao[1]}]]}
    return telegram("sendMessage", dados)


def e(t):
    return html.escape(t or "", quote=False)


def tempo_atras(minutos):
    if minutos is None:
        return "?"
    if minutos < 60:
        return f"há {minutos} min"
    return f"há {minutos // 60}h{minutos % 60:02d}"


def montar_alerta(projeto, nota, servico, motivos, orcamento, resumo=None):
    """A 1ª e a 2ª linha são o que aparece no pop-up do iPhone: precisam dizer tudo."""
    chamas = "🔥" * (3 if nota >= 9 else 2 if nota >= 8 else 1)
    facil = "🟢 Fácil" if e_facil(projeto) else "🟡 Aprender"
    preco = preco_do_projeto(projeto, servico, orcamento)
    propostas = projeto["propostas"] if projeto["propostas"] is not None else "?"
    valores = re.findall(r"R\$ [\d.]+", preco)
    preco_curto = "–".join(valores[:2]) if valores else "a combinar"
    if "menos de" in preco:
        preco_curto = "até " + preco_curto
    elif "mais de" in preco:
        preco_curto = "+ de " + preco_curto
    if "por hora" in preco:
        preco_curto += "/h"

    cliente = projeto["cliente"] or "Cliente"
    if projeto["cliente_avaliacoes"]:
        cliente += f" · ⭐ {projeto['cliente_nota']:.1f} ({projeto['cliente_avaliacoes']} aval.)"
    elif projeto["cliente_nota"]:
        cliente += f" · ⭐ {projeto['cliente_nota']:.1f}"
    else:
        cliente += " · sem avaliações"
    if projeto["pagamento_verificado"]:
        cliente += " · 💳 verificado"

    descricao = projeto["descricao"]
    if len(descricao) > 300:
        descricao = descricao[:300].rsplit(" ", 1)[0] + "…"

    linhas = [
        f"{chamas} <b>{nota}/10 · {e(projeto['titulo'])}</b>",
        f"{facil} · 💰 {e(preco_curto)} · 📨 {propostas} · {tempo_atras(projeto['idade_min'])}",
        "",
        f"💰 {e(preco)}",
        f"📍 {projeto['plataforma']} · porte {['pequeno', 'médio', 'grande'][porte_do_projeto(projeto)]}",
        f"👤 {e(cliente)}",
    ]
    if projeto["habilidades"]:
        linhas.append(f"🏷 {e(', '.join(projeto['habilidades'][:5]))}")
    if resumo:
        linhas += ["", f"🧠 <b>Em resumo:</b> {e(resumo)}"]
    linhas += ["", f"<i>{e(descricao)}</i>", "", f"💡 {e(', '.join(motivos))}"]
    return "\n".join(linhas)


# ---------------------------------------------------------------- execução

def carregar_vistos():
    if ARQ_VISTOS.exists():
        return json.loads(ARQ_VISTOS.read_text(encoding="utf-8"))
    return {}


def salvar_vistos(vistos):
    limite = time.time() - DIAS_GUARDAR_VISTOS * 86400
    vistos = {k: v for k, v in vistos.items() if v >= limite}
    ARQ_VISTOS.write_text(json.dumps(vistos, indent=0, sort_keys=True), encoding="utf-8")


def rodar(teste=False):
    vistos = carregar_vistos()
    primeira_vez = not vistos
    projetos = {}
    for caminho in LISTAS:
        for p in ler_lista(caminho):
            projetos.setdefault(p["id"], p)
        time.sleep(1.5)
    for url in LISTAS_WORKANA:
        for p in ler_workana(url):
            projetos.setdefault(p["id"], p)
        time.sleep(1.5)
    print(f"{len(projetos)} projetos lidos.")

    candidatos = []
    for p in projetos.values():
        if p["id"] in vistos and not teste:
            continue
        vistos[p["id"]] = time.time()
        if p["idade_min"] is None or p["idade_min"] > IDADE_MAX_HORAS * 60:
            continue
        nota, servico, motivos = nota_do_projeto(p)
        if nota >= NOTA_MINIMA:
            candidatos.append((nota, p, servico, motivos))

    candidatos.sort(key=lambda c: (-c[0], c[1]["idade_min"] or 0))
    candidatos = candidatos[:MAX_ALERTAS_POR_RODADA]
    print(f"{len(candidatos)} projetos com a sua cara.")

    if primeira_vez and not teste:
        enviar("🎯 <b>Caçador de clientes ligado!</b>\nVou te avisar aqui sempre que aparecer projeto com a sua cara no 99Freelas e no Workana.")

    for nota, p, servico, motivos in candidatos:
        orcamento = p["orcamento"] or ler_orcamento(p)
        ia = gerar_com_ia(p, servico)
        proposta = ia["proposta"] if ia else montar_proposta(p, servico)
        alerta = montar_alerta(p, nota, servico, motivos, orcamento, ia.get("resumo") if ia else None)
        autor = "✨ escrita pela IA" if ia else "modelo pronto"
        if teste:
            print("\n" + "=" * 60 + "\n" + re.sub(r"<[^>]+>", "", alerta) + f"\n\n--- PROPOSTA ({autor}) ---\n" + proposta)
            continue
        enviar(alerta, botao=(f"Abrir no {p['plataforma']}", p["link"]))
        enviar(f"✍️ <b>Rascunho da proposta</b> ({autor}, toque no texto para copiar)\n\n<pre>" + e(proposta) + "</pre>",
               silencioso=True)
        time.sleep(1)

    if not teste:
        salvar_vistos(vistos)


def descobrir_chat_id():
    r = telegram("getUpdates", {})
    if not r or not r.get("result"):
        print("Nenhuma mensagem encontrada. Mande um 'oi' para o seu bot no Telegram e rode de novo.")
        return
    for u in r["result"]:
        chat = (u.get("message") or {}).get("chat")
        if chat:
            print(f"Seu chat_id é: {chat['id']}  ({chat.get('first_name', '')})")
            return


if __name__ == "__main__":
    if "--chat-id" in sys.argv:
        descobrir_chat_id()
    elif "--ping" in sys.argv:
        r = enviar("✅ Teste do Caçador de clientes: o Telegram está funcionando!")
        print("Enviado!" if r and r.get("ok") else "Não foi. Confira o token e o chat_id.")
    else:
        rodar(teste="--teste" in sys.argv)
