import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ApiError, type ApiClient } from "../api/client";
import { ServerConfigProvider } from "../api/serverConfig";
import type { SessionState } from "../api/types";
import { change, column, fxState, previewPage, priceReport, question, session } from "../test/fixtures";
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
    setManualRate: vi.fn(unexpected("setManualRate")),
    refreshRate: vi.fn(unexpected("refreshRate")),
    preview: vi.fn(unexpected("preview")),
    approve: vi.fn(unexpected("approve")),
    listSheets: vi.fn().mockResolvedValue([]),
    getSample: vi.fn().mockResolvedValue({ header: [], rows: [] }),
    exportSheet: vi.fn().mockResolvedValue({ header: [], rows: [], total: 0 }),
    askQuestion: vi.fn().mockResolvedValue({ reply: "", suggested_option: null }),
    // A first import has no earlier list to compare with, which is the quiet default here.
    report: vi.fn(() => Promise.reject(new ApiError(409, "no_previous_import", "nothing to compare with"))),
    exportUrl: (id, format) => `/imports/${id}/export?format=${format}`,
    rejectedUrl: (id, format) => `/imports/${id}/rejected?format=${format}`,
    reportUrl: (id) => `/imports/${id}/report/export?format=csv`,
    config: vi.fn().mockResolvedValue({ model_provider: "ollama", demo: false }),
    ...overrides,
  };
}

