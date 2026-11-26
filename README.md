# Plataforma de IA como Serviço — C3.A2

**Projeto integrador cloud-native · Sistemas Distribuídos e Computação em Nuvem · FAESA 2026/2**
Prof. M.Sc. Howard Cruz Roatti · Entrega: 26/11/2026

> Sistema distribuído completo: microsserviços conteinerizados, orquestrados
> por docker-compose, publicados na nuvem, observáveis (rastreamento
> distribuído) e protegidos (JWT + rate limit + HTTPS). O modelo de IA é a
> carga de trabalho — a nota vem da engenharia distribuída.

**Equipe:** [PREENCHER: nome 1], [PREENCHER: nome 2], [PREENCHER: nome 3]

**URL pública (HTTPS):** [PREENCHER após o deploy — ex.: https://plataforma-gateway.onrender.com]

---

## 1. Arquitetura

```
                        ┌─────────────────── JAEGER (rastreamento) ───────────────────┐
                        │      um ÚNICO trace atravessa toda a plataforma             ▼
 cliente ──HTTPS──► ┌────────────┐  síncrono (timeout·retry·CB)  ┌────────────┐   HTTP  ┌────────────┐
                    │  GATEWAY   │──────────────────────────────►│ INFERÊNCIA │◄────────│   WORKER   │
                    │ JWT·rate·CB│                               │modelo local│         │ fila+vetor │
                    └─────┬──────┘                               └────────────┘         └─────┬──────┘
                          │ assíncrono: enfileira (LPUSH)                                    │ grava resultado (TTL)
                          ▼                                                                  ▼
                   ┌──────────────┐   BRPOP (worker consome)                          ┌────────────┐
                   │    REDIS     │──────────────────────────────────────────────────►│   QDRANT   │
                   │ fila+estado  │                                                   │  vetorial  │
                   └──────────────┘                                                   └────────────┘
          PROMETHEUS (métricas) ──► GRAFANA (painel) · AUTOESCALADOR (fila) · EDGE (borda, opcional)
```

| Serviço          | Papel                                                    | Porta (host)          |
|------------------|----------------------------------------------------------|-----------------------|
| `gateway`        | Porta de entrada ÚNICA: JWT, rate limit, resiliência     | 8000                  |
| `inferencia`     | IA como biblioteca: modelo scikit-learn local (offline)  | interna (8001)        |
| `worker`         | Consome a fila; grava resultado (Redis) e vetor (Qdrant) | interna (8002)        |
| `qdrant`         | **Armazenamento vetorial** — memória semântica           | 6333                  |
| `redis`          | Fila + rate limit + resultados com TTL                   | 6379                  |
| `jaeger`         | Rastreamento distribuído (UI)                            | 16686                 |
| `prometheus`     | Coleta de métricas                                       | 9090                  |
| `grafana`        | Painel de métricas (admin/admin)                         | 3000                  |
| `autoescalador`  | Recomenda réplicas conforme o tamanho da fila            | 8003                  |

Dois caminhos de processamento (decisão de arquitetura chave):

- **Síncrono `/predict`** — baixa latência; protegido por timeout + retentativa
  + circuit breaker; se a inferência está fora, a tarefa **cai na fila** e o
  cliente recebe `202` (degradação graciosa, sem erro).
- **Assíncrono `/tarefas`** — enfileira e devolve `202` + id; o worker processa
  e `GET /tarefas/{id}` devolve o resultado quando pronto.

## 2. Como executar do zero (UM comando)

Pré-requisito: **Docker** (Docker Desktop ou Engine). Não precisa de GPU,
internet após o pull das imagens, nem chave de API.

```bash
# 1. Clone o repositório
git clone https://github.com/SEU-USUARIO/SEU-REPO.git
cd SEU-REPO

# 2. Configure o ambiente
cp .env.example .env          # edite JWT_SEGREDO e USUARIOS em produção

# 3. Suba o sistema INTEIRO com UM comando
docker compose up --build -d

# 4. Teste o fluxo completo (gateway -> fila -> worker -> vetorial)
python scripts/fumaca.py
```

Primeiro acesso pelo **gateway** (nunca pelos serviços diretamente):

```bash
# Login emite o JWT
curl -s -X POST http://localhost:8000/login \
  -H "Content-Type: application/json" \
  -d '{"usuario":"aluno","senha":"aluno123"}'
# -> {"token":"eyJ...","tipo":"Bearer","expira_em":"..."}

TOKEN="cole-o-token-aqui"

# Classificação síncrona
curl -s -X POST http://localhost:8000/predict \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"texto":"o atendimento foi excelente"}'
# -> {"rotulo":"positivo","confianca":0.98,"tempo_ms":12.4,"modelo":"1.0.0","explicacao":"..."}

# Fluxo assíncrono (fila + worker)
curl -s -X POST http://localhost:8000/tarefas \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"texto":"o produto chegou quebrado"}'
# -> {"status":"enfileirado","id":"<uuid>","consultar":"/tarefas/<uuid>"}
curl -s http://localhost:8000/tarefas/<uuid> -H "Authorization: Bearer $TOKEN"

# Busca semântica na memória vetorial
curl -s "http://localhost:8000/memoria/busca?q=atendimento%20excelente&k=3" \
  -H "Authorization: Bearer $TOKEN"
```

Sem token: `401`. Excedendo 30 req/min: `429` com `Retry-After`.

## 3. Resiliência e tratamento de falhas (item 6)

Implementado em `comum/resiliencia.py` (reutilizado por todos os serviços):

| Mecanismo            | Onde                | Comportamento                                              |
|----------------------|---------------------|------------------------------------------------------------|
| **Tempo-limite**     | toda chamada HTTP   | 5–10 s por chamada; nenhuma chamada fica sem limite         |
| **Retentativa**      | gateway e worker    | 3 tentativas com espera exponencial (0,3→0,6→1,2 s) + jitter|
| **Circuit breaker**  | dependências remotas| 3 falhas seguidas → **aberto** 10 s (recusa imediata) → meio-aberto (1 teste) → fechado |
| **Fallback para fila**| gateway `/predict` | inferência fora do ar? enfileira e devolve `202`            |
| **Reentrega limitada**| worker             | tarefa que falha volta à fila até 3 vezes, senão é descartada com log |
| **Healthchecks**     | compose             | `depends_on` com condição de saúde dos contêineres          |

Como demonstrar (roteiro de teste):

```bash
docker compose stop inferencia
# 1ª–3ª chamadas de /predict: retentativas (latência sobe)
# a partir da 3ª falha: circuito ABRE → respostas 202 INSTANTÂNEAS (fila)
docker compose start inferencia
# ~10 s depois o circuito MEIO-ABRE, testa, volta a FECHAR
```

## 4. Observabilidade (item 7)

- **Rastreamento distribuído (Jaeger — <http://localhost:16686>):** o gateway
  injeta o contexto W3C `traceparent` na mensagem da fila e o worker o extrai:
  **um único trace** cobre gateway → fila (Redis) → worker → inferência/Qdrant.
- **Métricas (Prometheus — <http://localhost:9090>):** latência por rota,
  taxa de requisições, erros 5xx de cada serviço, tamanho da fila, tarefas
  processadas e escala recomendada.
- **Painel (Grafana — <http://localhost:3000>**, admin/admin): dashboards
  provisionados automaticamente em `observabilidade/grafana/`.

## 5. Segurança e conformidade (LGPD) — item 6

### Medidas técnicas

- **Autenticação JWT** no gateway: `/login` emite token HS256 com expiração
  (`JWT_EXPIRA_MINUTOS`); todas as rotas de negócio exigem `Authorization:
  Bearer` (401 caso contrário). Comparação de senha em tempo constante
  (`hmac.compare_digest`); rate limit também no login (força bruta).
- **Rate limit** por cliente por minuto (janela no Redis — válido mesmo com
  várias réplicas do gateway).
- **HTTPS** no serviço publicado: fornecido pela plataforma de deploy
  (`https://...onrender.com`); componente opcional na borda (`edge/`).
- **Logs sem dados pessoais:** os logs registram apenas método, rota, status
  e duração — **nunca o conteúdo dos textos**.
- **Minimização:** entradas limitadas a 2000 caracteres; identificadores
  pseudônimos (UUID) em lugar de dados pessoais.
- **Toda configuração em variáveis de ambiente** (`​.env.example`) — nada
  fixo no código; segredos não versionados (`.env` fora do git).

### Declaração LGPD (dados tratados)

| Pergunta                             | Resposta |
|--------------------------------------|----------|
| **Quais dados são tratados?**        | (1) Textos enviados voluntariamente em `/predict`, `/tarefas` e `/memoria/busca`; (2) nome de usuário informado no `/login`; (3) identificadores técnicos (id de tarefa em UUID, timestamps). Nenhum dado pessoal sensível é solicitado. |
| **Com qual finalidade?**             | Prover o serviço de classificação de sentimento e a memória semântica da plataforma; fins estritamente educacionais (avaliação acadêmica). |
| **Base legal**                       | Execução de serviço solicitado pelo titular (envio voluntário) — LGPD art. 7º, V; ambiente de teste educacional. |
| **Por quanto tempo (retenção)?**     | Resultados de tarefas: 1 hora (TTL do Redis) ou até o reinício do contêiner; fila: apagada após o processamento; memória vetorial: efêmera no free tier (reinício/redeploy apaga) e limitada ao conteúdo processado no local; logs de acesso: apenas enquanto o contêiner vive. |
| **Compartilhamento?**                | Nenhum dado é vendido ou compartilhado. Sem LLM_API_KEY configurada, **nada é enviado a serviços externos** (modo simulado offline). Com chave configurada, o texto enviável a uma API externa é o mínimo necessário para gerar a explicação. |
| **Uso para treinamento de modelos?** | Não. Nenhum modelo é treinado com dados dos usuários. |
| **Direitos do titular**              | Acesso, correção e eliminação sob demanda (art. 18): basta contatar a equipe abaixo; a eliminação imediata consiste em `docker compose down -v` (ambientes de teste). |
| **Encarregado (DPO) de contato**     | [PREENCHER: e-mail do grupo] |

## 6. Deploy público (item 5) — free tier

Instruções completas em **`deploy/INSTRUCOES.md`** (Render Blueprint com o
`render.yaml` deste repositório, ou Railway/Fly como alternativa).

**URL pública:** [PREENCHER — ex.: https://plataforma-gateway.onrender.com]

Nota de free tier: instâncias gratuitas adormecem após ~15 min de inatividade
(cold start ~50 s no próximo acesso) e o disco é efêmero — implicações
discutidas em `docs/TRADE-OFFS.md`.

## 7. Relatório de trade-offs (CAP · custo · latência)

Documento completo: **`docs/TRADE-OFFS.md`**. Resumo:

- **CAP** — escolha AP no fluxo assíncrono (aceita trabalho mesmo com falhas;
  consistência eventual via fila); gosto de CP no caminho síncrono
  (timeout/retry/CB, falha rápido em vez de travar).
- **Custo** — R$ 0 (modelo treinado no build; free tier); circuit breaker e
  rate limit reduzem desperdício de máquinas; autoescalonamento paga só o
  trabalho necessário.
- **Latência** — síncrono p95 baixo para interação humana; assíncrono assume
  fila em picos para NUNCA perder requisição; retentativa exponencial com
  jitter evita stampede.

## 8. Extensões opcionais (todas implementadas)

| Extensão                    | Onde                                                        |
|-----------------------------|-------------------------------------------------------------|
| Autoescalonamento pela fila | `autoescalador/` (compose) + `k8s/keda-scaledobject.yaml`    |
| Serverless na borda         | `edge/worker.js` (Cloudflare Workers — deploy gratuito)     |
| CI/CD a cada commit         | `.github/workflows/ci.yml` (testes + fumaça + publicação GHCR)|
| Painel de métricas          | `observabilidade/grafana/` (provisionado no compose)         |
| Manifests de Kubernetes     | `k8s/` (com README de aplicação)                             |

## 9. Estrutura do repositório

```
├── comum/               # biblioteca compartilhada: resiliência, fila, telemetria
├── gateway/             # API Gateway (JWT, rate limit, rotas)
├── inferencia/          # serviço de IA (modelo treina no build — offline)
├── worker/              # worker de fila (resultado + memória vetorial)
├── autoescalador/       # extensão: escala conforme a fila
├── edge/                # extensão: serverless na borda (Cloudflare)
├── k8s/                 # extensão: manifests + KEDA
├── observabilidade/     # Prometheus + Grafana provisionados
├── deploy/              # passo a passo do deploy (free tier)
├── docs/                # trade-offs (CAP/custo/latência) e status das tarefas
├── scripts/             # teste de fumaça do fluxo completo
├── tests/               # testes unitários (pytest)
├── docker-compose.yml   # UM comando sobe tudo
├── render.yaml          # Blueprint de deploy (Render)
└── .github/workflows/   # CI/CD
```

## 10. Referência das variáveis de ambiente

| Variável                  | Serviço            | Padrão                        | Uso |
|---------------------------|--------------------|-------------------------------|-----|
| `JWT_SEGREDO`             | gateway            | `troque-este-segredo`         | assinatura do JWT   |
| `JWT_EXPIRA_MINUTOS`      | gateway            | 120                           | validade do token   |
| `USUARIOS`                | gateway            | `aluno:aluno123`              | usuários demo       |
| `LIMITE_POR_MINUTO`       | gateway            | 30                            | rate limit          |
| `URL_INFERENCIA`          | gateway/worker     | `http://inferencia:8001`      | descoberta de serviço |
| `REDIS_URL`               | gateway/worker/autoesc. | `redis://redis:6379/0`   | fila/estado         |
| `QDRANT_URL`              | gateway/worker     | `http://qdrant:6333`          | memória vetorial    |
| `TAREFA_TTL_SEGUNDOS`     | gateway/worker     | 3600                          | retenção (LGPD)     |
| `VETOR_DIM`               | inferencia/worker  | 32                            | dimensão do vetor   |
| `MAX_REENTREGAS`          | worker             | 3                             | reentrega da tarefa |
| `LLM_API_KEY`             | inferencia         | *(vazio)*                     | sem chave = simulado |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | todos          | `http://jaeger:4318`          | rastreamento        |

## 11. Testes

```bash
pytest -q                    # testes unitários (resiliência + JWT)
python scripts/fumaca.py     # teste de fumaça do sistema inteiro (com o stack no ar)
```

O CI executa ambos a cada commit (`.github/workflows/ci.yml`).

---

### Checklist final do edital

Consulte **`docs/STATUS.md`** — mapeia cada tarefa do kit ao arquivo que a
implementa, incluindo o roteiro "antes de entregar" (clone do zero em outra
máquina, URL no ar, configuração 100% externa, logs sem dados pessoais).

Licença: MIT (herdada do kit de partida).
