import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ApiError, type ApiClient } from "../api/client";
import type { SessionState } from "../api/types";
import { change, column, previewPage, question, session } from "../test/fixtures";
import { renderWithI18n } from "../test/render";
import { ImportWizard } from "./ImportWizard";

function fakeApi(overrides: Partial<ApiClient> = {}): ApiClient {
  const unexpected = (name: string) => () => Promise.reject(new Error(`unexpected call: ${name}`));
  return {
    createImport: vi.fn(unexpected("createImport")),
    getImport: vi.fn(unexpected("getImport")),
    chooseHeader: vi.fn(unexpected("chooseHeader")),
    setRoles: vi.fn(unexpected("setRoles")),
    answer: vi.fn(unexpected("answer")),
    preview: vi.fn(unexpected("preview")),
    approve: vi.fn(unexpected("approve")),
    exportUrl: (id, format) => `/imports/${id}/export?format=${format}`,
    rejectedUrl: (id, format) => `/imports/${id}/rejected?format=${format}`,
    ...overrides,
  };
}

async function startImport() {
  await userEvent.type(screen.getByLabelText("Supplier name"), "Ferreteria Ejemplo");
  await userEvent.upload(screen.getByLabelText("Price list file"), new File(["a,b"], "lista.csv"));
  await userEvent.click(screen.getByRole("button", { name: "Start import" }));
}

const withQuestion: SessionState = session({
  status: "questions_pending",
  questions: [
    question({
      suggestion: { suggested_by: "gemma", option: "USD", confidence: 0.6, calibrated: false, evidence: [] },
    }),
  ],
});
const ready: SessionState = session({ status: "ready_for_preview", answers: { currency: "ARS" } });
const approved: SessionState = { ...ready, status: "approved", approved: true };

