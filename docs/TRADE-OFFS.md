# Trade-offs: CAP, custo e latência

## CAP e falhas

Redis e Qdrant são instâncias únicas no Compose, em uma só VM. A implementação não replica estado e não oferece disponibilidade sob partições entre todos os serviços. Se a inferência ficar isolada, o gateway ainda aceita tarefas enquanto o Redis responder. Se o gateway perder acesso ao Redis, operações que dependem de autenticação, limites ou estado retornam indisponibilidade em vez de registrar trabalho que não conseguiram confirmar.

A classificação assíncrona é publicada antes de o resultado existir. O resultado passa a concluído depois do upsert no Qdrant, mas as duas gravações não formam uma transação distribuída. Um vetor pode estar visível por breve período antes do estado final no Redis. O upsert usa ID determinístico, o que evita criar pontos duplicados numa retentativa.

A fila usa `BRPOP`: o worker reentrega erros que consegue tratar, mas uma queda entre retirar a tarefa e gravar o resultado pode deixar o estado pendente até expirar. Redis é volátil por escolha de retenção; reiniciar Redis perde fila e resultados. Qdrant usa volume e expiração lógica com remoção periódica. Uma evolução seria usar fila com reconhecimento e recuperação de mensagens e uma política explícita de persistência e recuperação.

## Custo

O processamento local evita custo por chamada de IA. Uma VM elegível no free tier pode hospedar toda a stack com custo de infraestrutura de R$ 0 dentro das cotas, sem garantia de capacidade. CPU, RAM, disco, disponibilidade do provedor e eventual domínio são os custos e limites a verificar. Colocar tudo na mesma VM reduz custo e rede, mas concentra falhas.

## Latência

O caminho síncrono tem uma chamada de inferência; o assíncrono responde ao cliente após gravar no Redis e desloca classificação e vetorização para o worker. O tempo até o resultado inclui espera de fila, duas chamadas de inferência e indexação. Timeout de 2 s por tentativa e backoff de até 0,9 s somado em três tentativas limitam a espera típica de falha antes do fallback; timeout de rede por operação não equivale a um limite absoluto para a requisição completa. O circuito aberto evita novas chamadas de inferência até a sondagem. Esses valores são configurações do projeto, não medições de latência.
