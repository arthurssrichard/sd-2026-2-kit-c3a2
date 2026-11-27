# Status das tarefas do kit (TAREFAS.md) — checklist de entrega

## Núcleo obrigatório

- [x] **1. Autenticação JWT no gateway** — `gateway/app.py`
      `/login` emite token (HS256, exp configurável); rotas protegidas exigem
      Bearer (401 ausente/inválido/expirado). Testes: `tests/test_seguranca.py`.
- [x] **2. Rate limit no gateway** — `gateway/app.py` (`limite_por_cliente`)
      Janela fixa por minuto no Redis (30/min por cliente; 429 + Retry-After).
- [x] **3. Dockerfile de cada serviço** — `gateway/`, `inferencia/`, `worker/`,
      `autoescalador/` (um por serviço; a inferência TREINA o modelo no build).
- [x] **4. docker-compose completo** — `docker-compose.yml` sobe TODO o
      sistema com UM comando: `docker compose up --build`
      (redis, qdrant, jaeger, prometheus, grafana, inferencia, worker,
      gateway, autoescalador).
- [x] **5. Deploy em nuvem (free tier)** — `render.yaml` (Blueprint) +
      `deploy/INSTRUCOES.md`. **URL pública: [PREENCHER NO README.md]**.
- [x] **6. Resiliência** — `comum/resiliencia.py`: tempo-limite, retentativa
      exponencial com jitter e circuit breaker (fechado/aberto/meio-aberto);
      fallback para a fila no gateway; reentrega limitada no worker.
- [x] **7. Observabilidade** — OpenTelemetry → Jaeger: um único trace cobre
      gateway → fila (Redis) → worker → inferência/Qdrant; métricas em
      Prometheus + painel Grafana (`observabilidade/`).
- [x] **8. HTTPS no serviço publicado** — automático no Render/Fly/Railway
      (`https://...onrender.com`); opção de borda em `edge/`.
- [x] **9. Seção LGPD no README** — README.md, seção "Segurança e LGPD".
- [x] **10. Relatório de trade-offs** — `docs/TRADE-OFFS.md` (CAP, custo, latência).

## Extensões opcionais

- [x] Autoescalonamento conforme a fila — `autoescalador/` (compose) +
      `k8s/keda-scaledobject.yaml` (KEDA no k8s).
- [x] Componente serverless na borda — `edge/worker.js` (Cloudflare Workers).
- [x] CI/CD publicando a cada commit — `.github/workflows/ci.yml`
      (testes + fumaça em contêiner + publicação GHCR na main).
- [x] Painel de métricas — Grafana provisionado (`observabilidade/grafana/`).
- [x] Manifests de Kubernetes — `k8s/`.

## Antes de entregar (roteiro do edital)

- [ ] Clone em OUTRA máquina e rode o comando único — funciona?
- [ ] A URL pública está no ar? (anotada no README)
- [ ] Toda configuração está em variável de ambiente? (sim — `.env.example`)
- [ ] Os logs estão livres de dados pessoais? (sim — apenas path/status/ms)
