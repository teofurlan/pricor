import type {
  CreateImportInput,
  ExportFormat,
  PreviewPage,
  SessionState,
  ColumnRole,
} from "./types";

/** A failed API call, normalized from the server's `{"error": {code, message}}` envelope. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

export interface ApiClient {
  createImport(input: CreateImportInput): Promise<SessionState>;
  getImport(id: string): Promise<SessionState>;
  chooseHeader(id: string, rowIndex: number | null): Promise<SessionState>;
  setRoles(id: string, roles: Record<number, ColumnRole>): Promise<SessionState>;
  answer(id: string, questionId: string, option: string): Promise<SessionState>;
  preview(id: string, offset: number, limit: number): Promise<PreviewPage>;
  approve(id: string): Promise<SessionState>;
  exportUrl(id: string, format: ExportFormat): string;
  rejectedUrl(id: string, format: ExportFormat): string;
}

type Fetch = typeof fetch;

async function fail(response: Response): Promise<never> {
  let envelope: { error?: { code?: string; message?: string } } | null = null;
  try {
    envelope = await response.json();
  } catch {
    envelope = null;
  }
  const error = envelope?.error;
  if (error?.code && error.message) {
    throw new ApiError(response.status, error.code, error.message);
  }
  throw new ApiError(response.status, "unexpected_response", `The server answered ${response.status}.`);
}

export function createApiClient(fetchImpl: Fetch = (...args) => fetch(...args), baseUrl = ""): ApiClient {
  async function call<T>(path: string, init?: RequestInit): Promise<T> {
    let response: Response;
    try {
      response = await fetchImpl(`${baseUrl}${path}`, init);
    } catch {
      throw new ApiError(0, "network_error", "The Pricor server cannot be reached.");
    }
    if (!response.ok) await fail(response);
    return (await response.json()) as T;
  }

  const json = (method: string, body: unknown): RequestInit => ({
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const base = (id: string) => `/imports/${encodeURIComponent(id)}`;

  return {
    createImport({ file, supplierName, sheet, language }) {
      const form = new FormData();
      form.set("file", file);
      form.set("supplier_name", supplierName);
      if (sheet?.trim()) form.set("sheet", sheet.trim());
      form.set("language", language);
      return call("/imports", { method: "POST", body: form });
    },
    getImport: (id) => call(base(id)),
    chooseHeader: (id, rowIndex) => call(`${base(id)}/header`, json("PUT", { row_index: rowIndex })),
    setRoles: (id, roles) => call(`${base(id)}/roles`, json("PUT", { roles })),
    answer: (id, questionId, option) =>
      call(`${base(id)}/answers`, json("POST", { question_id: questionId, option })),
    preview: (id, offset, limit) => call(`${base(id)}/preview?offset=${offset}&limit=${limit}`),
    approve: (id) => call(`${base(id)}/approve`, { method: "POST" }),
    exportUrl: (id, format) => `${baseUrl}${base(id)}/export?format=${format}`,
    rejectedUrl: (id, format) => `${baseUrl}${base(id)}/rejected?format=${format}`,
  };
}
