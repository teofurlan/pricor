import type { ColumnState, PlanChange, PreviewItem, PreviewPage, Question, SessionState } from "../api/types";

export function change(overrides: Partial<PlanChange> = {}): PlanChange {
  return {
    kind: "moved",
    header: "codigo",
    old_index: 0,
    new_index: 1,
    old_type: "code",
    new_type: "code",
    used_by_plan: false,
    role: "code",
    old_value: null,
    new_value: null,
    ...overrides,
  };
}

export function column(overrides: Partial<ColumnState> = {}): ColumnState {
  return {
    index: 0,
    header: "Codigo",
    role: "code",
    decided_by: "heuristics",
    score: 0.95,
    rationale: "header looks like a product code",
    samples: ["A1", "A2"],
    proposals: [],
    ...overrides,
  };
}

export function question(overrides: Partial<Question> = {}): Question {
  return {
    id: "currency",
    text: { en: "Which currency are the prices in?", es: "¿En qué moneda están los precios?" },
    options: [
      { token: "ARS", label: { en: "Argentine pesos (ARS)", es: "Pesos argentinos (ARS)" } },
      { token: "USD", label: { en: "US dollars (USD)", es: "Dólares estadounidenses (USD)" } },
    ],
    allows_custom: false,
    reason: "the list has no currency column",
    model_phrasing: null,
    suggestion: null,
    ...overrides,
  };
}

export function session(overrides: Partial<SessionState> = {}): SessionState {
  return {
    id: "s1",
    status: "questions_pending",
    supplier_name: "Ferreteria Ejemplo",
    file_name: "lista.csv",
    sheet_name: "lista",
    header: { row_index: 1, confidence: 0.9, ambiguous: false, candidates: [] },
    columns: [column()],
    role_issues: [],
    questions: [],
    answers: {},
    notices: [],
    approved: false,
    mode: "first_import",
    based_on_plan_version: null,
    changes: [],
    ...overrides,
  };
}

export function previewItem(overrides: Partial<PreviewItem> = {}): PreviewItem {
  return {
    row_number: 3,
    status: "accepted",
    original: ["A1", "Tornillo", "1.210,00", "21%"],
    trace: [
      { step: "original", value: "1.210,00" },
      { step: "parse_number", value: "1210.00" },
      { step: "strip_vat", value: "1000.00" },
      { step: "rounding", value: "1000.00" },
    ],
    record: { supplier_code: "A1", description: "Tornillo", unit_cost_net: "1000.00", currency: "ARS" },
    reasons: [],
    ...overrides,
  };
}

export function previewPage(overrides: Partial<PreviewPage> = {}): PreviewPage {
  return {
    offset: 0,
    limit: 50,
    total_items: 6,
    totals: {
      data_rows: 6,
      accepted: 5,
      rejected: 1,
      rejected_rows: [{ row_number: 8, reasons: ["cost: cannot parse 'abc' as a number"] }],
      reason_counts: { "cost: cannot parse 'abc' as a number": 1 },
      skipped_rows: { empty: 1, total: 1, section: 0, preamble: 1 },
    },
    items: [previewItem()],
    ...overrides,
  };
}
