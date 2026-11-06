#!/usr/bin/env python3
"""Cria (uma vez) as pastas e os 4 modelos de contrato no Google Docs do
escritorio, a partir do contrato_template.html + OBJETO_VARIANTES do app.py.

Uso: python3 scripts/criar_modelos_docs.py  (le o vault ~/.credentials/clients/kadia.env)
Imprime os ids pra configurar no Coolify (DOCS_*). Rodar de novo cria outra leva.
"""
import ast
import json
import os
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def env(k):
    return subprocess.run(['bash', '-c', f'source ~/.credentials/clients/kadia.env; printf "%s" "${k}"'],
                          capture_output=True, text=True).stdout.strip()


def token():
    corpo = urllib.parse.urlencode({
        "client_id": env("GOOGLE_OAUTH_CLIENT_ID"), "client_secret": env("GOOGLE_OAUTH_CLIENT_SECRET"),
        "refresh_token": env("GOOGLE_OAUTH_REFRESH_TOKEN"), "grant_type": "refresh_token"}).encode()
    return json.load(urllib.request.urlopen("https://oauth2.googleapis.com/token", corpo))["access_token"]


TK = token()


def req(metodo, url, corpo=None, headers=None, bruto=None):
    h = {"Authorization": "Bearer " + TK}
    if corpo is not None:
        h["Content-Type"] = "application/json"
    h.update(headers or {})
    data = bruto if bruto is not None else (json.dumps(corpo).encode() if corpo is not None else None)
    import time
    for tentativa in range(4):
        try:
            r = urllib.request.urlopen(urllib.request.Request(url, data=data, method=metodo, headers=h))
            break
        except urllib.error.HTTPError as e:
            if e.code < 500 or tentativa == 3:
                raise
            time.sleep(3 * (tentativa + 1))
    c = r.read()
    return json.loads(c) if c else {}


def pasta(nome, pai=None):
    corpo = {"name": nome, "mimeType": "application/vnd.google-apps.folder"}
    if pai:
        corpo["parents"] = [pai]
    return req("POST", "https://www.googleapis.com/drive/v3/files?fields=id", corpo)["id"]


def objeto_variantes():
    src = open(os.path.join(BASE, "app.py"), encoding="utf-8").read()
    arv = ast.parse(src)
    for no in arv.body:
        if isinstance(no, ast.Assign) and getattr(no.targets[0], "id", "") == "OBJETO_VARIANTES":
            return ast.literal_eval(no.value)
    raise SystemExit("OBJETO_VARIANTES nao encontrado")


P_STYLE = "font-family:Times New Roman;font-size:10.5pt;line-height:1.5;text-align:justify;margin:0 0 8pt 0"
AZUL = "#12224a"


def html_docs(tipo):
    html = open(os.path.join(BASE, "contrato_template.html"), encoding="utf-8").read()
    corpo = html[html.index('<div class="conteudo">') + len('<div class="conteudo">'):html.rindex("</div>")]
    corpo = corpo.replace("{{OBJETO_DESCRICAO}}", objeto_variantes()[tipo])
    corpo = re.sub(r"<h1>(.*?)</h1>",
                   lambda m: f'<p style="text-align:center;font-family:Times New Roman;font-size:13pt;color:{AZUL};margin:0 0 18pt 0"><b>{m.group(1)}</b></p>',
                   corpo, flags=re.S)
    corpo = re.sub(r'<p class="clausula"><h2>(.*?)</h2>',
                   lambda m: f'<p><b style="color:{AZUL}">{m.group(1)}</b>', corpo, flags=re.S)
    corpo = corpo.replace('<span class="campo">{{NOME_CONTRATANTE}}</span>', "<b>{{NOME_CONTRATANTE}}</b>")
    corpo = corpo.replace('<p class="local-data">', '<p style="margin:24pt 0 30pt 0">')
    # bloco de assinaturas e testemunhas: linhas simples (a assinatura vale pelo Autentique)
    ini = corpo.index('<div class="assinaturas">')
    corpo = corpo[:ini] + (
        '<p style="text-align:center;margin:30pt 0 0 0">________________________________________________</p>'
        '<p style="text-align:center;margin:0 0 24pt 0">Contratada: LEGADO E GOVERNANÇA FAMILIAR LTDA</p>'
        '<p style="text-align:center;margin:30pt 0 0 0">________________________________________________</p>'
        '<p style="text-align:center;margin:0 0 24pt 0">Contratante: {{NOME_CONTRATANTE}}</p>'
        '<p style="margin:18pt 0 18pt 0">Testemunhas:</p>'
        '<table style="width:100%;border:none;border-collapse:collapse"><tr>'
        '<td style="width:50%;border:none;padding:0 12pt 0 0">______________________________<br>Nome:<br>CPF:</td>'
        '<td style="width:50%;border:none;padding:0 0 0 12pt">______________________________<br>Nome:<br>CPF:</td>'
        '</tr></table>')
    corpo = re.sub(r"<p>\s*</p>", "", corpo)
    # estilo base em todo paragrafo/item que nao tem estilo proprio
    corpo = re.sub(r"<p>", f'<p style="{P_STYLE}">', corpo)
    corpo = re.sub(r'<p style="(?!font-family)([^"]*)">',
                   lambda m: f'<p style="font-family:Times New Roman;font-size:10.5pt;line-height:1.5;{m.group(1)}">', corpo)
    corpo = corpo.replace("<li>", f'<li style="{P_STYLE};margin:0 0 4pt 0">')
    return ('<html><head><meta charset="utf-8"></head><body style="font-family:Times New Roman;font-size:10.5pt">'
            + corpo + "</body></html>")


