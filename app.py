#!/usr/bin/env python3
"""Microservico HTTP que gera o Termo de Confidencialidade (Kadia Barro) em PDF.

POST /termo
  Header: X-API-Key: <TERMO_API_TOKEN>
  Body JSON: { nome, nacionalidade, estado_civil, profissao, rg, cpf, endereco, dpo, data }
  Campo ausente/vazio vira lacuna pontilhada no PDF (nunca quebra a geracao).
  Resposta: application/pdf (binario)

GET /health -> {"status": "ok"}

Reaproveita a logica de ~/codigos/clientes/kadia/termo-confidencialidade/render.py:
Chrome/Chromium headless imprime o HTML em PDF, depois pypdf estampa o papel
timbrado (logo-header.png) por baixo de cada pagina (o Chromium nao repete
background fixed em todas as paginas do print-to-pdf).
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

MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho",
         "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]

PLACEHOLDER = '<span style="color:#888">' + "&nbsp;" * 20 + "</span>"

CAMPOS = {
    "NOME_CLIENTE": "nome",
    "NACIONALIDADE": "nacionalidade",
    "ESTADO_CIVIL": "estado_civil",
    "PROFISSAO": "profissao",
    "RG": "rg",
    "CPF": "cpf",
    "ENDERECO_COMPLETO": "endereco",
    "EMAIL_DPO": "dpo",
    "DATA_EXTENSO": "data",
}

app = Flask(__name__)


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

    dados = request.get_json(silent=True) or {}

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
