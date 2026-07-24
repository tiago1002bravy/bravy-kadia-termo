# bravy-kadia-termo

Microservico HTTP que gera o Termo de Confidencialidade (Kadia Barro /
Legado e Governanca Familiar) em PDF, com papel timbrado, a partir de dados
do webhook da Hotmart. Usado pelo workflow n8n `[comercial]negocio-fechado->onboarding`
(kadia.bravy.com.br) porque o n8n roda em container sem Chrome/Chromium.

## Endpoints

- `POST /termo` - Header `X-API-Key`. Retorna o PDF (binario).
- `GET /health` - healthcheck.

### Body do POST /termo

Só usa o que a Hotmart entrega em `data.buyer.*` (nome, CPF, endereço) + o
e-mail do DPO (fixo do escritório) + a data (automática). Nada de
nacionalidade/estado civil/profissão/RG — a Hotmart não entrega isso, então
esses campos foram removidos do documento.

Aceita 2 formatos (pode misturar):

```json
{ "nome": "Fulano de Tal", "cpf": "12345678900", "endereco": "Rua X, 1, Bairro, Cidade/UF, CEP 00000-000" }
```

ou, mais perto do payload cru da Hotmart:

```json
{
  "nome": "Fulano de Tal",
  "cpf": "12345678900",
  "endereco_raw": {
    "address": "Rua X", "number": "1", "complement": "Apto 2",
    "neighborhood": "Centro", "city": "Belo Horizonte", "state": "Minas Gerais",
    "zipcode": "30130000"
  }
}
```

`endereco_raw` é formatado internamente (CPF mascarado, estado → UF, CEP
mascarado, endereço por extenso) com a MESMA lógica de
`~/codigos/clientes/kadia/termo-confidencialidade/render.py::de_hotmart()`.
Campo ausente/vazio vira lacuna pontilhada — nunca quebra a geração.

`dpo`, se omitido no body, cai pra env `DPO_EMAIL` (config do escritório,
não varia por cliente; a Kádia ainda não informou esse e-mail).

## Deploy

Coolify, projeto `kadia-termo`, build pack `dockerfile`, porta 8080,
domínio `termo-kadia.bravy.com.br`. Variáveis de ambiente `TERMO_API_TOKEN`
(shared secret, o n8n manda no header `X-API-Key`) e `DPO_EMAIL` (ainda vazia).
