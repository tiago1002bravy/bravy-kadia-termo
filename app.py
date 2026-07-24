#!/usr/bin/env python3
"""Microservico HTTP que gera o Termo de Confidencialidade (Kadia Barro) em PDF.

POST /termo
  Header: X-API-Key: <TERMO_API_TOKEN>
  Body JSON aceita 2 formatos pros dados do cliente (pode misturar):
    - campos ja prontos: nome, cpf, endereco (string formatada), dpo, data
    - endereco_raw: objeto no formato data.buyer.address da Hotmart
      { address, number, complement, neighborhood, city, state, zipcode }
      (nesse caso o endereco final e montado aqui, com a MESMA logica do
      render.py local: state "Minas Gerais" -> "MG", CEP mascarado, etc.)
    - cpf tambem aceita digitos crus ou ja mascarado, sempre normalizado aqui.
  Campo ausente/vazio vira lacuna pontilhada no PDF (nunca quebra a geracao).
  dpo, se omitido, cai pra env DPO_EMAIL (config do escritorio, nao varia por cliente).
  Resposta: application/pdf (binario)

GET /health -> {"status": "ok"}

Espelha ~/codigos/clientes/kadia/termo-confidencialidade/render.py (mesmo
template.html, mesma logica de formatacao de CPF/endereco em de_hotmart()) —
so os dados que a Hotmart entrega em data.buyer.* (nome, cpf, endereco) vao
pro termo. NACIONALIDADE/ESTADO_CIVIL/PROFISSAO/RG foram removidos do
documento porque a Hotmart nao entrega esses campos.
"""
import base64
import mimetypes
import os
import re
import subprocess
import tempfile
from datetime import date

from flask import Flask, request, jsonify, send_file, abort

BASE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(BASE, "template.html")
TIMBRE_CACHE = os.path.join(BASE, "assets", "timbre.pdf")
CHROME = os.environ.get("CHROME_BIN", "/usr/bin/chromium")
API_TOKEN = os.environ.get("TERMO_API_TOKEN", "")
DPO_EMAIL_DEFAULT = os.environ.get("DPO_EMAIL", "")

MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho",
         "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]

PLACEHOLDER = '<span style="color:#888">' + "&nbsp;" * 20 + "</span>"

# so campos que a Hotmart entrega no webhook (data.buyer.*) + fixos do escritorio
CAMPOS = {
    "NOME_CLIENTE": "nome",
    "CPF": "cpf",
    "ENDERECO_COMPLETO": "endereco",
    "EMAIL_DPO": "dpo",
    "DATA_EXTENSO": "data",
}

UF = {
    "acre": "AC", "alagoas": "AL", "amapá": "AP", "amazonas": "AM", "bahia": "BA",
    "ceará": "CE", "distrito federal": "DF", "espírito santo": "ES", "goiás": "GO",
    "maranhão": "MA", "mato grosso": "MT", "mato grosso do sul": "MS",
    "minas gerais": "MG", "pará": "PA", "paraíba": "PB", "paraná": "PR",
    "pernambuco": "PE", "piauí": "PI", "rio de janeiro": "RJ",
    "rio grande do norte": "RN", "rio grande do sul": "RS", "rondônia": "RO",
    "roraima": "RR", "santa catarina": "SC", "são paulo": "SP",
    "sergipe": "SE", "tocantins": "TO",
}

app = Flask(__name__)


def formata_cpf(doc):
    d = re.sub(r"\D", "", doc or "")
    if len(d) == 11:
        return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"
    if len(d) == 14:  # CNPJ, caso o comprador seja PJ
        return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"
    return doc or ""


def formata_cep(cep):
    d = re.sub(r"\D", "", cep or "")
    return f"{d[:5]}-{d[5:]}" if len(d) == 8 else (cep or "")


def monta_endereco(addr):
    """Monta o endereco por extenso a partir de data.buyer.address da Hotmart."""
    if not isinstance(addr, dict):
        return ""
    estado = (addr.get("state") or "").strip()
    uf = UF.get(estado.lower(), estado)
    cidade = (addr.get("city") or "").strip()
    cidade_uf = "/".join(p for p in [cidade, uf] if p)
    partes = [
        (addr.get("address") or "").strip(),
        (addr.get("number") or "").strip(),
        (addr.get("complement") or "").strip(),
        (addr.get("neighborhood") or "").strip(),
        cidade_uf,
    ]
    endereco = ", ".join(p for p in partes if p)
    cep = formata_cep(addr.get("zipcode"))
    if cep:
        endereco += f", CEP {cep}"
    return endereco


def data_extenso(d=None):
    d = d or date.today()
    return f"{d.day:02d} de {MESES[d.month - 1]} de {d.year}"


