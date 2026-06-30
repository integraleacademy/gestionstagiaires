const QONTO_API_BASE_URL = process.env.QONTO_API_BASE_URL || "https://thirdparty.qonto.com";

export function getQontoHeaders(): Record<string, string> {
  const login = (process.env.QONTO_LOGIN || "").trim();
  const secretKey = (process.env.QONTO_SECRET_KEY || "").trim();
  return { Authorization: `${login}:${secretKey}`, "Content-Type": "application/json" };
}

export function isQontoConfigured(): boolean {
  return Boolean((process.env.QONTO_LOGIN || "").trim() && (process.env.QONTO_SECRET_KEY || "").trim());
}

const INVALID_QONTO_CLIENT_SEARCH_MESSAGE = "Recherche client Qonto invalide : utiliser uniquement filter[name], filter[email], filter[tax_identification_number] ou filter[vat_number].";
const INVALID_QONTO_SEARCH_MARKERS = ["queryfields", "query_fields", "QueryFields", "first_name last_name name email"];

export function cleanQontoPayload<T = unknown>(obj: T): T {
  if (Array.isArray(obj)) return obj.map((v) => cleanQontoPayload(v)).filter((v) => v !== undefined && v !== null && v !== "" && !(typeof v === "object" && !Array.isArray(v) && Object.keys(v as object).length === 0)) as T;
  if (obj && typeof obj === "object") {
    const out: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(obj as Record<string, unknown>)) {
      const cleaned = cleanQontoPayload(value);
      if (cleaned === undefined || cleaned === null || cleaned === "") continue;
      if (cleaned && typeof cleaned === "object" && !Array.isArray(cleaned) && Object.keys(cleaned as object).length === 0) continue;
      out[key] = cleaned;
    }
    return out as T;
  }
  return obj;
}

function containsInvalidQontoSearchMarker(value: unknown): boolean {
  const serialized = typeof value === "string" ? value : JSON.stringify(value || {});
  const lowered = serialized.toLowerCase();
  return INVALID_QONTO_SEARCH_MARKERS.some((marker) => lowered.includes(marker.toLowerCase()));
}

function extractQontoMessage(body: string): string {
  try {
    const data = JSON.parse(body);
    if (typeof data?.message === "string") return data.message;
    if (typeof data?.error === "string") return data.error;
    if (Array.isArray(data?.errors)) return data.errors.map((e: any) => e?.message || e?.detail || e?.code || String(e)).join("; ");
  } catch (_) {}
  return body;
}

async function qontoRequest(path: string, init: RequestInit = {}): Promise<Response> {
  const baseUrl = QONTO_API_BASE_URL.replace(/\/+$/, "");
  const endpoint = path.startsWith("/") ? path : `/${path}`;
  const cleanedBody = init.body && typeof init.body === "string" ? JSON.stringify(cleanQontoPayload(JSON.parse(init.body))) : init.body;
  if (containsInvalidQontoSearchMarker(endpoint) || containsInvalidQontoSearchMarker(cleanedBody)) {
    console.error("[QONTO] invalid client search blocked", { endpoint });
    throw new Error(INVALID_QONTO_CLIENT_SEARCH_MESSAGE);
  }
  const response = await fetch(`${baseUrl}${endpoint}`, { ...init, body: cleanedBody, headers: { ...getQontoHeaders(), ...(init.headers || {}) } });
  const cloned = response.clone();
  const body = await cloned.text().catch(() => "");
  console.info("[QONTO] api_call", { method: init.method || "GET", url: `${baseUrl}${endpoint}`, payload: cleanedBody || null, status: response.status, trace_id: response.headers.get("x-qonto-trace-id") || response.headers.get("x-request-id") || "", body });
  return response;
}

async function qontoJson<T = Record<string, unknown>>(path: string, init: RequestInit = {}): Promise<T> {
  if (!isQontoConfigured()) throw new Error("Qonto n’est pas connecté");
  const response = await qontoRequest(path, init);
  const text = await response.text();
  const data = text ? JSON.parse(text) : {};
  if (!response.ok) throw new Error(`Qonto HTTP ${response.status}: ${extractQontoMessage(text)}`);
  return data as T;
}

export async function testQontoConnection(): Promise<{ ok: boolean; status: number }> {
  const response = await qontoRequest("/v2/organization", { method: "GET" });
  return { ok: response.ok, status: response.status };
}

