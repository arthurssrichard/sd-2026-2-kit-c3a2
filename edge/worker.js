/**
 * Componente serverless na BORDA (Cloudflare Workers) — extensão do edital.
 *
 * Colocado NA FRENTE do gateway público:
 *   - responde /saude na própria borda (sem atravessar o backend);
 *   - recusa na borda requisições sem Authorization (401), economizando
 *     requisições contra o free tier do backend e reduzindo latência de erro;
 *   - repassa o resto para o gateway (o JWT continua sendo validado lá).
 *
 * Deploy (gratuito):  npx wrangler deploy   (com o GATEWAY_URL correto abaixo)
 */
export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    // Saúde responde na borda (componente executado na borda de verdade).
    if (url.pathname === "/saude") {
      return new Response(JSON.stringify({ status: "ok", servico: "borda" }), {
        headers: { "content-type": "application/json" },
      });
    }

    // Primeira barreira de autenticação: sem token, nem chega ao gateway.
    if (!request.headers.get("authorization")) {
      return new Response(
        JSON.stringify({ erro: "token ausente (verificação na borda)" }),
        { status: 401, headers: { "content-type": "application/json" } }
      );
    }

    // Repassa método, headers e corpo para o gateway.
    return fetch(env.GATEWAY_URL + url.pathname + url.search, request);
  },
};
