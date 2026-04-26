const RAG_SERVICE_URL =
  process.env.RAG_SERVICE_URL || "http://localhost:8001";

/**
 * Proxy handler for all /rag-api/* requests.
 * Reads RAG_SERVICE_URL at request time so Docker runtime env vars are used.
 */
async function proxyToRagService(request, { params }) {
  const path = (await params).path.join("/");
  const targetUrl = `${RAG_SERVICE_URL}/${path}`;

  const headers = { "Content-Type": "application/json" };

  const init = {
    method: request.method,
    headers,
  };

  if (request.method !== "GET" && request.method !== "HEAD") {
    init.body = await request.text();
  }

  const upstream = await fetch(targetUrl, init);
  const data = await upstream.text();

  return new Response(data, {
    status: upstream.status,
    headers: { "Content-Type": upstream.headers.get("Content-Type") || "application/json" },
  });
}

export const GET = proxyToRagService;
export const POST = proxyToRagService;