export async function findQontoClientByName(name: string): Promise<Record<string, unknown> | null> {
  const normalizedName = String(name || "").trim();
  const qs = normalizedName ? `?${new URLSearchParams({ "filter[name]": normalizedName }).toString()}` : "";
  const data = await qontoJson<Record<string, unknown>>(`/v2/clients${qs}`, { method: "GET" });
  const clients = (data.clients || data.items || []) as Record<string, unknown>[];
  return Array.isArray(clients) && clients.length ? clients[0] : null;
}

export async function findQontoClientByTaxIdentificationNumber(taxId: string): Promise<Record<string, unknown> | null> {
  const normalized = String(taxId || "").trim();
  if (!normalized) return null;
  const qs = `?${new URLSearchParams({ "filter[tax_identification_number]": normalized }).toString()}`;
  const data = await qontoJson<Record<string, unknown>>(`/v2/clients${qs}`, { method: "GET" });
  const clients = (data.clients || data.items || []) as Record<string, unknown>[];
  return Array.isArray(clients) && clients.length ? clients[0] : null;
}

export async function searchQontoClient(criteria: Record<string, unknown>): Promise<Record<string, unknown> | null> {
  const email = String(criteria.email || "").trim();
  const name = String(criteria.name || criteria.client_name || "").trim();
  const params = email ? { "filter[email]": email } : name ? { "filter[name]": name } : undefined;
  const qs = params ? `?${new URLSearchParams(params).toString()}` : "";
  const data = await qontoJson<Record<string, unknown>>(`/v2/clients${qs}`, { method: "GET" });
  const clients = (data.clients || data.items || []) as Record<string, unknown>[];
  return Array.isArray(clients) && clients.length ? clients[0] : null;
}

export async function createQontoClient(payload: Record<string, unknown>): Promise<Record<string, unknown>> {
  return qontoJson("/v2/clients", { method: "POST", body: JSON.stringify(cleanQontoPayload(payload)) });
}

export const CPF_QONTO_CLIENT = {
  kind: "company",
  type: "company",
  name: "Mon Compte Formation géré par la Caisse des Dépôts et Consignations",
  tax_identification_number: "18002002600019",
  billing_address: {
    street_address: "56 rue de Lille - Mon Compte Formation",
    city: "PARIS 07 SP",
    zip_code: "75356",
    country_code: "FR",
  },
  currency: "EUR",
  locale: "fr",
};

export function getCpfQontoClientDefaults(): Record<string, unknown> {
  return { ...CPF_QONTO_CLIENT };
}


export async function getOrCreateCpfQontoClient(): Promise<Record<string, unknown>> {
  const taxClient = await findQontoClientByTaxIdentificationNumber(CPF_QONTO_CLIENT.tax_identification_number);
  if (taxClient) return taxClient;
  const nameClient = await findQontoClientByName("Mon Compte Formation");
  if (nameClient) return nameClient;
  return createQontoClient({ client: CPF_QONTO_CLIENT });
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

export async function createClientIfNeeded(payload: Record<string, unknown>): Promise<Record<string, unknown>> {
  const existing = await searchQontoClient(payload);
  return existing || createQontoClient(payload);
}

export async function createInvoiceDraft(payload: Record<string, unknown>): Promise<Record<string, unknown>> {
  return createQontoInvoice({ ...payload, status: (payload.status as string) || "draft" });
}

export async function finalizeInvoiceIfNeeded(invoiceId: string, shouldFinalize = true): Promise<Record<string, unknown>> {
  return shouldFinalize ? finalizeQontoInvoice(invoiceId) : getQontoInvoice(invoiceId);
}

export async function getInvoiceStatus(invoiceId: string): Promise<Record<string, unknown>> {
  return getQontoInvoice(invoiceId);
}

export async function downloadInvoicePdf(invoiceId: string): Promise<Record<string, unknown>> {
  return qontoJson(`/v2/client_invoices/${encodeURIComponent(invoiceId)}/download`, { method: "GET" });
}

export async function syncPaymentStatus(invoiceId: string): Promise<Record<string, unknown>> {
  return getQontoInvoice(invoiceId);
}

export async function createCreditNote(invoiceId: string, payload: Record<string, unknown> = {}): Promise<Record<string, unknown>> {
  return qontoJson(`/v2/client_invoices/${encodeURIComponent(invoiceId)}/credit_notes`, { method: "POST", body: JSON.stringify(payload) });
}
