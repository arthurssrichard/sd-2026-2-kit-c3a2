# Componente serverless na borda (Cloudflare Workers) — extensão opcional

Funciona como uma primeira barreira na frente do gateway: responde saúde na
borda, recusa requisições sem token (economizando o free tier do backend) e
repassa o restante.

Deploy gratuito:

```bash
cd edge
npm install -g wrangler     # uma única vez
wrangler login
# edite GATEWAY_URL em wrangler.toml para a URL pública do seu gateway
wrangler deploy
```

A URL da borda (ex.: `https://plataforma-ia-borda.SUA-CONTA.workers.dev`) vira
mais um endpoint público HTTPS do sistema — e é a peça "executada na borda"
do edital.
