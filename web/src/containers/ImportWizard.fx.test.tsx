import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { ApiClient } from "../api/client";
import { ApiError } from "../api/client";
import { fxState, previewItem, previewPage, question, session } from "../test/fixtures";
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
    report: vi.fn(() => Promise.reject(new ApiError(409, "no_previous_import", "nothing to compare with"))),
    exportUrl: (id, format) => `/imports/${id}/export?format=${format}`,
    rejectedUrl: (id, format) => `/imports/${id}/rejected?format=${format}`,
    reportUrl: (id) => `/imports/${id}/report/export?format=csv`,
    ...overrides,
  };
}

async function startImport() {
  await userEvent.type(screen.getByLabelText("Supplier name"), "Emilio");
  await userEvent.upload(screen.getByLabelText("Price list file"), new File(["a,b"], "lista.csv"));
  await userEvent.click(screen.getByRole("button", { name: "Start import" }));
  await userEvent.click(await screen.findByRole("button", { name: "Confirm columns" }));
}

const fxQuestion = question({
  id: "fx_conversion",
  text: { en: "Convert to ARS, and with which rate?", es: "¿Se convierte a ARS y con qué cotización?" },
  options: [
    { token: "keep", label: { en: "Keep the original currency", es: "Mantener la moneda original" } },
    { token: "oficial:venta", label: { en: "Convert to ARS: Official, sell rate", es: "Convertir a ARS: Oficial, venta" } },
  ],
  suggestion: { suggested_by: "setting", option: "oficial:venta", confidence: 1, calibrated: true, evidence: [] },
});
const asking = session({ status: "questions_pending", questions: [fxQuestion] });
const needsRate = session({
  status: "fx_rate_required",
  answers: { fx_conversion: "oficial:venta" },
  fx: fxState({ snapshot: null, error: "cannot reach DolarAPI" }),
});
const ready = session({
  status: "ready_for_preview",
  answers: { fx_conversion: "oficial:venta" },
  fx: fxState({ snapshot: { ...fxState().snapshot!, source: "manual", rate_type: "manual", rate: "1420.5" } }),
});

describe("ImportWizard: currency conversion", () => {
  it("blocks on a missing rate, takes a typed one, and shows the rate in the preview", async () => {
    const api = fakeApi({
      createImport: vi.fn().mockResolvedValue(asking),
      answer: vi.fn().mockResolvedValue(needsRate),
      setManualRate: vi.fn().mockResolvedValue(ready),
      preview: vi.fn().mockResolvedValue(
        previewPage({
          items: [
            previewItem({
              record: { supplier_code: "A2", description: "x", unit_cost_net: "2.50", currency: "USD", unit_cost_net_converted: "3551.25" },
            }),
          ],
        }),
      ),
    });
    renderWithI18n(<ImportWizard api={api} />);
    await startImport();

    expect(await screen.findByText("YOUR DEFAULT")).toBeInTheDocument();
    for (const radio of screen.getAllByRole("radio")) expect(radio).not.toBeChecked(); // never auto-applied
    await userEvent.click(screen.getByRole("radio", { name: /Official, sell rate/ }));
    expect(api.answer).toHaveBeenCalledWith("s1", "fx_conversion", "oficial:venta");

    expect(await screen.findByText("Could not get a live rate: cannot reach DolarAPI")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "See the preview" })).toBeDisabled();

    await userEvent.type(screen.getByLabelText("Rate typed by you (USD to ARS)"), "1420,5");
    await userEvent.click(screen.getByRole("button", { name: "Use this rate" }));
    expect(api.setManualRate).toHaveBeenCalledWith("s1", "1420,5");

    await userEvent.click(await screen.findByRole("button", { name: "See the preview" }));
    expect(await screen.findByText("1 USD = 1420.5 ARS")).toBeInTheDocument();
    expect(screen.getByText("Typed by you")).toBeInTheDocument();
    expect(screen.getByText("3551.25 ARS")).toBeInTheDocument();
  });

  it("goes straight to the questions step when a new file already needs a rate", async () => {
    const api = fakeApi({ createImport: vi.fn().mockResolvedValue(needsRate) });
    renderWithI18n(<ImportWizard api={api} />);

    await startImport();

    expect(await screen.findByText("Could not get a live rate: cannot reach DolarAPI")).toBeInTheDocument();
  });

  it("refreshes the live rate on request", async () => {
    const live = session({ ...ready, fx: fxState() });
    const api = fakeApi({
      createImport: vi.fn().mockResolvedValue(needsRate),
      refreshRate: vi.fn().mockResolvedValue(live),
    });
    renderWithI18n(<ImportWizard api={api} />);
    await startImport();

    await userEvent.click(await screen.findByRole("button", { name: "Get the live rate again" }));

    expect(api.refreshRate).toHaveBeenCalledWith("s1");
    expect(await screen.findByText("1 USD = 1535 ARS")).toBeInTheDocument();
  });
});
