# Worker

Consome IDs da fila no Redis, recupera a tarefa temporária, continua seu trace, classifica e vetoriza o texto e grava o vetor no Qdrant. Ao finalizar, atualiza o estado no Redis e remove o texto. Retenta falhas tratáveis com backoff; a limitação em caso de interrupção do processo está descrita no [relatório](../docs/TRADE-OFFS.md).
