# Relatório de trade-offs — item 10 do edital (CAP, custo e latência)

Plataforma: gateway + inferência + fila (Redis) + worker + armazenamento
vetorial (Qdrant), com caminhos síncrono e assíncrono.

## 1. CAP (consistência, disponibilidade e tolerância a partições)

Em sistema distribuído, a tolerância a partições (P) não é opcional — a rede
pode falhar. A escolha de verdadeira é **consistência vs. disponibilidade**:

**Escolha: AP (disponibilidade acima da consistência) no fluxo principal.**

- **Caminho assíncrono (`/tarefas`)** — AP: se a inferência estiver fora, a
  tarefa continua sendo aceita e enfileirada. O resultado é *eventualmente
  consistente*: `GET /tarefas/{id}` devolve 202 (pendente) até o worker
  concluir. Disponibilidade vem antes do frescor do dado.
- **Caminho síncrono (`/predict`)** — gosto de CP: tempo-limite de 10s,
  retentativas (0,3s/0,6s/1,2s + jitter) e circuit breaker. Após 3 falhas o
  circuito **abre** e recusa de imediato por 10s (meio-aberto depois) — troca
  consistência de resposta por resposta rápida e proteção contra cascata.
  Se o circuito abre, o pedido é desviado para a fila (202): o gateway
  **degrada** em vez de devolver erro.
- **Memória vetorial (Qdrant)** — consistência final: o ponto aparece nas
  buscas logo após o worker gravar; não há leitura que garanta
  *read-your-writes* através do gateway.
- **Fila (Redis)** — trade-off declarado: habilitamos AOF (`--appendonly yes`)
  para sobreviver a reinícios, ao custo de I/O extra por escrita. Sem isso,
  tarefas enfileiradas se perderiam em crash — consistência mais fraca, mas
  latência menor.

**Falha admitida (documentada):** no free tier da nuvem, o Redis gerenciado
(Upstash) e o Qdrant têm disco efêmero/reinícios; nesses ambientes o trade-off
AP é levado ao extremo (dado pode se perder em redeploy — custo zero).

## 2. Custo

| Cenário                     | Custo mensal | O que se abre mão                             |
|-----------------------------|--------------|-----------------------------------------------|
| Local (compose)             | R$ 0         | nada — tudo roda na máquina                   |
| Nuvem free tier (adotado)   | R$ 0         | *cold start* ~50s após 15min ocioso; disco     |
|                             |              | efêmero; limites de banda/comandos do Upstash  |
| Nuvem paga (referência)     | ~US$ 25–40   | nada: máquina sempre quente, disco persistente |

Decisões de custo embutidas no projeto:

- **Modelo treinado no build da imagem** (scikit-learn local) — zero custo de
  API de IA em runtime; LLM opcional só para explicação.
- **Circuit breaker economiza dinheiro**: sem ele, cada falha custaria
  `tentativas × timeout` de tempo de máquina ocupado à toa.
- **Rate limit (30/min/cliente)** protege o free tier de abuso — em free tier,
  abuso = custo (ou bloqueio).
- **Autoescalonamento pela fila** (autoescalador + KEDA) mantém o mínimo de
  réplicas ociosas: paga-se por trabalho, não por "sempre ligado".

## 3. Latência

| Caminho                          | Latência típica (local) | Nuvem free tier                    |
|----------------------------------|-------------------------|------------------------------------|
| `/predict` síncrono (feliz)      | ~10–40 ms               | + rede + cold start (~50s no 1º acesso) |
| `/predict` com retentativas      | +0,3s/0,6s/1,2s         | idem (apenas em falha)             |
| Circuito aberto                  | < 1 ms (recusa imediata)| idem                               |
| `/tarefas` + consulta            | +2–10 s (fila + worker) | cold start do worker pode somar    |
| `/memoria/busca`                 | ~20–50 ms               | + cold start do Qdrant             |

Análise:

- **Síncrono** existe para interação humana (aplicativo espera): baixo p95.
- **Assíncrono** existe para robustez e picos: aceita-se fila em troca de
  *nunca perder* requisição — a retentativa fica no worker, não no usuário.
- **Retentativa exponencial com jitter** evita sincronizar clientes e agravar
  sobrecarga (evita o "stampede").
- **Cold start** é a maior latência do free tier — mitigações: ping periódico
  (cron-job.org) e, no caso da borda, o Cloudflare Worker responde `/saude`
  e erros de autenticação sem acordar o backend.

## Resumo

| Dimensão | Escolha | Trade-off aceito |
|----------|---------|------------------|
| CAP      | AP (assíncrono) + CP no síncrono | dado eventualmente consistente |
| Custo    | free tier + modelo local | cold start, disco efêmero |
| Latência | síncrono rápido + assíncrono resiliente | fila em picos/falhas |
