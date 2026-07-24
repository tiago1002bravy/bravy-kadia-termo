# bravy-kadia-termo

Microservico HTTP que gera o Termo de Confidencialidade (Kadia Barro /
Legado e Governanca Familiar) em PDF, com papel timbrado, a partir de dados
enviados via JSON. Usado pelo workflow n8n `[comercial]negocio-fechado->onboarding`
(kadia.bravy.com.br) porque o n8n roda em container sem Chrome/Chromium.

## Endpoints

- `POST /termo` - Header `X-API-Key`. Body JSON com os campos abaixo. Retorna o PDF (binario).
- `GET /health` - healthcheck.

### Campos aceitos (todos opcionais - vazio vira lacuna pontilhada no documento)

`nome, nacionalidade, estado_civil, profissao, rg, cpf, endereco, dpo, data`

`data` default = data de hoje por extenso, formato "24 de julho de 2026".

## Origem

Adaptado de `~/codigos/clientes/kadia/termo-confidencialidade/render.py` (script local
validado no Mac, usa Chrome headless + pypdf para estampar o timbre por baixo de
cada pagina, porque o `background: fixed` do Chromium so aparece na 1a pagina do
print-to-pdf).

## Deploy

Coolify, projeto `kadia-termo`, build pack `dockerfile`, porta 8080,
dominio `termo-kadia.bravy.com.br`. Variavel de ambiente `TERMO_API_TOKEN`
(shared secret, o n8n manda no header `X-API-Key`).
