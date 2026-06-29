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

export async function testQontoConnection(): Promise<{ ok: boolean; status: number }> {
  const response = await qontoRequest("/v2/organization", { method: "GET" });
  return { ok: response.ok, status: response.status };
}

export async function searchQontoClient(_criteria: Record<string, unknown>): Promise<never> {
  throw new Error("Qonto client search is not implemented in this phase.");
}

export async function createQontoClient(_payload: Record<string, unknown>): Promise<never> {
  throw new Error("Qonto client creation is not implemented in this phase.");
}

export async function createQontoInvoice(_payload: Record<string, unknown>): Promise<never> {
  throw new Error("Qonto invoice creation is not implemented in this phase.");
}

export async function finalizeQontoInvoice(_invoiceId: string): Promise<never> {
  throw new Error("Qonto invoice finalization is not implemented in this phase.");
}

export async function sendQontoInvoice(_invoiceId: string): Promise<never> {
  throw new Error("Qonto invoice sending is not implemented in this phase.");
}

export async function markQontoInvoiceAsPaid(_invoiceId: string): Promise<never> {
  throw new Error("Qonto paid status synchronization is not implemented yet.");
}
