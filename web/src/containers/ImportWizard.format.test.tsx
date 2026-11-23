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
  await userEvent.upload(screen.getByLabelText("Price list file"), new File(["a,b"], "lista.csv"));
  await userEvent.clear(screen.getByLabelText("Supplier for lista.csv"));
  await userEvent.type(screen.getByLabelText("Supplier for lista.csv"), "Ferreteria Ejemplo");
  await userEvent.click(screen.getByRole("button", { name: "Start import" }));
  await userEvent.click(await screen.findByRole("button", { name: "Confirm columns" }));
  await userEvent.click(await screen.findByRole("button", { name: "Continue to approval" }));
}

const stepNames = () => within(screen.getByRole("navigation", { name: "Import steps" })).getAllByRole("listitem").map((item) => item.textContent?.replace(/^(✓|\d+)/, ""));

describe("ImportWizard output format drawer", () => {
  it("keeps the weekly stepper to 5 steps without an extra Output format stop", async () => {
    renderWithI18n(<ImportWizard api={fakeApi(confirmed)} />);
    await screen.findByLabelText("Price list file");
    expect(stepNames()).toEqual(["Upload", "Columns", "Questions", "Preview", "Approve"]);
    expect(screen.queryByRole("region", { name: "Products file columns" })).toBeNull();
  });

  it("shows the saved format count in the top bar and opens the non-modal format drawer", async () => {
    const api = fakeApi(confirmed);
    renderWithI18n(<ImportWizard api={api} />);
    const trigger = await screen.findByRole("button", { name: "Format: Custom (2 cols)" });
    await userEvent.click(trigger);
    const drawer = await screen.findByRole("complementary", { name: "Export format" });
    expect(within(drawer).getByRole("region", { name: "Products file columns" })).toBeInTheDocument();
    await userEvent.click(within(drawer).getByRole("button", { name: "Close format" }));
  });

  it("goes straight from Preview to Approve and surfaces a quick Change link before approving", async () => {
    renderWithI18n(<ImportWizard api={fakeApi(confirmed)} />);
    await toPreview();
    expect(await screen.findByRole("button", { name: "Approve and generate file" })).toBeInTheDocument();
    expect(screen.getByText("Export format: Your format (2 columns)")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Change" }));
    expect(await screen.findByRole("complementary", { name: "Export format" })).toBeInTheDocument();
  });

  it("shows standard format label when no custom format is stored", async () => {
    renderWithI18n(<ImportWizard api={fakeApi(null)} />);
    expect(await screen.findByRole("button", { name: "Format: Standard" })).toBeInTheDocument();
    await toPreview();
    expect(await screen.findByText("Export format: Pricor standard columns")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve and generate file" })).toBeInTheDocument();
  });

  it("speaks to the user as usted in Spanish", async () => {
    renderWithI18n(<ImportWizard api={fakeApi(confirmed)} />, "es");
    expect(await screen.findByRole("button", { name: "Formato: Mi sistema (2 col.)" })).toBeInTheDocument();
    await userEvent.upload(screen.getByLabelText("Archivo de la lista de precios"), new File(["a,b"], "lista.csv"));
    await userEvent.clear(screen.getByLabelText("Proveedor de lista.csv"));
    await userEvent.type(screen.getByLabelText("Proveedor de lista.csv"), "Ferreteria Ejemplo");
    await userEvent.click(screen.getByRole("button", { name: "Iniciar importación" }));
    await userEvent.click(await screen.findByRole("button", { name: "Confirmar columnas" }));
    await userEvent.click(await screen.findByRole("button", { name: "Continuar a la aprobación" }));
    expect(await screen.findByText("Formato de exportación: Su formato (2 columnas)")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cambiar" })).toBeInTheDocument();
  });

  it("hides the format button when the server offers no output format API", async () => {
    const { getOutputFormat: _a, uploadOutputFormat: _b, confirmOutputFormat: _c, defineOutputFormat: _d, deleteOutputFormat: _e, ...plain } = fakeApi(null);
    renderWithI18n(<ImportWizard api={plain} />);
    await screen.findByLabelText("Price list file");
    expect(screen.queryByRole("button", { name: /Format:/ })).toBeNull();
    expect(stepNames()).toEqual(["Upload", "Columns", "Questions", "Preview", "Approve"]);
  });
});
