import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ApiError, type ApiClient, type OutputFormatApiClient } from "../api/client";
import type { OutputFormat } from "../api/types";
import { previewPage, session } from "../test/fixtures";
import { renderWithI18n } from "../test/render";
import { ImportWizard } from "./ImportWizard";

const ready = session({ status: "ready_for_preview", answers: { currency: "ARS" } });
const approved = { ...ready, status: "approved" as const, approved: true };

const confirmed: OutputFormat = {
  name: "mi-sistema.xlsx",
  state: "confirmed",
  fields: ["supplier_code", "unit_cost_net"],
  columns: [
    { index: 0, name: "Código", samples: [], proposal: { source: "field:supplier_code", proposed_by: "gemma", confidence: 0.9 }, source: "field:supplier_code", kind: "code" },
    { index: 1, name: "Costo", samples: [], proposal: { source: "field:unit_cost_net", proposed_by: "gemma", confidence: 0.9 }, source: "field:unit_cost_net", kind: "price" },
  ],
};

function fakeApi(stored: OutputFormat | null, overrides: Partial<ApiClient> = {}): ApiClient & OutputFormatApiClient {
  const unexpected = (name: string) => () => Promise.reject(new Error(`unexpected call: ${name}`));
  return {
    createImport: vi.fn().mockResolvedValue(ready),
    getImport: vi.fn(unexpected("getImport")),
    chooseHeader: vi.fn(unexpected("chooseHeader")),
    setRoles: vi.fn(unexpected("setRoles")),
    answer: vi.fn(unexpected("answer")),
    setManualRate: vi.fn(unexpected("setManualRate")),
    refreshRate: vi.fn(unexpected("refreshRate")),
    preview: vi.fn().mockResolvedValue(previewPage()),
    approve: vi.fn().mockResolvedValue(approved),
    listSheets: vi.fn().mockResolvedValue([]),
    getSample: vi.fn().mockResolvedValue({ header: [], rows: [] }),
    exportSheet: vi.fn().mockResolvedValue({ header: [], rows: [], total: 0 }),
    askQuestion: vi.fn().mockResolvedValue({ reply: "", suggested_option: null }),
    report: vi.fn(() => Promise.reject(new ApiError(409, "no_previous_import", "nothing to compare with"))),
    exportUrl: (id, format) => `/imports/${id}/export?format=${format}`,
    rejectedUrl: (id, format) => `/imports/${id}/rejected?format=${format}`,
    reportUrl: (id) => `/imports/${id}/report/export?format=csv`,
    config: vi.fn().mockResolvedValue({ model_provider: "ollama", demo: false }),
    getOutputFormat: vi.fn().mockResolvedValue(stored),
    uploadOutputFormat: vi.fn(),
    confirmOutputFormat: vi.fn(),
    defineOutputFormat: vi.fn(),
    deleteOutputFormat: vi.fn(),
    ...overrides,
  };
}

async function toPreview() {
  await userEvent.type(screen.getByLabelText("Supplier name"), "Ferreteria Ejemplo");
  await userEvent.upload(screen.getByLabelText("Price list file"), new File(["a,b"], "lista.csv"));
  await userEvent.click(screen.getByRole("button", { name: "Start import" }));
  await userEvent.click(await screen.findByRole("button", { name: "Confirm columns" }));
  await userEvent.click(await screen.findByRole("button", { name: "Continue to approval" }));
}

const stepNames = () => within(screen.getByRole("navigation", { name: "Import steps" })).getAllByRole("listitem").map((item) => item.textContent?.replace(/^(✓|\d+)/, ""));

describe("ImportWizard output format step", () => {
  it("keeps the template panel out of the upload step", async () => {
    const api = fakeApi(confirmed);
    renderWithI18n(<ImportWizard api={api} />);
    expect(await screen.findByLabelText("Price list file")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Products file columns" })).toBeNull();
    expect(screen.queryByLabelText("Template file")).toBeNull();
    expect(api.getOutputFormat).not.toHaveBeenCalled();
  });

  it("puts the output format between the preview and the approval", async () => {
    renderWithI18n(<ImportWizard api={fakeApi(null)} />);
    await screen.findByLabelText("Price list file");
    expect(stepNames()).toEqual(["Upload", "Columns", "Questions", "Preview", "Output format", "Approve"]);
  });

  it("summarises a saved format and goes to approval in one click", async () => {
    const api = fakeApi(confirmed);
    renderWithI18n(<ImportWizard api={api} />);
    await toPreview();
    expect(await screen.findByText("Using your format: 2 columns")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Products file columns" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Continue to approval" }));
    expect(await screen.findByRole("button", { name: "Approve import" })).toBeInTheDocument();
  });

  it("opens the editor from Change", async () => {
    renderWithI18n(<ImportWizard api={fakeApi(confirmed)} />);
    await toPreview();
    await userEvent.click(await screen.findByRole("button", { name: "Change" }));
    expect(await screen.findByRole("region", { name: "Products file columns" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Change" })).toBeNull();
  });

  it("continues with the standard columns when there is no format, and offers to set one up", async () => {
    renderWithI18n(<ImportWizard api={fakeApi(null)} />);
    await toPreview();
    expect(await screen.findByText("The products file will use Pricor's standard columns.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Set up my format" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Continue to approval" }));
    expect(await screen.findByRole("button", { name: "Approve import" })).toBeInTheDocument();
  });

  it("speaks to the user as usted in Spanish", async () => {
    renderWithI18n(<ImportWizard api={fakeApi(confirmed)} />, "es");
    await userEvent.type(screen.getByLabelText("Nombre del proveedor"), "Ferreteria Ejemplo");
    await userEvent.upload(screen.getByLabelText("Archivo de la lista de precios"), new File(["a,b"], "lista.csv"));
    await userEvent.click(screen.getByRole("button", { name: "Iniciar importación" }));
    await userEvent.click(await screen.findByRole("button", { name: "Confirmar columnas" }));
    await userEvent.click(await screen.findByRole("button", { name: "Continuar a la aprobación" }));
    expect(await screen.findByText("Usando su formato: 2 columnas")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cambiar" })).toBeInTheDocument();
  });

  it("locks the step once the import is approved, like the other plan steps", async () => {
    renderWithI18n(<ImportWizard api={fakeApi(null)} />);
    await toPreview();
    await userEvent.click(await screen.findByRole("button", { name: "Continue to approval" }));
    await userEvent.click(await screen.findByRole("button", { name: "Approve import" }));
    await screen.findByRole("link", { name: "Products (CSV)" });
    expect(screen.getByRole("navigation", { name: "Import steps" })).toHaveTextContent("Output format locked");
  });

  it("has no output format step when the server offers none", async () => {
    const { getOutputFormat: _a, uploadOutputFormat: _b, confirmOutputFormat: _c, defineOutputFormat: _d, deleteOutputFormat: _e, ...plain } = fakeApi(null);
    renderWithI18n(<ImportWizard api={plain} />);
    await screen.findByLabelText("Price list file");
    expect(stepNames()).toEqual(["Upload", "Columns", "Questions", "Preview", "Approve"]);
  });
});
