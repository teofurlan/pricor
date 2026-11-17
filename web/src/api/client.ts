import { parseCsv } from "./csv";
import type {
  OutputColumnDefinition,
  OutputFormat,
  OutputSource,
  AskReply,
  AskTurn,
  CreateImportInput,
  ExportFormat,
  PreviewFilter,
  PreviewPage,
  PriceReport,
  SessionState,
  ColumnRole,
  Memory,
  ServerConfig,
  SampleListing,
  FunnelEvent,
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

/** Which approved file: the products or the rejected-rows report. */
export type ExportFile = "products" | "rejected";

export interface ExportSheet {
  header: string[];
  rows: string[][];
  total: number;
}

export interface ApiClient {
  listSheets(file: File): Promise<string[]>;
  createImport(input: CreateImportInput): Promise<SessionState>;
  getImport(id: string): Promise<SessionState>;
  chooseHeader(id: string, rowIndex: number | null): Promise<SessionState>;
  setRoles(id: string, roles: Record<number, ColumnRole>): Promise<SessionState>;
  answer(id: string, questionId: string, option: string): Promise<SessionState>;
  /** Asks Gemma about one question. The reply only explains or suggests; it never answers. */
  askQuestion(id: string, questionId: string, message: string, history: AskTurn[]): Promise<AskReply>;
  /** Use a rate the user typed for this run (`1420,50` and `1420.50` both work). */
  setManualRate(id: string, rate: string): Promise<SessionState>;
  /** Ask the live source for the plan's rate again. */
  refreshRate(id: string): Promise<SessionState>;
  preview(id: string, offset: number, limit: number, filter?: Partial<PreviewFilter>): Promise<PreviewPage>;
  approve(id: string): Promise<SessionState>;
  /** What changed since the supplier's previous approved import; `threshold` is a ratio ("0.30"). */
  report(id: string, threshold?: string): Promise<PriceReport>;
  getSample(id: string, limit?: number): Promise<{ header: string[]; rows: string[][] }>;
  /** An approved file as written (CSV): its header, the first `limit` rows and the row count. */
  exportSheet(id: string, file: ExportFile, limit?: number): Promise<ExportSheet>;
  exportUrl(id: string, format: ExportFormat): string;
  rejectedUrl(id: string, format: ExportFormat): string;
  reportUrl(id: string, threshold?: string): string;
  config(): Promise<ServerConfig>;
}

/** The synthetic sample lists a visitor can try (`/samples`). */
export interface SampleApiClient {
  listSamples(): Promise<SampleListing[]>;
  /** The sample's file, ready to load into the upload form like a dropped one. */
  downloadSample(sample: SampleListing): Promise<File>;
}

/** The visitor's private workspace: its personal link, which also sets the workspace cookie. */
export interface WorkspaceApiClient {
  workspace(): Promise<{ link: string }>;
  /** The workspace the cookie points at, or null when there is none; never creates one. */
  currentWorkspace(): Promise<{ link: string } | null>;
  /** Switch this browser to the workspace of a personal link's token (sets the cookie). */
  claimWorkspace(token: string): Promise<{ link: string }>;
}

export interface MemoryApiClient {
  listMemories(): Promise<Memory[]>;
  createMemoryNote(text: string, supplierName?: string): Promise<Memory>;
  rememberSuggestion(sessionId: string, questionId: string): Promise<Memory>;
  editMemory(id: string, text: string): Promise<Memory>;
  deleteMemory(id: string): Promise<void>;
}

/** The store-wide output format read from a template (`/output-format`). */
export interface OutputFormatApiClient {
  /** The stored format, or null when the standard columns apply. */
  getOutputFormat(): Promise<OutputFormat | null>;
  uploadOutputFormat(file: File): Promise<OutputFormat>;
  /** Every column's source in template order; the format is used only after this. */
  confirmOutputFormat(sources: OutputSource[]): Promise<OutputFormat>;
  /** Save exactly these columns, in this order, as the confirmed format. */
  defineOutputFormat(columns: OutputColumnDefinition[]): Promise<OutputFormat>;
  deleteOutputFormat(): Promise<void>;
}

/** One file made from several approved imports (`POST /imports/combined-export`). */
export interface CombinedExportApiClient {
  /** The unified products or rejected-rows file of these approved sessions, in this order. */
  downloadCombined(sessionIds: string[], format: ExportFormat, kind: ExportFile): Promise<{ blob: Blob; fileName: string }>;
}

/** The anonymous funnel record: which group of testers got how far (`POST /events`). */
export interface EventsApiClient {
  recordEvent(event: FunnelEvent, group: string | null): Promise<void>;
}

/** Asks the server to load its models now and keeps the request open meanwhile (`POST /warm-up`). */
export interface WarmUpApiClient {
  /** Fire-and-forget: resolves whatever happens, never rejects. */
  warmUp(): Promise<void>;
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

export function createApiClient(fetchImpl: Fetch = (...args) => fetch(...args), baseUrl = ""): ApiClient & MemoryApiClient & OutputFormatApiClient & SampleApiClient & WorkspaceApiClient & CombinedExportApiClient & EventsApiClient & WarmUpApiClient {
  async function call<T>(path: string, init?: RequestInit): Promise<T> {
    let response: Response;
    try {
      response = await fetchImpl(`${baseUrl}${path}`, init);
    } catch {
      throw new ApiError(0, "network_error", "The Pricor server cannot be reached.");
    }
    if (!response.ok) await fail(response);
    if (response.status === 204) return undefined as T;
    return (await response.json()) as T;
  }

  const json = (method: string, body: unknown): RequestInit => ({
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const base = (id: string) => `/imports/${encodeURIComponent(id)}`;

  return {
    listSheets: async (file) => {
      const form = new FormData();
      form.set("file", file);
      const data = await call<{ sheets: string[] }>("/sheets", { method: "POST", body: form });
      return data.sheets;
    },
    createImport({ file, supplierName, sheet, language, forceFirstImport }) {
      const form = new FormData();
      form.set("file", file);
      form.set("supplier_name", supplierName);
      if (sheet?.trim()) form.set("sheet", sheet.trim());
      form.set("language", language);
      if (forceFirstImport) form.set("force_first_import", "true");
      return call("/imports", { method: "POST", body: form });
    },
    getImport: (id) => call(base(id)),
    chooseHeader: (id, rowIndex) => call(`${base(id)}/header`, json("PUT", { row_index: rowIndex })),
    setRoles: (id, roles) => call(`${base(id)}/roles`, json("PUT", { roles })),
    answer: (id, questionId, option) =>
      call(`${base(id)}/answers`, json("POST", { question_id: questionId, option })),
    setManualRate: (id, rate) => call(`${base(id)}/fx`, json("PUT", { rate })),
    refreshRate: (id) => call(`${base(id)}/fx/refresh`, { method: "POST" }),
    preview: (id, offset, limit, filter) => {
      const params = new URLSearchParams({ offset: String(offset), limit: String(limit) });
      const query = filter?.query?.trim();
      if (query) params.set("q", query);
      if (filter?.status && filter.status !== "all") params.set("status", filter.status);
      return call(`${base(id)}/preview?${params.toString()}`);
    },
    approve: (id) => call(`${base(id)}/approve`, { method: "POST" }),
    report: (id, threshold) =>
      call(`${base(id)}/report${threshold === undefined ? "" : `?threshold=${encodeURIComponent(threshold)}`}`),
    getSample: (id, limit = 5) => call(`${base(id)}/sample?limit=${limit}`),
    async getOutputFormat() {
      try {
        return await call<OutputFormat>("/output-format");
      } catch (failure) {
        if (failure instanceof ApiError && failure.status === 404) return null;
        throw failure;
      }
    },
    uploadOutputFormat(file) {
      const form = new FormData();
      form.set("file", file);
      return call<OutputFormat>("/output-format", { method: "POST", body: form });
    },
    confirmOutputFormat: (sources) => call<OutputFormat>("/output-format/mapping", json("PUT", { sources })),
    defineOutputFormat: (columns) => call<OutputFormat>("/output-format", json("PUT", { columns })),
    deleteOutputFormat: () => call<void>("/output-format", { method: "DELETE" }),
    askQuestion: (id, questionId, message, history) =>
      call<AskReply>(`${base(id)}/questions/${encodeURIComponent(questionId)}/ask`, json("POST", { message, history })),
    async exportSheet(id, file, limit = 10) {
      let response: Response;
      try {
        response = await fetchImpl(`${baseUrl}${base(id)}/${file === "products" ? "export" : "rejected"}?format=csv`);
      } catch {
        throw new ApiError(0, "network_error", "The Pricor server cannot be reached.");
      }
      if (!response.ok) await fail(response);
      const [header = [], ...rows] = parseCsv(await response.text());
      return { header, rows: rows.slice(0, limit), total: rows.length };
    },
    exportUrl: (id, format) => `${baseUrl}${base(id)}/export?format=${format}`,
    rejectedUrl: (id, format) => `${baseUrl}${base(id)}/rejected?format=${format}`,
    reportUrl: (id, threshold) =>
      `${baseUrl}${base(id)}/report/export?format=csv${threshold === undefined ? "" : `&threshold=${encodeURIComponent(threshold)}`}`,
    listMemories: () => call("/memories"),
    createMemoryNote: (text, supplierName) =>
      call("/memories", json("POST", { text, ...(supplierName?.trim() ? { supplier_name: supplierName.trim() } : {}) })),
    rememberSuggestion: (sessionId, questionId) =>
      call("/memories", json("POST", { session_id: sessionId, question_id: questionId })),
    editMemory: (id, text) => call(`/memories/${encodeURIComponent(id)}`, json("PATCH", { text })),
    deleteMemory: (id) => call(`/memories/${encodeURIComponent(id)}`, { method: "DELETE" }),
    config: () => call<ServerConfig>("/config"),
    workspace: () => call<{ link: string }>("/workspace"),
    async currentWorkspace() {
      try {
        return await call<{ link: string }>("/workspace/current");
      } catch (failure) {
        if (failure instanceof ApiError && failure.status === 404 && failure.code === "workspace_not_found") return null;
        throw failure;
      }
    },
    claimWorkspace: (token) => call<{ link: string }>("/workspace/claim", json("POST", { token })),
    async downloadCombined(sessionIds, format, kind) {
      let response: Response;
      try {
        response = await fetchImpl(`${baseUrl}/imports/combined-export`, json("POST", { session_ids: sessionIds, format, kind }));
      } catch {
        throw new ApiError(0, "network_error", "The Pricor server cannot be reached.");
      }
      if (!response.ok) await fail(response);
      const named = /filename="?([^";]+)"?/.exec(response.headers.get("Content-Disposition") ?? "");
      return { blob: await response.blob(), fileName: named?.[1] ?? `pricor-combined-${kind}.${format}` };
    },
    recordEvent: (event, group) => call<void>("/events", json("POST", { event, group })),
    warmUp: async () => {
      try {
        await fetchImpl(`${baseUrl}/warm-up`, { method: "POST" });
      } catch {
        // The page works the same without it.
      }
    },
    listSamples: () => call<SampleListing[]>("/samples"),
    async downloadSample(sample) {
      let response: Response;
      try {
        response = await fetchImpl(`${baseUrl}/samples/${encodeURIComponent(sample.id)}`);
      } catch {
        throw new ApiError(0, "network_error", "The Pricor server cannot be reached.");
      }
      if (!response.ok) await fail(response);
      const bytes = await response.arrayBuffer();
      return new File([bytes], sample.file_name, { type: response.headers.get("Content-Type") ?? "" });
    },
  };
}
