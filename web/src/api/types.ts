/** Shapes returned by the Pricor API (see src/pricor/entrypoints/api.py). */

export type Language = "en" | "es";

export type SessionStatus =
  | "header_choice_required"
  | "role_confirmation_required"
  | "questions_pending"
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
  /** A cascade stage name ("heuristics", "gemma"), "user", or null while undecided. */
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
}
