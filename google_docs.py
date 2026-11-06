"""Contrato em Google Docs (Kadia, 06/11/2026).

O contrato de cada cliente vira um Google Doc no Drive do escritorio
(Workspace kadiabarroholdings.com, conta contato@). A equipe edita o Doc
direto antes de mandar assinar; o PDF de assinatura sai do proprio Doc.

- Modelos: 4 Docs (1, 2, 3 Celulas e Internacional) na pasta Modelos, com
  campos {{...}} que o sistema troca. Mudar o texto do modelo muda os
  contratos novos dali pra frente.
- criar_contrato(): copia o modelo do tipo de holding pra pasta Clientes e
  preenche nome, qualificacao, honorarios e estado com beneficio fiscal.
  {{DATA_EXTENSO}} fica no Doc e so e preenchido na hora de gerar o PDF.
- campos_pendentes(): lista os {{...}} que ainda sobraram (bloqueia o envio).
- exportar_pdf(): copia temporaria com a data do dia, exporta PDF e apaga a copia.

Acesso: OAuth interno do Workspace (projeto GCP kadia-contratos-513919),
refresh token da conta contato@ em GOOGLE_REFRESH_TOKEN.
"""
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
REFRESH_TOKEN = os.environ.get("GOOGLE_REFRESH_TOKEN", "")
PASTA_CLIENTES = os.environ.get("DOCS_PASTA_CLIENTES", "")
MODELOS = {
    "1 célula": os.environ.get("DOCS_MODELO_1_CELULA", ""),
    "2 células": os.environ.get("DOCS_MODELO_2_CELULAS", ""),
    "3 células": os.environ.get("DOCS_MODELO_3_CELULAS", ""),
    "internacional": os.environ.get("DOCS_MODELO_INTERNACIONAL", ""),
}

_token = {"valor": "", "expira": 0}
CAMPO_RE = re.compile(r"\{\{[A-Z_]+\}\}")


class GoogleErro(Exception):
    pass


def _access_token():
    if _token["valor"] and time.time() < _token["expira"] - 60:
        return _token["valor"]
    corpo = urllib.parse.urlencode({
        "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET,
        "refresh_token": REFRESH_TOKEN, "grant_type": "refresh_token",
    }).encode()
    r = json.load(urllib.request.urlopen("https://oauth2.googleapis.com/token", corpo, timeout=20))
    _token["valor"] = r["access_token"]
    _token["expira"] = time.time() + int(r.get("expires_in", 3600))
    return _token["valor"]


def _req(metodo, url, corpo=None, bruto=False):
    dados = json.dumps(corpo).encode() if corpo is not None else None
    req = urllib.request.Request(url, data=dados, method=metodo, headers={
        "Authorization": "Bearer " + _access_token(),
        "Content-Type": "application/json",
    })
    try:
        resp = urllib.request.urlopen(req, timeout=60)
    except urllib.error.HTTPError as e:
        raise GoogleErro(f"{metodo} {url.split('?')[0]} -> {e.code}: {e.read().decode(errors='ignore')[:300]}")
    conteudo = resp.read()
    if bruto:
        return conteudo
    return json.loads(conteudo) if conteudo else {}


def doc_id_de(texto):
    """Aceita o id puro ou qualquer link docs.google.com/document/d/<id>/..."""
    texto = (texto or "").strip()
    m = re.search(r"/document/d/([A-Za-z0-9_-]{20,})", texto)
    if m:
        return m.group(1)
    return texto if re.fullmatch(r"[A-Za-z0-9_-]{20,}", texto) else ""


def url_doc(doc_id):
    return f"https://docs.google.com/document/d/{doc_id}/edit"


def _copiar(doc_id, nome, pasta):
    corpo = {"name": nome}
    if pasta:
        corpo["parents"] = [pasta]
    r = _req("POST", f"https://www.googleapis.com/drive/v3/files/{doc_id}/copy?supportsAllDrives=true&fields=id", corpo)
    return r["id"]


def _apagar(doc_id):
    try:
        _req("DELETE", f"https://www.googleapis.com/drive/v3/files/{doc_id}?supportsAllDrives=true")
    except GoogleErro:
        pass


def _substituir(doc_id, valores):
    reqs = [{"replaceAllText": {"containsText": {"text": "{{" + k + "}}", "matchCase": True},
                                "replaceText": v}} for k, v in valores.items()]
    if reqs:
        _req("POST", f"https://docs.googleapis.com/v1/documents/{doc_id}:batchUpdate", {"requests": reqs})


def _texto(doc_id):
    d = _req("GET", f"https://docs.googleapis.com/v1/documents/{doc_id}")
    partes = []

    def andar(conteudo):
        for el in conteudo or []:
            if "paragraph" in el:
                for pe in el["paragraph"].get("elements", []):
                    partes.append(pe.get("textRun", {}).get("content", ""))
            elif "table" in el:
                for linha in el["table"].get("tableRows", []):
                    for cel in linha.get("tableCells", []):
                        andar(cel.get("content"))
    andar(d.get("body", {}).get("content"))
    return "".join(partes)


def criar_contrato(tipo, nome_arquivo, valores):
    modelo = MODELOS.get(tipo or "")
    if not modelo:
        raise GoogleErro(f"tipo de holding sem modelo no Docs: {tipo!r}")
    novo = _copiar(modelo, nome_arquivo, PASTA_CLIENTES)
    _substituir(novo, valores)
    return novo


def campos_pendentes(doc_id, ignorar=("{{DATA_EXTENSO}}",)):
    return sorted({c for c in CAMPO_RE.findall(_texto(doc_id)) if c not in ignorar})


FUNDO_BRANCO_RE = re.compile(rb"(1 1 1 rg\s*(?:/\w+ gs\s*)?0 0 [\d.]+ [\d.]+ re\s*)f\b")


def sem_fundo_branco(pdf_bytes):
    """O PDF exportado pelo Google pinta um retangulo branco na pagina inteira
    antes do texto, o que esconderia o papel timbrado aplicado por baixo.
    Troca o 'f' (preencher) desse primeiro retangulo por 'n' (nao desenhar)."""
    import io
    from pypdf import PdfReader, PdfWriter
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(pdf_bytes)))
    for pagina in writer.pages:
        conteudo = pagina.get_contents()
        if conteudo is None:
            continue
        dados = conteudo.get_data()
        novo = FUNDO_BRANCO_RE.sub(rb"\1n", dados, count=1)
        if novo != dados:
            conteudo.set_data(novo)
            pagina.replace_contents(conteudo)
    saida = io.BytesIO()
    writer.write(saida)
    return saida.getvalue()


def exportar_pdf(doc_id, data_extenso_str):
    temp = _copiar(doc_id, "temp-pdf-" + doc_id, PASTA_CLIENTES)
    try:
        _substituir(temp, {"DATA_EXTENSO": data_extenso_str})
        pdf = _req("GET", f"https://www.googleapis.com/drive/v3/files/{temp}/export?mimeType=application/pdf", bruto=True)
    finally:
        _apagar(temp)
    return sem_fundo_branco(pdf)
