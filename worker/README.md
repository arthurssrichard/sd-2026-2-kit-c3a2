# Worker de fila

Consome a fila do Redis e completa o fluxo assíncrono:

```
BRPOP fila:tarefas
  └─► chama inferência /predict + /vetor (com resiliência)
      └─► grava resultado no Redis (TTL) — o gateway o serve em /tarefas/{id}
          └─► grava vetor + metadados na memória vetorial (Qdrant)
```

- Continua o trace original do gateway (contexto W3C gravado na mensagem);
- reentrega limitada: tarefa falha volta para a fila até MAX_REENTREGAS vezes;
- expõe `/saude` e `/metrics` (healthcheck + painel de métricas + deploy em
  plataformas gratuitas que exigem porta HTTP).
