import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, type ApiClient, type CombinedExportApiClient } from "../api/client";
import { previewPage, session } from "../test/fixtures";
import { renderWithI18n } from "../test/render";
import { ImportWizard } from "./ImportWizard";

const ready = (id: string, supplier: string) => session({ id, supplier_name: supplier, status: "ready_for_preview", answers: { currency: "ARS" } });
const approvedOf = (id: string, supplier: string) => ({ ...ready(id, supplier), status: "approved" as const, approved: true });

function fakeApi(overrides: Partial<ApiClient & CombinedExportApiClient> = {}): ApiClient & CombinedExportApiClient {
  const unexpected = (name: string) => () => Promise.reject(new Error(`unexpected call: ${name}`));
  return {
    createImport: vi.fn(unexpected("createImport")),
    getImport: vi.fn(unexpected("getImport")),
    chooseHeader: vi.fn(unexpected("chooseHeader")),
    setRoles: vi.fn(unexpected("setRoles")),
    answer: vi.fn(unexpected("answer")),
    setManualRate: vi.fn(unexpected("setManualRate")),
    refreshRate: vi.fn(unexpected("refreshRate")),
    preview: vi.fn().mockResolvedValue(previewPage()),
    approve: vi.fn(unexpected("approve")),
    listSheets: vi.fn().mockResolvedValue([]),
    getSample: vi.fn().mockResolvedValue({ header: [], rows: [] }),
    exportSheet: vi.fn().mockResolvedValue({ header: [], rows: [], total: 0 }),
    askQuestion: vi.fn().mockResolvedValue({ reply: "", suggested_option: null }),
    report: vi.fn(() => Promise.reject(new ApiError(409, "no_previous_import", "nothing to compare with"))),
    exportUrl: (id, format) => `/imports/${id}/export?format=${format}`,
    rejectedUrl: (id, format) => `/imports/${id}/rejected?format=${format}`,
    reportUrl: (id) => `/imports/${id}/report/export?format=csv`,
    config: vi.fn().mockResolvedValue({ model_provider: "ollama", demo: false }),
    downloadCombined: vi.fn().mockResolvedValue({ blob: new Blob(["x"]), fileName: "pricor-combined-2-files-products.xlsx" }),
    ...overrides,
  };
}

const files = () => [new File(["a"], "Ferreteria_lista.csv"), new File(["b"], "acme-semana-3.xlsx")];

async function pick(lang: "en" | "es" = "en", list: File[] = files()) {
  const label = lang === "es" ? "Archivo de la lista de precios" : "Price list file";
  await userEvent.upload(screen.getByLabelText(label), list);
}

/** Walks the open file: columns, preview, approval (no output format API in these tests). */
async function reviewAndApprove(lang: "en" | "es" = "en") {
  await userEvent.click(await screen.findByRole("button", { name: lang === "es" ? "Confirmar columnas" : "Confirm columns" }));
  await userEvent.click(await screen.findByRole("button", { name: lang === "es" ? "Continuar a la aprobación" : "Continue to approval" }));
  await userEvent.click(await screen.findByRole("button", { name: lang === "es" ? "Firmar" : "Approve import" }));
}

