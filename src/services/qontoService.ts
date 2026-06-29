const QONTO_API_BASE_URL = process.env.QONTO_API_BASE_URL || "https://thirdparty.qonto.com";

export function getQontoHeaders(): Record<string, string> {
  const login = (process.env.QONTO_LOGIN || "").trim();
  const secretKey = (process.env.QONTO_SECRET_KEY || "").trim();

  return {
    Authorization: `${login}:${secretKey}`,
    "Content-Type": "application/json",
  };
}

export function isQontoConfigured(): boolean {
  return Boolean((process.env.QONTO_LOGIN || "").trim() && (process.env.QONTO_SECRET_KEY || "").trim());
}

async function qontoRequest(path: string, init: RequestInit = {}): Promise<Response> {
  const baseUrl = QONTO_API_BASE_URL.replace(/\/+$/, "");
  const endpoint = path.startsWith("/") ? path : `/${path}`;
  return fetch(`${baseUrl}${endpoint}`, {
    ...init,
    headers: {
      ...getQontoHeaders(),
      ...(init.headers || {}),
    },
  });
}

async function qontoJson<T = Record<string, unknown>>(path: string, init: RequestInit = {}): Promise<T> {
  if (!isQontoConfigured()) throw new Error("Qonto n’est pas connecté");
  const response = await qontoRequest(path, init);
  const text = await response.text();
  const data = text ? JSON.parse(text) : {};
  if (!response.ok) throw new Error(`Qonto HTTP ${response.status}`);
  return data as T;
}

export async function testQontoConnection(): Promise<{ ok: boolean; status: number }> {
  const response = await qontoRequest("/v2/organization", { method: "GET" });
  return { ok: response.ok, status: response.status };
}

export async function searchQontoClient(criteria: Record<string, unknown>): Promise<Record<string, unknown> | null> {
  const email = String(criteria.email || "").trim();
  const query = email || String(criteria.name || criteria.client_name || "").trim();
  const qs = query ? `?${new URLSearchParams(email ? { email } : { query }).toString()}` : "";
  const data = await qontoJson<Record<string, unknown>>(`/v2/clients${qs}`, { method: "GET" });
  const clients = (data.clients || data.items || []) as Record<string, unknown>[];
  return Array.isArray(clients) && clients.length ? clients[0] : null;
}

export async function createQontoClient(payload: Record<string, unknown>): Promise<Record<string, unknown>> {
  return qontoJson("/v2/clients", { method: "POST", body: JSON.stringify(payload) });
}

export async function createQontoInvoice(payload: Record<string, unknown>): Promise<Record<string, unknown>> {
  return qontoJson("/v2/client_invoices", { method: "POST", body: JSON.stringify(payload) });
}

export async function finalizeQontoInvoice(invoiceId: string): Promise<Record<string, unknown>> {
  return qontoJson(`/v2/client_invoices/${encodeURIComponent(invoiceId)}/finalize`, { method: "POST" });
}

export async function sendQontoInvoice(invoiceId: string, emailPayload: Record<string, unknown>): Promise<Record<string, unknown>> {
  return qontoJson(`/v2/client_invoices/${encodeURIComponent(invoiceId)}/send`, { method: "POST", body: JSON.stringify(emailPayload) });
}

export async function getQontoInvoice(invoiceId: string): Promise<Record<string, unknown>> {
  return qontoJson(`/v2/client_invoices/${encodeURIComponent(invoiceId)}`, { method: "GET" });
}

export async function markQontoInvoiceAsPaid(_invoiceId: string): Promise<never> {
  throw new Error("Qonto paid status synchronization is not implemented yet.");
}
