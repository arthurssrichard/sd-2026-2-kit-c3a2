# Deploy em nuvem (free tier) — item 5 do edital

Objetivo: **URL pública com HTTPS** funcionando a partir do repositório do grupo.
Siga a Opção A (Render); a Opção B (Railway/Fly) fica como alternativa.

## Opção A — Render com Blueprint (recomendada, usa o `render.yaml` do repositório)

1. **Fork** deste repositório no GitHub (botão Fork no canto superior direito).
2. Crie conta em <https://render.com> e conecte o GitHub.
3. Dashboard: **New + → Blueprint** → selecione o SEU fork.
   O Render lê o `render.yaml` e propõe os serviços: gateway, inferência,
   worker, vetorial (Qdrant) e jaeger.
4. Clique **Apply** e aguarde o build (a inferência demora mais: treina no build).
5. Redis gerenciado:
   - **Upstash (grátis, recomendado):** crie um banco em <https://upstash.com>,
     copie a URL TLS (`rediss://...`) e cole em `REDIS_URL` do **gateway** e do
     **worker** (Environment → Edit).
   - Alternativa: **Render Key Value** (New + → Key Value) e use a URL interna
     ou externa no `REDIS_URL`.
6. Anote as URLs públicas criadas (ex.: `https://plataforma-gateway.onrender.com`)
   e **corrija** em cada serviço as variáveis `URL_INFERENCIA`, `QDRANT_URL` e
   `OTEL_EXPORTER_OTLP_ENDPOINT` para as URLs reais.
7. Reinicie os serviços para aplicar (Environment → qualquer edit pede redeploy).
8. Teste: `https://SEU-GATEWAY.onrender.com/saude` no navegador → `{"status":"ok"}`.

**HTTPS:** automático — o Render emite e renova o certificado TLS do domínio
`*.onrender.com` (atende o item 8 do edital sem configuração extra).

**Cold start (atenção):** instâncias gratuitas adormecem após ~15 min sem
tráfego; o próximo acesso demora ~50s. Para o worker NÃO dormir (fila precisa
processar), use um ping periódico gratuito (ex.: cron-job.org em
`https://plataforma-worker.onrender.com/saude` a cada 10 min).

## Opção B — Railway

1. <https://railway.app> → New Project → Deploy from GitHub repo.
2. Crie um serviço para cada Dockerfile (raiz do repositório como contexto).
3. Configure as mesmas variáveis de ambiente.
4. Settings → Networking → Generate Domain (URL pública com HTTPS).

## Opção C — Fly.io

1. `fly launch` em cada serviço (`fly.toml` gerado apontando ao Dockerfile).
2. URLs públicas `https://<app>.fly.dev` com HTTPS automático.

## Variáveis mínimas por serviço

| Serviço    | Variáveis                                                            |
|------------|----------------------------------------------------------------------|
| gateway    | `JWT_SEGREDO`, `USUARIOS`, `REDIS_URL`, `URL_INFERENCIA`, `QDRANT_URL`|
| inferência | (opcional) `LLM_API_KEY`                                             |
| worker     | `REDIS_URL`, `URL_INFERENCIA`, `QDRANT_URL`                          |

## Dica que vale nota

Publique CEDO, ainda que incompleto — deploy sempre dá mais trabalho do que
se imagina. Anote a URL no README principal (seção "Deploy público").
