# Checklist de entrega

| Exigência | Onde verificar |
|---|---|
| Microsserviços, fila e armazenamento vetorial | `gateway/`, `inferencia/`, `worker/` e Redis/Qdrant no Compose |
| Dockerfile por serviço próprio e comando único | `docker-compose.yml` e Dockerfiles |
| Autenticação e rate limit | `gateway/app.py` |
| Timeout, retentativa e circuit breaker | `comum/resiliencia.py` |
| Trace gateway → fila → worker | `comum/fila.py`, Jaeger e roteiro do README |
| LGPD e análise de CAP, custo e latência | `README.md` e `docs/TRADE-OFFS.md` |
| HTTPS e publicação | `compose.publico.yml`, `deploy/Caddyfile` e instruções de publicação; requer VM e domínio ativos |

Antes de entregar:

- [ ] Fork final do grupo no GitHub e contribuições revisadas.
- [ ] Clone limpo validado em outra máquina com Compose e teste de fumaça.
- [ ] HTTPS público testado, inclusive classificação, fila e busca via URL pública.
- [ ] README com nomes, URL e contato; acesso de demonstração enviado em privado.
- [ ] Somente o link do repositório final enviado no AVA.