describe("ImportWizard", () => {
  it("walks a first import from upload to approved exports", async () => {
    const api = fakeApi({
      createImport: vi.fn().mockResolvedValue(withQuestion),
      answer: vi.fn().mockResolvedValue(ready),
      preview: vi.fn().mockResolvedValue(previewPage()),
      approve: vi.fn().mockResolvedValue(approved),
    });
    renderWithI18n(<ImportWizard api={api} />);

    await startImport();
    expect(api.createImport).toHaveBeenCalledWith(
      expect.objectContaining({ supplierName: "Ferreteria Ejemplo", language: "en" }),
    );

    // Columns are always shown before anything else is asked.
    await screen.findByRole("button", { name: "Confirm columns" });
    expect(api.setRoles).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Confirm columns" }));

    // The suggestion is visible and nothing is preselected.
    expect(await screen.findByText("Suggested by Gemma (uncalibrated: 0.6)")).toBeInTheDocument();
    for (const radio of screen.getAllByRole("radio")) expect(radio).not.toBeChecked();
    await userEvent.click(screen.getByRole("radio", { name: /Argentine pesos/ }));
    expect(api.answer).toHaveBeenCalledWith("s1", "currency", "ARS");
    // An answered question stays on screen with its answer, so it can be changed.
    expect(await screen.findByRole("radio", { name: /Argentine pesos/ })).toBeChecked();

    await userEvent.click(await screen.findByRole("button", { name: "See the preview" }));
    expect(api.preview).toHaveBeenCalledWith("s1", 0, 50);
    expect(await screen.findByLabelText("Accepted")).toHaveTextContent("5");
    expect(screen.getByLabelText("Rejected")).toHaveTextContent("1");
    expect(screen.getByLabelText("Data rows")).toHaveTextContent("6");
    expect(screen.getByText("1000.00 ARS")).toBeInTheDocument();
    expect(screen.getByText(/cannot parse 'abc'/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Continue to approval" }));
    await userEvent.click(await screen.findByRole("button", { name: "Approve import" }));
    expect(api.approve).toHaveBeenCalledWith("s1");

    const csv = await screen.findByRole("link", { name: "Products (CSV)" });
    expect(csv).toHaveAttribute("href", "/imports/s1/export?format=csv");
    expect(screen.getByRole("link", { name: "Rejected rows (XLSX)" })).toHaveAttribute(
      "href",
      "/imports/s1/rejected?format=xlsx",
    );
  });

  it("asks for the header row when the sheet is ambiguous, then continues with the user's choice", async () => {
    const ambiguous = session({
      status: "header_choice_required",
      header: {
        row_index: null,
        confidence: 0.4,
        ambiguous: true,
        candidates: [
          { row_index: 0, file_row: 1, cells: ["Contacto", "", ""] },
          { row_index: 1, file_row: 2, cells: ["Codigo", "Descripcion", "Precio"] },
        ],
      },
      columns: [],
    });
    const needsRole = session({
      status: "role_confirmation_required",
      columns: [column({ index: 0 }), column({ index: 2, header: "Precio", role: null, decided_by: null, samples: ["10"] })],
    });
    const api = fakeApi({
      createImport: vi.fn().mockResolvedValue(ambiguous),
      chooseHeader: vi.fn().mockResolvedValue(needsRole),
      setRoles: vi.fn().mockResolvedValue(ready),
      preview: vi.fn().mockResolvedValue(previewPage()),
    });
    renderWithI18n(<ImportWizard api={api} />);

    await startImport();
    await userEvent.click(await screen.findByRole("radio", { name: /Row 2/ }));
    await userEvent.click(screen.getByRole("button", { name: "Use this row" }));
    expect(api.chooseHeader).toHaveBeenCalledWith("s1", 1);

    const row = await screen.findByRole("row", { name: /Precio/ });
    expect(within(row).getByText("Needs your choice")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Confirm columns" })).toBeDisabled();
    await userEvent.selectOptions(within(row).getByRole("combobox"), "cost_price");
    await userEvent.click(screen.getByRole("button", { name: "Confirm columns" }));
    expect(api.setRoles).toHaveBeenCalledWith("s1", { 2: "cost_price" });

    // No open question, so the wizard goes straight to the preview.
    expect(await screen.findByLabelText("Accepted")).toHaveTextContent("5");
  });

  it("can tell the server the sheet has no header", async () => {
    const ambiguous = session({
      status: "header_choice_required",
      header: { row_index: null, confidence: 0.2, ambiguous: true, candidates: [{ row_index: 0, file_row: 1, cells: ["A1", "x"] }] },
      columns: [],
    });
    const api = fakeApi({
      createImport: vi.fn().mockResolvedValue(ambiguous),
      chooseHeader: vi.fn().mockResolvedValue(withQuestion),
    });
    renderWithI18n(<ImportWizard api={api} />);
    await startImport();
    await userEvent.click(await screen.findByRole("button", { name: "This sheet has no header row" }));
    expect(api.chooseHeader).toHaveBeenCalledWith("s1", null);
    expect(await screen.findByRole("button", { name: "Confirm columns" })).toBeInTheDocument();
  });

  it("explains a 409 no_accepted_rows on approval and lets the user go back", async () => {
    const api = fakeApi({
      createImport: vi.fn().mockResolvedValue(ready),
      preview: vi.fn().mockResolvedValue(previewPage()),
      approve: vi
        .fn()
        .mockRejectedValue(new ApiError(409, "no_accepted_rows", "nothing to approve")),
    });
    renderWithI18n(<ImportWizard api={api} />);
    await startImport();
    await userEvent.click(await screen.findByRole("button", { name: "Confirm columns" }));
    await userEvent.click(await screen.findByRole("button", { name: "Continue to approval" }));
    await userEvent.click(await screen.findByRole("button", { name: "Approve import" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("No row passed the checks");
    expect(screen.queryByRole("link", { name: "Products (CSV)" })).toBeNull();
    expect(screen.getByRole("button", { name: "Approve import" })).toBeEnabled();
    // The finished steps stay reachable.
    expect(screen.getByRole("button", { name: /Columns/ })).toBeInTheDocument();
  });

  it("shows the model_unavailable notice prominently and keeps going", async () => {
    const degraded = {
      ...withQuestion,
      notices: [{ code: "model_unavailable", message: "connection refused", stage: "gemma" }],
    };
    const api = fakeApi({ createImport: vi.fn().mockResolvedValue(degraded) });
    renderWithI18n(<ImportWizard api={api} />);
    await startImport();
    expect(await screen.findByRole("status")).toHaveTextContent("Gemma was not available");
    expect(screen.getByRole("button", { name: "Confirm columns" })).toBeEnabled();
  });

  it("keeps the upload form and says why when the file is refused", async () => {
    const api = fakeApi({
      createImport: vi.fn().mockRejectedValue(new ApiError(415, "unsupported_format", "unsupported file type")),
    });
    renderWithI18n(<ImportWizard api={api} />);
    await startImport();
    expect(await screen.findByRole("alert")).toHaveTextContent("unsupported file type");
    await waitFor(() => expect(screen.getByRole("button", { name: "Start import" })).toBeEnabled());
  });

  it("says the local models are working while a slow call is pending", async () => {
    let finish: (value: SessionState) => void = () => {};
    const api = fakeApi({
      createImport: vi.fn().mockReturnValue(new Promise<SessionState>((resolve) => (finish = resolve))),
    });
    renderWithI18n(<ImportWizard api={api} />);
    await startImport();
    expect(await screen.findByText(/Working. Local models can take up to a minute/)).toBeInTheDocument();
    finish(withQuestion);
    await screen.findByRole("button", { name: "Confirm columns" });
    expect(screen.queryByText(/Working. Local models can take up to a minute/)).toBeNull();
  });

  it("shows the reused plan and what changed on the columns step", async () => {
    const reused = session({
      status: "ready_for_preview",
      mode: "reuse",
      based_on_plan_version: 2,
      columns: [column({ decided_by: "saved_plan" })],
      changes: [change({ kind: "moved", header: "codigo", old_index: 0, new_index: 1 })],
    });
    const api = fakeApi({ createImport: vi.fn().mockResolvedValue(reused) });
    renderWithI18n(<ImportWizard api={api} />);

    await startImport();

    expect(await screen.findByRole("heading", { name: "Reusing plan v2 for Ferreteria Ejemplo" })).toBeInTheDocument();
    expect(screen.getByText(/moved from column 1 to column 2/)).toBeInTheDocument();
    expect(screen.getByText("Saved plan")).toBeInTheDocument();
  });

  it("shows no reuse banner for a first import", async () => {
    const api = fakeApi({ createImport: vi.fn().mockResolvedValue(withQuestion) });
    renderWithI18n(<ImportWizard api={api} />);

    await startImport();

    await screen.findByRole("button", { name: "Confirm columns" });
    expect(screen.queryByText(/Reusing plan/)).not.toBeInTheDocument();
  });

  it("switches the whole interface to Spanish", async () => {
    renderWithI18n(<ImportWizard api={fakeApi()} />);
    await userEvent.click(screen.getByRole("button", { name: "ES" }));
    expect(screen.getByRole("button", { name: "Iniciar importación" })).toBeInTheDocument();
  });
});