def embutir_assets(html):
    """Troca src/url de arquivos locais por data URI (Chromium headless nao
    carrega caminho relativo quando o HTML vem de um arquivo temporario)."""
    def repl(m):
        rel = m.group(1)
        caminho = os.path.join(BASE, rel)
        if not os.path.exists(caminho):
            return m.group(0)
        mime = mimetypes.guess_type(caminho)[0] or "application/octet-stream"
        b64 = base64.b64encode(open(caminho, "rb").read()).decode()
        return f'url("data:{mime};base64,{b64}")'
    return re.sub(r'url\("([^"]+)"\)', repl, html)


def html_para_pdf(html, saida):
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
        f.write(html)
        tmp = f.name
    try:
        subprocess.run([
            CHROME, "--headless", "--disable-gpu", "--no-sandbox",
            "--disable-dev-shm-usage", "--no-pdf-header-footer",
            f"--print-to-pdf={os.path.abspath(saida)}", f"file://{tmp}",
        ], check=True, capture_output=True, timeout=60)
    finally:
        os.unlink(tmp)


def timbre_pdf():
    """Gera (e cacheia) o papel timbrado A4 full-bleed como PDF de 1 pagina."""
    if os.path.exists(TIMBRE_CACHE):
        return TIMBRE_CACHE
    html = embutir_assets(
        '<!doctype html><html><head><meta charset="utf-8"><style>'
        "@page{size:A4;margin:0}html,body{margin:0;padding:0}"
        ".p{width:210mm;height:297mm;"
        'background-image:url("assets/logo-header.png");'
        "background-size:210mm 297mm;background-repeat:no-repeat}"
        "</style></head><body><div class=p></div></body></html>"
    )
    html_para_pdf(html, TIMBRE_CACHE)
    return TIMBRE_CACHE


def estampar_timbre(pdf_conteudo, saida):
    from pypdf import PdfReader, PdfWriter

    conteudo = PdfReader(pdf_conteudo)
    writer = PdfWriter()
    for pagina in conteudo.pages:
        fundo = PdfReader(timbre_pdf()).pages[0]
        fundo.merge_page(pagina)
        writer.add_page(fundo)
    with open(saida, "wb") as f:
        writer.write(f)


def preparar_dados(payload):
    """Normaliza o body recebido: aceita campos prontos e/ou endereco_raw
    (formato data.buyer.address da Hotmart), sem nunca quebrar por campo
    faltando."""
    dados = dict(payload or {})
    if dados.get("cpf"):
        dados["cpf"] = formata_cpf(dados["cpf"])
    endereco_raw = dados.pop("endereco_raw", None)
    if not (dados.get("endereco") or "").strip() and endereco_raw:
        dados["endereco"] = monta_endereco(endereco_raw)
    if not (dados.get("dpo") or "").strip():
        dados["dpo"] = DPO_EMAIL_DEFAULT
    return dados


def render(dados, saida):
    html = open(TEMPLATE, encoding="utf-8").read()
    dados = dict(dados)
    dados.setdefault("data", data_extenso())
    for chave, campo in CAMPOS.items():
        valor = (dados.get(campo) or "").strip()
        html = html.replace("{{" + chave + "}}", valor if valor else PLACEHOLDER)
    html = embutir_assets(html)

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        bruto = f.name
    try:
        html_para_pdf(html, bruto)
        estampar_timbre(bruto, saida)
    finally:
        os.unlink(bruto)
    return saida


def slugify(texto):
    texto = (texto or "cliente").strip().lower()
    texto = re.sub(r"[^a-z0-9]+", "-", texto)
    return texto.strip("-") or "cliente"


@app.get("/health")
def health():
    return jsonify(status="ok")


@app.post("/termo")
def termo():
    if API_TOKEN:
        chave = request.headers.get("X-API-Key", "")
        if chave != API_TOKEN:
            abort(401, description="X-API-Key invalido ou ausente")

    dados = preparar_dados(request.get_json(silent=True) or {})

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        saida = f.name
    try:
        render(dados, saida)
        nome_arquivo = f"termo-confidencialidade-{slugify(dados.get('nome'))}.pdf"
        resp = send_file(saida, mimetype="application/pdf",
                          as_attachment=True, download_name=nome_arquivo)
        resp.call_on_close(lambda: os.path.exists(saida) and os.unlink(saida))
        return resp
    except subprocess.CalledProcessError as e:
        if os.path.exists(saida):
            os.unlink(saida)
        return jsonify(error="falha ao gerar PDF", detalhe=e.stderr.decode(errors="ignore") if e.stderr else str(e)), 500
    except Exception as e:
        if os.path.exists(saida):
            os.unlink(saida)
        return jsonify(error="falha ao gerar PDF", detalhe=str(e)), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