def criar_doc(nome, html, pai):
    limite = "kadia-limite-123"
    meta = json.dumps({"name": nome, "mimeType": "application/vnd.google-apps.document", "parents": [pai]})
    corpo = (f"--{limite}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{meta}\r\n"
             f"--{limite}\r\nContent-Type: text/html; charset=UTF-8\r\n\r\n{html}\r\n--{limite}--").encode()
    r = req("POST", "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&fields=id",
            headers={"Content-Type": f"multipart/related; boundary={limite}"}, bruto=corpo)
    did = r["id"]
    mm = 2.8346  # pt por mm. Margens iguais ao PDF atual (@page 45/25/48/25 mm), A4.
    req("POST", f"https://docs.googleapis.com/v1/documents/{did}:batchUpdate", {"requests": [{
        "updateDocumentStyle": {
            "documentStyle": {
                "pageSize": {"width": {"magnitude": 595.28, "unit": "PT"}, "height": {"magnitude": 841.89, "unit": "PT"}},
                "marginTop": {"magnitude": 45 * mm, "unit": "PT"}, "marginBottom": {"magnitude": 48 * mm, "unit": "PT"},
                "marginLeft": {"magnitude": 25 * mm, "unit": "PT"}, "marginRight": {"magnitude": 25 * mm, "unit": "PT"}},
            "fields": "pageSize,marginTop,marginBottom,marginLeft,marginRight"}}]})
    return did


def compartilhar_link_editor(file_id):
    req("POST", f"https://www.googleapis.com/drive/v3/files/{file_id}/permissions",
        {"type": "anyone", "role": "writer", "allowFileDiscovery": False})


if __name__ == "__main__":
    import sys
    if len(sys.argv) == 4:  # reaproveita pastas existentes: raiz modelos clientes
        raiz, modelos, clientes = sys.argv[1:4]
    else:
        raiz = pasta("Contratos Kádia Barro (sistema)")
        modelos = pasta("Modelos de Contrato", raiz)
        clientes = pasta("Contratos de Clientes", raiz)
        compartilhar_link_editor(raiz)
    nomes = {"1 célula": "1_CELULA", "2 células": "2_CELULAS", "3 células": "3_CELULAS", "internacional": "INTERNACIONAL"}
    titulos = {"1 célula": "1 Célula", "2 células": "2 Células", "3 células": "3 Células", "internacional": "Internacional"}
    saida = {"DOCS_PASTA_RAIZ": raiz, "DOCS_PASTA_MODELOS": modelos, "DOCS_PASTA_CLIENTES": clientes}
    for tipo, chave in nomes.items():
        saida["DOCS_MODELO_" + chave] = criar_doc(f"Modelo - Contrato {titulos[tipo]}", html_docs(tipo), modelos)
    print(json.dumps(saida, indent=1))