describe("ImportWizard with several files", () => {
  beforeEach(() => {
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: vi.fn(() => "blob:x"), revokeObjectURL: vi.fn() }));
  });
  afterEach(() => vi.unstubAllGlobals());

  it("builds a queue with supplier names from the file stems and keeps them editable", async () => {
    const api = fakeApi();
    renderWithI18n(<ImportWizard api={api} />);
    await pick();

    const first = screen.getByLabelText("Supplier for Ferreteria_lista.csv");
    const second = screen.getByLabelText("Supplier for acme-semana-3.xlsx");
    expect(first).toHaveValue("Ferreteria");
    expect(second).toHaveValue("acme");
    await userEvent.clear(first);
    await userEvent.type(first, "Ferretería Sur");
    expect(first).toHaveValue("Ferretería Sur");
    expect(api.createImport).not.toHaveBeenCalled();
  });

  it("lets the user choose the sheet of a multi-sheet file", async () => {
    const listSheets = vi.fn((file: File) => Promise.resolve(file.name.startsWith("acme") ? ["Hoja1", "Precios"] : ["Hoja1"]));
    const createImport = vi.fn().mockResolvedValue(ready("s1", "acme"));
    renderWithI18n(<ImportWizard api={fakeApi({ listSheets, createImport })} />);
    await pick("en", [new File(["b"], "acme-semana-3.xlsx"), new File(["a"], "Ferreteria_lista.csv")]);

    const select = await screen.findByLabelText("Sheet for acme-semana-3.xlsx");
    expect(screen.queryByLabelText("Sheet for Ferreteria_lista.csv")).toBeNull();
    await userEvent.selectOptions(select, "Precios");
    await userEvent.click(screen.getByRole("button", { name: "Start" }));
    await waitFor(() => expect(createImport).toHaveBeenCalledTimes(1));
    expect(createImport.mock.calls[0][0]).toMatchObject({ supplierName: "acme", sheet: "Precios" });
  });

  it("starts with the first file, offers the next after approving and ends with the unified downloads", async () => {
    const createImport = vi.fn()
      .mockResolvedValueOnce(ready("s1", "Ferreteria"))
      .mockResolvedValueOnce(ready("s2", "acme"));
    const approve = vi.fn()
      .mockResolvedValueOnce(approvedOf("s1", "Ferreteria"))
      .mockResolvedValueOnce(approvedOf("s2", "acme"));
    const api = fakeApi({ createImport, approve });
    renderWithI18n(<ImportWizard api={api} />);
    await pick();
    await userEvent.click(screen.getByRole("button", { name: "Start" }));

    await waitFor(() => expect(createImport).toHaveBeenCalledTimes(1));
    expect(createImport.mock.calls[0][0]).toMatchObject({ supplierName: "Ferreteria" });
    const tray = screen.getByRole("list", { name: "Files" });
    expect(within(tray).getByText(/Ferreteria_lista/).closest("li")).toHaveTextContent("Reviewing");
    expect(within(tray).getByText(/acme-semana/).closest("li")).toHaveTextContent("Waiting");

    await reviewAndApprove();
    await waitFor(() =>
      expect(within(screen.getByRole("list", { name: "Files" })).getByText(/Ferreteria_lista/).closest("li")).toHaveTextContent("Approved"));
    await userEvent.click(await screen.findByRole("button", { name: "Review the next file (2 of 2)" }));
    await waitFor(() => expect(createImport).toHaveBeenCalledTimes(2));
    expect(createImport.mock.calls[1][0]).toMatchObject({ supplierName: "acme" });

    await reviewAndApprove();
    await userEvent.click(await screen.findByRole("button", { name: "See the summary" }));
    expect(screen.getByText(/2 of 2 files approved/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Download the combined file" }));
    await waitFor(() => expect(api.downloadCombined).toHaveBeenCalledWith(["s1", "s2"], "xlsx", "products"));
    await userEvent.click(screen.getByRole("button", { name: "Download the combined file (CSV)" }));
    await waitFor(() => expect(api.downloadCombined).toHaveBeenCalledWith(["s1", "s2"], "csv", "products"));
    await userEvent.click(screen.getByRole("button", { name: "Download the combined rejected rows" }));
    await waitFor(() => expect(api.downloadCombined).toHaveBeenCalledWith(["s1", "s2"], "xlsx", "rejected"));
    await userEvent.click(screen.getByRole("button", { name: "Download the combined rejected rows (CSV)" }));
    await waitFor(() => expect(api.downloadCombined).toHaveBeenLastCalledWith(["s1", "s2"], "csv", "rejected"));
  }, 30000);

  it("marks a file that fails to read and moves on to the next one", async () => {
    const createImport = vi.fn()
      .mockRejectedValueOnce(new ApiError(422, "unreadable_file", "the file is damaged"))
      .mockResolvedValueOnce(ready("s2", "acme"));
    renderWithI18n(<ImportWizard api={fakeApi({ createImport })} />);
    await pick();
    await userEvent.click(screen.getByRole("button", { name: "Start" }));

    await waitFor(() => expect(createImport).toHaveBeenCalledTimes(2));
    const tray = screen.getByRole("list", { name: "Files" });
    const failed = within(tray).getByText(/Ferreteria_lista/).closest("li");
    expect(failed).toHaveTextContent("Failed");
    expect(failed).toHaveTextContent("the file is damaged");
    expect(await screen.findByRole("button", { name: "Confirm columns" })).toBeInTheDocument();
  });

  it("skips the file under review and shows the summary when nothing is left", async () => {
    const createImport = vi.fn().mockResolvedValueOnce(ready("s1", "Ferreteria")).mockResolvedValueOnce(ready("s2", "acme"));
    renderWithI18n(<ImportWizard api={fakeApi({ createImport })} />);
    await pick();
    await userEvent.click(screen.getByRole("button", { name: "Start" }));
    await screen.findByRole("button", { name: "Confirm columns" });

    await userEvent.click(screen.getByRole("button", { name: "Skip" }));
    await waitFor(() => expect(createImport).toHaveBeenCalledTimes(2));
    await waitFor(() =>
      expect(within(screen.getByRole("list", { name: "Files" })).getByText(/Ferreteria_lista/).closest("li")).toHaveTextContent("Skipped"));
    await userEvent.click(await screen.findByRole("button", { name: "Skip" }));

    expect(await screen.findByText(/0 of 2 files approved/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Download the combined file" })).toBeNull();
  });

  it("speaks Spanish with usted", async () => {
    const createImport = vi.fn().mockResolvedValueOnce(ready("s1", "Ferreteria")).mockResolvedValueOnce(ready("s2", "acme"));
    const approve = vi.fn().mockResolvedValueOnce(approvedOf("s1", "Ferreteria")).mockResolvedValueOnce(approvedOf("s2", "acme"));
    renderWithI18n(<ImportWizard api={fakeApi({ createImport, approve })} />, "es");
    await pick("es");
    expect(screen.getByLabelText("Proveedor de Ferreteria_lista.csv")).toHaveValue("Ferreteria");
    await userEvent.click(screen.getByRole("button", { name: "Empezar" }));
    await reviewAndApprove("es");
    await userEvent.click(await screen.findByRole("button", { name: "Revisar el siguiente archivo (2 de 2)" }));
    await reviewAndApprove("es");
    await userEvent.click(await screen.findByRole("button", { name: "Ver el resumen" }));
    expect(screen.getByRole("button", { name: "Descargar archivo unificado" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Descargar rechazados unificados" })).toBeInTheDocument();
  });

  it("keeps the one-file flow as it was", async () => {
    const createImport = vi.fn().mockResolvedValue(ready("s1", "Ferreteria Ejemplo"));
    renderWithI18n(<ImportWizard api={fakeApi({ createImport })} />);
    await userEvent.type(screen.getByLabelText("Supplier name"), "Ferreteria Ejemplo");
    await userEvent.upload(screen.getByLabelText("Price list file"), new File(["a"], "lista.csv"));
    await userEvent.click(screen.getByRole("button", { name: "Start import" }));
    await screen.findByRole("button", { name: "Confirm columns" });
    expect(screen.queryByRole("list", { name: "Files" })).toBeNull();
  });
});
