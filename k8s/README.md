# Manifests de Kubernetes (extensão — item 9/8 do edital)

Manifests equivalentes ao docker-compose, inclusive o autoescalonamento de
workers pela fila (KEDA). Podem ser aplicados em qualquer cluster; o edital
aceita os manifests "mesmo sem executá-los em cluster real".

## Como aplicar

```bash
# 1. As imagens devem estar publicadas (CI publica no push na main se PUBLICAR_GHCR=true)
#    Edite SEU_USUARIO nos manifests: k8s/inferencia.yaml, worker.yaml, gateway.yaml

# 2. Namespace + segredos
kubectl create namespace plataforma
kubectl -n plataforma create secret generic plataforma-segredos \
  --from-literal=jwt-segredo='UM-SEGREDO-SEGURO' \
  --from-literal=usuarios='aluno:senhaForte1,maria:senhaForte2'

# 3. Infra e serviços
kubectl apply -f k8s/redis.yaml
kubectl apply -f k8s/qdrant.yaml
kubectl apply -f k8s/inferencia.yaml
kubectl apply -f k8s/worker.yaml
kubectl apply -f k8s/gateway.yaml
kubectl -n plataforma port-forward svc/gateway 8000:80

# 4. Autoescalonamento pela fila (opcional — instale o KEDA antes)
kubectl apply -f k8s/keda-scaledobject.yaml
```

## O que cada arquivo faz

| Arquivo                    | Papel                                        |
|----------------------------|----------------------------------------------|
| `redis.yaml`               | fila + rate limit + resultados               |
| `qdrant.yaml`              | armazenamento vetorial                       |
| `inferencia.yaml`          | serviço de inferência (2 réplicas)           |
| `worker.yaml`              | worker de fila (1 réplica, escala via KEDA)  |
| `gateway.yaml`             | gateway interno, acessível via port-forward  |
| `secret.example.yaml`      | modelo de segredos (JWT e usuários)          |
| `keda-scaledobject.yaml`   | autoescalador baseado na fila                |
