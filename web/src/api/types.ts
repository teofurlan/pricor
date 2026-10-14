/** Shapes returned by the Pricor API (see src/pricor/entrypoints/api.py). */

export type Language = "en" | "es";

export type SessionStatus =
  | "header_choice_required"
  | "role_confirmation_required"
  | "questions_pending"
  | "fx_rate_required"
  | "ready_for_preview"
  | "approved";

export type ColumnRole =
  | "code"
  | "description"
  | "cost_price"
  | "retail_price"
  | "vat_rate"
  | "units_per_pack"
  | "barcode"
  | "discount"
  | "currency"
  | "ignore";

export const COLUMN_ROLES: readonly ColumnRole[] = [
  "code",
  "description",
  "cost_price",
  "retail_price",
  "vat_rate",
  "units_per_pack",
  "barcode",
  "discount",
  "currency",
  "ignore",
];

export interface HeaderCandidate {
  row_index: number;
  file_row: number;
  cells: string[];
}

export interface HeaderState {
  row_index: number | null;
  confidence: number;
  ambiguous: boolean;
  candidates: HeaderCandidate[];
}

export interface StageProposal {
  stage: string;
  role: ColumnRole;
  score: number;
  rationale: string;
}

export interface ColumnState {
  index: number;
  header: string;
  role: ColumnRole | null;
  /** A cascade stage name ("heuristics", "gemma"), "user", "saved_plan", or null while undecided. */
  decided_by: string | null;
  score: number;
  rationale: string;
  /** A few representative cell values from the column. */
  samples: string[];
  proposals: StageProposal[];
}

export interface LocalizedText {
  en: string;
  es: string;
}

export interface QuestionOption {
  token: string;
  label: LocalizedText;
}

export interface Suggestion {
  suggested_by: string;
  option: string;
  confidence: number;
  calibrated: boolean;
  evidence: { column_index: number; sample: string }[];
}

export interface Question {
  id: string;
  text: LocalizedText;
  options: QuestionOption[];
  allows_custom: boolean;
  reason: string;
  model_phrasing: string | null;
  suggestion: Suggestion | null;
}

export interface Notice {
  code: string;
  message: string;
  stage: string | null;
}

export type PlanChangeKind =
  | "moved"
  | "retyped"
  | "new"
  | "missing"
  | "sheet_changed"
  | "header_row_changed";

/** One difference between a new file and the saved plan it reuses. */
export interface PlanChange {
  kind: PlanChangeKind;
  /** Normalized column header; empty for sheet and header-row changes. */
  header: string;
  old_index: number | null;
  new_index: number | null;
  old_type: string | null;
  new_type: string | null;
  /** For a missing column: the saved plan read it. */
  used_by_plan: boolean;
  /** What the saved plan used the column for. */
  role: string | null;
  old_value: string | null;
  new_value: string | null;
}

/** The exchange rate one run converts with (see `FxSnapshot` on the server). */
export interface FxSnapshot {
  /** Exact decimal text. */
  rate: string;
  /** The plan's rate type, or "manual" for a rate the user typed. */
  rate_type: string;
  side: "compra" | "venta";
  /** "dolarapi" or "manual". */
  source: string;
  quoted_at: string;
  /** ISO date of the quote. */
  date: string;
  /** A cached quote used because the live source could not be reached. */
  stale: boolean;
}

/** `null` on a session whose plan does not convert currency. */
export interface FxState {
  from: string;
  to: string;
  rate_type: string;
  side: "compra" | "venta";
  /** Why no live rate could be obtained, when `snapshot` is null. */
  error: string | null;
  snapshot: FxSnapshot | null;
}

export type ImportMode = "first_import" | "reuse";

export interface SessionState {
  id: string;
  status: SessionStatus;
  supplier_name: string;
  file_name: string;
  sheet_name: string;
  header: HeaderState;
  columns: ColumnState[];
  role_issues: string[];
  questions: Question[];
  answers: Record<string, string>;
  notices: Notice[];
  approved: boolean;
  mode: ImportMode;
  based_on_plan_version: number | null;
  changes: PlanChange[];
  fx: FxState | null;
}

export interface TraceStep {
  step: string;
  value: string;
}

export interface PreviewItem {
  row_number: number;
  status: "accepted" | "rejected";
  original: string[];
  trace: TraceStep[];
  record: Record<string, string | null> | null;
  reasons: string[];
}

export interface PreviewTotals {
  data_rows: number;
  accepted: number;
  rejected: number;
  rejected_rows: { row_number: number; reasons: string[] }[];
  reason_counts: Record<string, number>;
  skipped_rows: Record<string, number>;
}

export interface PreviewPage {
  offset: number;
  limit: number;
  total_items: number;
  totals: PreviewTotals;
  items: PreviewItem[];
}

export type ExportFormat = "csv" | "xlsx";

export interface CreateImportInput {
  file: File;
  supplierName: string;
  sheet?: string;
  language: Language;
  /** Ignore the supplier's saved plan and run a first import. */
  forceFirstImport?: boolean;
}

export interface ReportChange {
  supplier_code: string;
  description: string;
  currency: string;
  previous_cost: string;
  current_cost: string;
  change: string;
  /** Percentage rounded for display ("4.20"), or null when the previous cost was zero. */
  change_pct: string | null;
  anomaly: boolean;
}

export interface ReportProduct {
  supplier_code: string;
  description: string;
  currency: string;
  unit_cost_net: string;
}

export interface ReportCurrencyChange {
  supplier_code: string;
  description: string;
  previous_currency: string;
  current_currency: string;
  previous_cost: string;
  current_cost: string;
}

export interface ReportAmbiguousCode {
  supplier_code: string;
  previous_count: number;
  current_count: number;
}

export interface ReportImport {
  import_id: string;
  imported_at: string;
  record_count: number;
}

export interface ReportSummary {
  unchanged: number;
  increases: number;
  decreases: number;
  from_zero: number;
  new_products: number;
  discontinued: number;
  currency_changed: number;
  ambiguous: number;
  anomalies: number;
  /** Median change of the increases and decreases, as a rounded percentage ("4.20"). */
  median_change_pct: string | null;
}

/** What changed between an approved import and the supplier's previous approved one. */
export interface PriceReport {
  import_id: string;
  supplier_name: string;
  /** The anomaly threshold as a ratio ("0.30" is 30%). */
  threshold: string;
  previous_import: ReportImport;
  current_import: ReportImport;
  summary: ReportSummary;
  increases: ReportChange[];
  decreases: ReportChange[];
  from_zero: ReportChange[];
  anomalies: ReportChange[];
  new_products: ReportProduct[];
  discontinued: ReportProduct[];
  currency_changed: ReportCurrencyChange[];
  ambiguous_codes: ReportAmbiguousCode[];
}