async function startImport(lang: "en" | "es" = "en") {
  const supplierLabel = lang === "es" ? "Proveedor de lista.csv" : "Supplier for lista.csv";
  const fileLabel = lang === "es" ? "Archivo de la lista de precios" : "Price list file";
  const buttonLabel = lang === "es" ? "Iniciar importación" : "Start import";
  await userEvent.upload(screen.getByLabelText(fileLabel), new File(["a,b"], "lista.csv"));
  await userEvent.clear(screen.getByLabelText(supplierLabel));
  await userEvent.type(screen.getByLabelText(supplierLabel), "Ferreteria Ejemplo");
  await userEvent.click(screen.getByRole("button", { name: buttonLabel }));
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
  it("forgets answers the server cleared when the header row is chosen again", async () => {
    const ambiguous = session({
      status: "header_choice_required",
      header: {
        row_index: null, confidence: 0.4, ambiguous: true,
        candidates: [
          { row_index: 0, file_row: 1, cells: ["Codigo", "Precio", ""] },
          { row_index: 1, file_row: 2, cells: ["Codigo", "Descripcion", "Precio"] },
        ],
      },
      columns: [],
    });
    const asking = session({ status: "questions_pending", questions: [question()], answers: {}, header: { ...ambiguous.header, row_index: 1 } });
    const api = fakeApi({
      createImport: vi.fn().mockResolvedValue(ambiguous),
      chooseHeader: vi.fn().mockResolvedValue(asking),
      answer: vi.fn().mockResolvedValue(session({ status: "ready_for_preview", questions: [question()], answers: { currency: "ARS" }, header: asking.header })),
      preview: vi.fn().mockResolvedValue(previewPage()),
    });
    renderWithI18n(<ImportWizard api={api} />);
    await startImport();
    await userEvent.click(await screen.findByRole("radio", { name: /Row 2/ }));
    await userEvent.click(screen.getByRole("button", { name: "Use this row" }));
    await userEvent.click(await screen.findByRole("button", { name: "Confirm columns" }));
    await userEvent.click(await screen.findByRole("button", { name: /Argentine pesos/ }));
    expect(await screen.findByRole("button", { name: "See the preview" })).toBeEnabled();

    await userEvent.click(screen.getByRole("button", { name: /Header/ }));
    await userEvent.click(await screen.findByRole("radio", { name: /Row 1/ }));
    await userEvent.click(screen.getByRole("button", { name: "Use this row" }));
    await userEvent.click(await screen.findByRole("button", { name: "Confirm columns" }));
    expect(await screen.findByRole("button", { name: /Argentine pesos/ })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", { name: "See the preview" })).toBeDisabled();
  });

  it("ignores a slow answer from the previous import once a new one started", async () => {
    let finishOld!: (value: SessionState) => void;
    const api = fakeApi({
      createImport: vi.fn()
        .mockResolvedValueOnce(session({ status: "questions_pending", questions: [question()], answers: {} }))
        .mockResolvedValueOnce(session({ id: "s2", supplier_name: "Otro proveedor", status: "questions_pending", questions: [question()], answers: {} })),
      answer: vi.fn(() => new Promise<SessionState>((resolve) => { finishOld = resolve; })),
    });
    renderWithI18n(<ImportWizard api={api} />);
    await startImport();
    await userEvent.click(await screen.findByRole("button", { name: "Confirm columns" }));
    await userEvent.click(await screen.findByRole("button", { name: /Argentine pesos/ }));

    await userEvent.click(screen.getByRole("button", { name: /Upload/ }));
    await userEvent.click(await screen.findByRole("button", { name: "Yes, start over" }));
    await startImport();
    await userEvent.click(await screen.findByRole("button", { name: "Confirm columns" }));
    expect(await screen.findByText("Otro proveedor")).toBeInTheDocument();

    finishOld(session({ status: "ready_for_preview", answers: { currency: "ARS" } }));
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(screen.getByText("Otro proveedor")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Argentine pesos/ })).toHaveAttribute("aria-pressed", "false");
  });

  it("guards against discarding an active import when clicking Upload and supports Previous step navigation", async () => {
    const api = fakeApi({
      createImport: vi.fn().mockResolvedValue(withQuestion),
    });
    renderWithI18n(<ImportWizard api={api} />);
    await startImport();
    await userEvent.click(await screen.findByRole("button", { name: "Confirm columns" }));

    await userEvent.click(screen.getByRole("button", { name: "← Previous step" }));
    expect(await screen.findByRole("button", { name: "Confirm columns" })).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Upload" }));
    const guard = await screen.findByRole("alertdialog");
    expect(guard).toHaveTextContent("Leave this import?");
    await userEvent.click(within(guard).getByRole("button", { name: "Keep working" }));
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(screen.getByRole("button", { name: "Confirm columns" })).toBeInTheDocument();
  });

  it("goes where the server says when Continue finds the import not ready", async () => {
    const api = fakeApi({
      createImport: vi.fn().mockResolvedValue(session({ status: "questions_pending", questions: [question()], answers: {} })),
      answer: vi.fn().mockResolvedValue(session({
        status: "role_confirmation_required", questions: [], answers: { currency: "ARS" },
        columns: [column({ index: 0 }), column({ index: 2, header: "Precio", role: null, decided_by: null, samples: ["10"] })],
      })),
      preview: vi.fn().mockResolvedValue(previewPage()),
    });
    renderWithI18n(<ImportWizard api={api} />);
    await startImport();
    await userEvent.click(await screen.findByRole("button", { name: "Confirm columns" }));
    await userEvent.click(await screen.findByRole("button", { name: /Argentine pesos/ }));
    await userEvent.click(await screen.findByRole("button", { name: "See the preview" }));
    expect(await screen.findByRole("button", { name: "Confirm columns" })).toBeInTheDocument();
    expect(api.preview).not.toHaveBeenCalled();
  });

  it("reloads the preview when an answer changes after the import was ready", async () => {
    const vat = question({ id: "vat_rate", allows_custom: true, options: [
      { token: "constant:21", label: { en: "21%", es: "21%" } },
      { token: "constant:10.5", label: { en: "10.5%", es: "10,5%" } },
    ] });
    const at21 = session({ status: "ready_for_preview", questions: [vat], answers: { vat_rate: "constant:21" } });
    const at105 = session({ status: "ready_for_preview", questions: [vat], answers: { vat_rate: "constant:10.5" } });
    const api = fakeApi({
      createImport: vi.fn().mockResolvedValue(at21),
      answer: vi.fn().mockResolvedValue(at105),
      preview: vi.fn().mockResolvedValue(previewPage()),
    });
    renderWithI18n(<ImportWizard api={api} />);
    await startImport();
    await userEvent.click(await screen.findByRole("button", { name: "Confirm columns" }));
    await waitFor(() => expect(api.preview).toHaveBeenCalledTimes(1));
    await userEvent.click(screen.getByRole("button", { name: /Questions/ })); // back from the preview
    await userEvent.click(await screen.findByRole("button", { name: "Change" }));

    await userEvent.click(await screen.findByRole("button", { name: "10.5%" }));
    await waitFor(() => expect(api.preview).toHaveBeenCalledTimes(2));
  });

  it("drops an answer the server refuses instead of showing it as chosen", async () => {
    const vat = question({ id: "vat_rate", allows_custom: true, options: [{ token: "constant:21", label: { en: "21%", es: "21%" } }] });
    const api = fakeApi({
      createImport: vi.fn().mockResolvedValue(session({ status: "questions_pending", questions: [vat], answers: {} })),
      answer: vi.fn().mockRejectedValue(new ApiError(422, "invalid_input", "the answer was refused")),
    });
    renderWithI18n(<ImportWizard api={api} />);
    await startImport();
    await userEvent.click(await screen.findByRole("button", { name: "Confirm columns" }));

    // The card only lets numbers through; this stands in for any value the server still refuses.
    await userEvent.click(await screen.findByRole("button", { name: "21%" }));
    await waitFor(() => expect(api.answer).toHaveBeenCalledWith("s1", "vat_rate", "constant:21"));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "21%" })).toHaveAttribute("aria-pressed", "false"));
  });

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
    expect(await screen.findByText("Automatic suggestion · medium confidence")).toBeInTheDocument();
    const qGroup = screen.getByRole("group", { name: "Which currency are the prices in?" });
    for (const button of within(qGroup).getAllByRole("button")) expect(button).toHaveAttribute("aria-pressed", "false");
    await userEvent.click(screen.getByRole("button", { name: /Argentine pesos/ }));
    expect(api.answer).toHaveBeenCalledWith("s1", "currency", "ARS");
    // An answered question moves to the history above with its answer, where it can be changed.
    const history = await screen.findByRole("list", { name: "Answered questions" });
    expect(within(history).getByText("Argentine pesos (ARS)")).toBeInTheDocument();
    expect(within(history).getByRole("button", { name: "Change" })).toBeInTheDocument();

    await userEvent.click(await screen.findByRole("button", { name: "See the preview" }));
    expect(api.preview).toHaveBeenCalledWith("s1", 0, 50);
    expect(await screen.findByLabelText("Accepted")).toHaveTextContent("5");
    expect(screen.getByLabelText("Rejected")).toHaveTextContent("1");
    expect(screen.getByLabelText("Data rows")).toHaveTextContent("6");
    expect(
      await screen.findByText((_, el) => Boolean(el?.classList.contains("trace__value") && el?.textContent === "1,000.00 ARS")),
    ).toBeInTheDocument();
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

  it("locks the steps that would change the plan once the import is approved", async () => {
    const api = fakeApi({
      createImport: vi.fn().mockResolvedValue(withQuestion),
      answer: vi.fn().mockResolvedValue(ready),
      preview: vi.fn().mockResolvedValue(previewPage()),
      approve: vi.fn().mockResolvedValue(approved),
    });
    renderWithI18n(<ImportWizard api={api} />);
    await startImport();
    await userEvent.click(await screen.findByRole("button", { name: "Confirm columns" }));
    await userEvent.click(await screen.findByRole("button", { name: /Argentine pesos/ }));
    await userEvent.click(await screen.findByRole("button", { name: "See the preview" }));
    await userEvent.click(await screen.findByRole("button", { name: "Continue to approval" }));
    const steps = screen.getByRole("navigation", { name: "Import steps" });
    expect(within(steps).getByRole("button", { name: "Columns" })).toBeInTheDocument();

    await userEvent.click(await screen.findByRole("button", { name: "Approve import" }));
    await screen.findByRole("link", { name: "Products (CSV)" });

    expect(within(steps).queryByRole("button", { name: /Columns/ })).toBeNull();
    expect(within(steps).queryByRole("button", { name: /Questions/ })).toBeNull();
    expect(within(steps).getByText("Columns").closest("li")).toHaveTextContent("locked");
    // The preview stays readable and a new import can still be started.
    expect(within(steps).getByRole("button", { name: "Upload" })).toBeInTheDocument();
    await userEvent.click(within(steps).getByRole("button", { name: "Preview" }));
    expect(await screen.findByLabelText("Accepted")).toHaveTextContent("5");
  });

  it("shows the rate of an approved import without offering to change it", async () => {
    const converting: SessionState = { ...approved, fx: fxState() };
    const api = fakeApi({
      createImport: vi.fn().mockResolvedValue({ ...converting, status: "ready_for_preview", approved: false }),
      preview: vi.fn().mockResolvedValue(previewPage()),
      approve: vi.fn().mockResolvedValue(converting),
    });
    renderWithI18n(<ImportWizard api={api} />);
    await startImport();
    await userEvent.click(await screen.findByRole("button", { name: "Confirm columns" }));
    expect(await screen.findByRole("button", { name: "Use this rate" })).toBeInTheDocument();
    await userEvent.click(await screen.findByRole("button", { name: "Continue to approval" }));
    await userEvent.click(await screen.findByRole("button", { name: "Approve import" }));
    await screen.findByRole("link", { name: "Products (CSV)" });

    await userEvent.click(within(screen.getByRole("navigation", { name: "Import steps" })).getByRole("button", { name: "Preview" }));
    expect(await screen.findByText("1 USD = 1,535 ARS")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Use this rate" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Get the live rate again" })).toBeNull();
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
    expect(within(row).getByText("Needs your confirmation")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Confirm columns" })).toBeDisabled();
    await userEvent.selectOptions(within(row).getByRole("combobox", { name: /Change role/i }), "cost_price");
    await userEvent.click(screen.getByRole("button", { name: "Confirm columns" }));
    expect(api.setRoles).toHaveBeenCalledWith("s1", { 2: "cost_price" });

    // No open question, so the wizard goes straight to the preview.
    expect(await screen.findByLabelText("Accepted")).toHaveTextContent("5");
  });

  it("loads and renders the first 5 rows sample preview on the columns and questions steps", async () => {
    const api = fakeApi({
      createImport: vi.fn().mockResolvedValue(withQuestion),
      getSample: vi.fn().mockResolvedValue({
        header: ["Codigo", "Precio"],
        rows: [["P100", "500"]],
      }),
    });
    renderWithI18n(<ImportWizard api={api} />);
    await startImport();

    // On columns step, sample preview is shown
    expect(await screen.findByRole("heading", { name: "Preview: first 5 rows" })).toBeInTheDocument();
    expect(screen.getByText("P100")).toBeInTheDocument();
    expect(api.getSample).toHaveBeenCalledWith("s1", 5);

    // Proceed to questions step
    await userEvent.click(screen.getByRole("button", { name: "Confirm columns" }));

    // On questions step, sample preview is also shown
    expect(await screen.findByRole("heading", { name: "Preview: first 5 rows" })).toBeInTheDocument();
    expect(screen.getByText("P100")).toBeInTheDocument();
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

  it("shows the model_unavailable notice prominently on columns and compact on later steps", async () => {
    const degraded = {
      ...withQuestion,
      notices: [{ code: "model_unavailable", message: "connection refused", stage: "gemma" }],
    };
    const api = fakeApi({
      createImport: vi.fn().mockResolvedValue(degraded),
      setRoles: vi.fn().mockResolvedValue(degraded),
    });
    renderWithI18n(<ImportWizard api={api} />);
    await startImport();
    // Full banner on Columns step
    const notice = await screen.findByRole("status");
    expect(notice).toHaveTextContent("Gemma was not available");
    expect(notice).toHaveTextContent("Import continues with automatic detection only. Review the columns yourself and answer every question.");
    expect(notice).toHaveTextContent("connection refused");

    // Move to Questions step (later step)
    await userEvent.click(screen.getByRole("button", { name: "Confirm columns" }));
    await screen.findByRole("button", { name: "See the preview" });

    // Compact one-line banner on Questions step
    const compactNotice = screen.getByRole("status");
    expect(compactNotice).toHaveTextContent("Gemma was not available");
    expect(compactNotice).not.toHaveTextContent("Import continues with automatic detection only");
    expect(compactNotice).not.toHaveTextContent("connection refused");
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

  it("shows local upload lede text by default", () => {
    const api = fakeApi();
    renderWithI18n(<ImportWizard api={api} />);
    expect(screen.getByText("Nothing leaves this computer. The list is read here, and every row is accounted for.")).toBeInTheDocument();
  });

  it("shows local upload lede text in Spanish by default", () => {
    const api = fakeApi();
    renderWithI18n(<ImportWizard api={api} />, "es");
    expect(screen.getByText("Nada sale de esta computadora. La lista se lee aquí y cada fila queda contabilizada.")).toBeInTheDocument();
  });

  it("shows hosted upload lede text in hosted mode", () => {
    const api = fakeApi();
    renderWithI18n(
      <ServerConfigProvider hosted={true}>
        <ImportWizard api={api} />
      </ServerConfigProvider>,
    );
    expect(screen.getByText("This is a trial version on the web. The list is processed on Pricor's server, with Gemma on Google's API. Pricor can also be installed on the store's own computer, where the data does not leave it.")).toBeInTheDocument();
  });

  it("shows hosted upload lede text in Spanish in hosted mode", () => {
    const api = fakeApi();
    renderWithI18n(
      <ServerConfigProvider hosted={true}>
        <ImportWizard api={api} />
      </ServerConfigProvider>,
      "es",
    );
    expect(screen.getByText("Esta es una versión de prueba en la web. La lista se procesa en el servidor de Pricor, con Gemma en la API de Google. Pricor también puede instalarse en la computadora del comercio, y allí los datos no salen de ella.")).toBeInTheDocument();
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

  it("says the local models are working in Spanish while a slow call is pending", async () => {
    let finish: (value: SessionState) => void = () => {};
    const api = fakeApi({
      createImport: vi.fn().mockReturnValue(new Promise<SessionState>((resolve) => (finish = resolve))),
    });
    renderWithI18n(<ImportWizard api={api} />, "es");
    await startImport("es");
    expect(await screen.findByText(/Trabajando. Los modelos locales pueden demorar hasta un minuto/)).toBeInTheDocument();
    finish(withQuestion);
    await screen.findByRole("button", { name: "Confirmar columnas" });
    expect(screen.queryByText(/Trabajando. Los modelos locales pueden demorar hasta un minuto/)).toBeNull();
  });

  it("says the models are working in hosted mode while a slow call is pending", async () => {
    let finish: (value: SessionState) => void = () => {};
    const api = fakeApi({
      createImport: vi.fn().mockReturnValue(new Promise<SessionState>((resolve) => (finish = resolve))),
    });
    renderWithI18n(
      <ServerConfigProvider hosted={true}>
        <ImportWizard api={api} />
      </ServerConfigProvider>,
    );
    await startImport();
    expect(await screen.findByText(/Working. This can take up to a minute/)).toBeInTheDocument();
    finish(withQuestion);
    await screen.findByRole("button", { name: "Confirm columns" });
    expect(screen.queryByText(/Working. This can take up to a minute/)).toBeNull();
  });

  it("says the models are working in Spanish in hosted mode while a slow call is pending", async () => {
    let finish: (value: SessionState) => void = () => {};
    const api = fakeApi({
      createImport: vi.fn().mockReturnValue(new Promise<SessionState>((resolve) => (finish = resolve))),
    });
    renderWithI18n(
      <ServerConfigProvider hosted={true}>
        <ImportWizard api={api} />
      </ServerConfigProvider>,
      "es",
    );
    await startImport("es");
    expect(await screen.findByText(/Trabajando. Puede demorar hasta un minuto/)).toBeInTheDocument();
    finish(withQuestion);
    await screen.findByRole("button", { name: "Confirmar columnas" });
    expect(screen.queryByText(/Trabajando. Puede demorar hasta un minuto/)).toBeNull();
  });

  it("shows what changed in prices once the import is approved", async () => {
    const api = fakeApi({
      createImport: vi.fn().mockResolvedValue(ready),
      preview: vi.fn().mockResolvedValue(previewPage()),
      approve: vi.fn().mockResolvedValue(approved),
      report: vi.fn().mockResolvedValue(priceReport()),
    });
    renderWithI18n(<ImportWizard api={api} />);
    await startImport();
    await userEvent.click(await screen.findByRole("button", { name: "Confirm columns" }));
    await userEvent.click(await screen.findByRole("button", { name: "Continue to approval" }));
    expect(api.report).not.toHaveBeenCalled(); // nothing to compare before the user signs

    await userEvent.click(await screen.findByRole("button", { name: "Approve import" }));

    expect(await screen.findByRole("heading", { level: 2, name: "Price comparison" })).toBeInTheDocument();
    const summary = screen.getByRole("region", { name: "Price comparison" });
    expect(summary).toHaveTextContent("unchanged312");
    expect(summary).toHaveTextContent("up85");
    expect(api.report).toHaveBeenCalledWith("s1", undefined);
  });

  it("previews both approved files, and only after the user signs", async () => {
    const sheet = { header: ["supplier_code", "description"], rows: [["A1", "Bolt"]], total: 5 };
    const rejectedSheet = { header: ["source_row", "reasons"], rows: [["8", "Invalid cost"]], total: 1 };
    const api = fakeApi({
      createImport: vi.fn().mockResolvedValue(ready),
      preview: vi.fn().mockResolvedValue(previewPage()),
      approve: vi.fn().mockResolvedValue(approved),
      exportSheet: vi.fn((_: string, file: string) => Promise.resolve(file === "products" ? sheet : rejectedSheet)),
    });
    renderWithI18n(<ImportWizard api={api} />);
    await startImport();
    await userEvent.click(await screen.findByRole("button", { name: "Confirm columns" }));
    await userEvent.click(await screen.findByRole("button", { name: "Continue to approval" }));
    expect(api.exportSheet).not.toHaveBeenCalled();

    await userEvent.click(await screen.findByRole("button", { name: "Approve import" }));

    const table = await screen.findByRole("table", { name: "The products file" });
    expect(table).toHaveTextContent("Bolt");
    expect(api.exportSheet).toHaveBeenCalledWith("s1", "products");
    expect(await screen.findByRole("table", { name: "The rejected-rows file" })).toHaveTextContent("Invalid cost");
    expect(api.exportSheet).toHaveBeenCalledWith("s1", "rejected");
  });

  it("says so when an approved import is the first of its supplier", async () => {
    const api = fakeApi({
      createImport: vi.fn().mockResolvedValue(ready),
      preview: vi.fn().mockResolvedValue(previewPage()),
      approve: vi.fn().mockResolvedValue(approved),
    });
    renderWithI18n(<ImportWizard api={api} />);
    await startImport();
    await userEvent.click(await screen.findByRole("button", { name: "Confirm columns" }));
    await userEvent.click(await screen.findByRole("button", { name: "Continue to approval" }));
    await userEvent.click(await screen.findByRole("button", { name: "Approve import" }));

    expect(await screen.findByText(/This is the first approved list from Ferreteria Ejemplo/)).toBeInTheDocument();
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
    expect(screen.getByText("✓ From the saved plan")).toBeInTheDocument();
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

  it("records both answers when clicking options for two questions back to back while the first is pending", async () => {
    const q1 = question({
      id: "currency",
      text: { en: "Which currency?", es: "Moneda" },
      options: [
        { token: "ARS", label: { en: "Argentine pesos", es: "ARS" } },
        { token: "USD", label: { en: "US dollars", es: "USD" } },
      ],
    });
    const q2 = question({
      id: "vat_included",
      text: { en: "VAT included?", es: "IVA" },
      options: [
        { token: "yes", label: { en: "Yes", es: "Si" } },
        { token: "no", label: { en: "No", es: "No" } },
      ],
    });
    const sessionWithTwoQuestions = session({
      status: "questions_pending",
      questions: [q1, q2],
      answers: {},
    });

    let resolveFirstAnswer!: (value: SessionState) => void;
    const firstAnswerPromise = new Promise<SessionState>((resolve) => {
      resolveFirstAnswer = resolve;
    });

    const api = fakeApi({
      createImport: vi.fn().mockResolvedValue(sessionWithTwoQuestions),
      answer: vi
        .fn()
        .mockImplementationOnce(() => firstAnswerPromise)
        .mockImplementationOnce(() =>
          Promise.resolve(
            session({
              status: "ready_for_preview",
              questions: [q1, q2],
              answers: { currency: "ARS", vat_included: "yes" },
            }),
          ),
        ),
    });

    renderWithI18n(<ImportWizard api={api} />);
    await startImport();
    await userEvent.click(await screen.findByRole("button", { name: "Confirm columns" }));

    // Questions come one at a time; the next appears as soon as the first is answered.
    const arsOption = await screen.findByRole("button", { name: /Argentine pesos/ });
    expect(screen.queryByRole("button", { name: /Yes/ })).toBeNull();

    // Click first question
    await userEvent.click(arsOption);
    expect(api.answer).toHaveBeenCalledWith("s1", "currency", "ARS");

    // Answer the second question back to back while the first API call is still pending
    await userEvent.click(await screen.findByRole("button", { name: /Yes/ }));

    // Resolve first answer
    resolveFirstAnswer(
      session({
        status: "questions_pending",
        questions: [q1, q2],
        answers: { currency: "ARS" },
      }),
    );

    // Both answers must be recorded in order
    await waitFor(() => {
      expect(api.answer).toHaveBeenCalledWith("s1", "vat_included", "yes");
    });
    expect(api.answer).toHaveBeenCalledTimes(2);

    const history = screen.getByRole("list", { name: "Answered questions" });
    expect(within(history).getByText(/Argentine pesos/)).toBeInTheDocument();
    expect(within(history).getByText(/Yes/)).toBeInTheDocument();
  });

  describe("slow first import notice", () => {
    const notice = /The first list can take up to a minute while the model gets ready/;
    // userEvent hangs under fake timers, so the form is driven with fireEvent.
    async function startWithTimers(file = "Price list file", button = "Start import") {
      fireEvent.change(screen.getByLabelText(file), { target: { files: [new File(["a,b"], "lista.csv")] } });
      await act(async () => { await vi.advanceTimersByTimeAsync(0); });
      fireEvent.click(screen.getByRole("button", { name: button }));
    }

    it("shows the notice only after the wait, and removes it when the answer arrives", async () => {
      try {
        let finish: (value: SessionState) => void = () => {};
        const api = fakeApi({ createImport: vi.fn().mockReturnValue(new Promise<SessionState>((resolve) => (finish = resolve))) });
        renderWithI18n(<ImportWizard api={api} />);
        await screen.findByLabelText("Price list file");
        vi.useFakeTimers();
        await startWithTimers();
        await act(async () => { await vi.advanceTimersByTimeAsync(4000); });
        expect(screen.queryByText(notice)).toBeNull();
        expect(screen.getByText(/Working. Local models can take up to a minute/)).toBeInTheDocument();
        await act(async () => { await vi.advanceTimersByTimeAsync(1500); });
        // One waiting message at a time: the minute is explained once, by the notice that replaces the generic line.
        expect(screen.getByText(notice)).toBeInTheDocument();
        expect(screen.queryByText(/Working. Local models can take up to a minute/)).toBeNull();
        expect(screen.getAllByText(/up to a minute/)).toHaveLength(1);
        await act(async () => { finish(withQuestion); await vi.advanceTimersByTimeAsync(0); });
        expect(screen.queryByText(notice)).toBeNull();
      } finally {
        vi.useRealTimers();
      }
    });

    it("removes the notice when the import fails", async () => {
      try {
        let fail: (reason: unknown) => void = () => {};
        const api = fakeApi({ createImport: vi.fn().mockReturnValue(new Promise<SessionState>((_, reject) => (fail = reject))) });
        renderWithI18n(<ImportWizard api={api} />);
        await screen.findByLabelText("Price list file");
        vi.useFakeTimers();
        await startWithTimers();
        await act(async () => { await vi.advanceTimersByTimeAsync(5500); });
        expect(screen.getByText(notice)).toBeInTheDocument();
        await act(async () => { fail(new ApiError(415, "unsupported_format", "unsupported file type")); await vi.advanceTimersByTimeAsync(0); });
        expect(screen.queryByText(notice)).toBeNull();
      } finally {
        vi.useRealTimers();
      }
    });

    it("says it in Spanish", async () => {
      try {
        const api = fakeApi({ createImport: vi.fn().mockReturnValue(new Promise<SessionState>(() => {})) });
        renderWithI18n(<ImportWizard api={api} />, "es");
        await screen.findByLabelText("Archivo de la lista de precios");
        vi.useFakeTimers();
        await startWithTimers("Archivo de la lista de precios", "Iniciar importación");
        await act(async () => { await vi.advanceTimersByTimeAsync(5500); });
        expect(screen.getByText("La primera lista puede tardar hasta un minuto mientras se prepara el modelo.")).toBeInTheDocument();
        expect(screen.queryByText(/Trabajando\./)).toBeNull();
        expect(screen.getAllByText(/hasta un minuto/)).toHaveLength(1);
      } finally {
        vi.useRealTimers();
      }
    });
  });
});
