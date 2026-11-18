import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, type ApiClient, type CombinedExportApiClient, type EventsApiClient } from "../api/client";
import { previewPage, session } from "../test/fixtures";
import { renderWithI18n } from "../test/render";
import { ImportWizard } from "./ImportWizard";

const ready = (id: string) => session({ id, supplier_name: "Ferreteria", status: "ready_for_preview", answers: { currency: "ARS" } });
const approvedOf = (id: string) => ({ ...ready(id), status: "approved" as const, approved: true });

type Api = ApiClient & CombinedExportApiClient & EventsApiClient;

function fakeApi(overrides: Partial<Api> = {}): Api {
  const unexpected = (name: string) => () => Promise.reject(new Error(`unexpected call: ${name}`));
  return {
    createImport: vi.fn().mockResolvedValue(ready("s1")),
    getImport: vi.fn(unexpected("getImport")),
    chooseHeader: vi.fn(unexpected("chooseHeader")),
    setRoles: vi.fn(unexpected("setRoles")),
    answer: vi.fn(unexpected("answer")),
    setManualRate: vi.fn(unexpected("setManualRate")),
    refreshRate: vi.fn(unexpected("refreshRate")),
    preview: vi.fn().mockResolvedValue(previewPage()),
    approve: vi.fn().mockResolvedValue(approvedOf("s1")),
    listSheets: vi.fn().mockResolvedValue([]),
    getSample: vi.fn().mockResolvedValue({ header: [], rows: [] }),
    exportSheet: vi.fn().mockResolvedValue({ header: [], rows: [], total: 0 }),
    askQuestion: vi.fn().mockResolvedValue({ reply: "", suggested_option: null }),
    report: vi.fn(() => Promise.reject(new ApiError(409, "no_previous_import", "nothing to compare with"))),
    exportUrl: (id, format) => `/imports/${id}/export?format=${format}`,
    rejectedUrl: (id, format) => `/imports/${id}/rejected?format=${format}`,
    reportUrl: (id) => `/imports/${id}/report/export?format=csv`,
    config: vi.fn().mockResolvedValue({ model_provider: "ollama", demo: false }),
    downloadCombined: vi.fn().mockResolvedValue({ blob: new Blob(["x"]), fileName: "x.xlsx" }),
    recordEvent: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  };
}

const sent = (api: Api) => (api.recordEvent as ReturnType<typeof vi.fn>).mock.calls;

// One file today asks for the supplier by hand; the form may fill it in. Either way "Start…" begins.
async function startWith(files: File[]) {
  await userEvent.upload(screen.getByLabelText("Price list file"), files);
  await userEvent.click(screen.getByRole("button", { name: /^Start/ }));
}
const pickAndStart = () => startWith([new File(["a"], "Ferreteria_lista.csv")]);

async function reviewAndApprove() {
  await userEvent.click(await screen.findByRole("button", { name: "Confirm columns" }));
  await userEvent.click(await screen.findByRole("button", { name: "Continue to approval" }));
  await userEvent.click(await screen.findByRole("button", { name: "Approve and generate file" }));
}

beforeEach(() => {
  vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: vi.fn(() => "blob:x"), revokeObjectURL: vi.fn() }));
});

afterEach(() => {
  vi.unstubAllGlobals();
  window.sessionStorage.clear();
  window.history.replaceState(null, "", "/");
});

describe("the group funnel record (S10)", () => {
  it("stores g, removes it from the URL and sends visit once with the group", async () => {
    window.history.replaceState(null, "", "/?g=grupo-7");
    const api = fakeApi();
    const view = renderWithI18n(<ImportWizard api={api} />);

    await waitFor(() => expect(sent(api)).toEqual([["visit", "grupo-7"]]));
    expect(window.location.search).toBe("");
    expect(window.sessionStorage.getItem("pricor_group")).toBe("grupo-7");
    view.rerender(<ImportWizard api={api} />);
    expect(sent(api)).toHaveLength(1);
  });

  it("sends visit with null when the link has no group", async () => {
    const api = fakeApi();
    renderWithI18n(<ImportWizard api={api} />);

    await waitFor(() => expect(sent(api)).toEqual([["visit", null]]));
  });

  it("sends import_started, approved and downloaded with the group", async () => {
    window.history.replaceState(null, "", "/?g=grupo-7");
    const api = fakeApi();
    renderWithI18n(<ImportWizard api={api} />);
    await pickAndStart();
    await waitFor(() => expect(sent(api)).toContainEqual(["import_started", "grupo-7"]));
    await reviewAndApprove();
    await waitFor(() => expect(sent(api)).toContainEqual(["approved", "grupo-7"]));

    await userEvent.click(await screen.findByRole("link", { name: "Products (XLSX)" }));
    expect(sent(api).map(([event]) => event)).toEqual(["visit", "import_started", "approved", "downloaded"]);
    expect(sent(api).every(([, group]) => group === "grupo-7")).toBe(true);
  });

  it("does not count a rejected-rows download", async () => {
    const api = fakeApi();
    renderWithI18n(<ImportWizard api={api} />);
    await pickAndStart();
    await reviewAndApprove();
    await userEvent.click(await screen.findByRole("link", { name: "Rejected rows (XLSX)" }));

    expect(sent(api).map(([event]) => event)).not.toContain("downloaded");
  });

  it("failures of /events never show an error or block the flow", async () => {
    const api = fakeApi({ recordEvent: vi.fn().mockRejectedValue(new ApiError(500, "internal_error", "boom")) });
    renderWithI18n(<ImportWizard api={api} />);
    await pickAndStart();
    await reviewAndApprove();

    expect(await screen.findByRole("link", { name: "Products (XLSX)" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(sent(api).length).toBeGreaterThanOrEqual(3);
  });

  it("works when the client has no recordEvent at all", async () => {
    const api = fakeApi();
    delete (api as Partial<Api>).recordEvent;
    renderWithI18n(<ImportWizard api={api} />);
    await pickAndStart();
    await waitFor(() => expect(api.createImport).toHaveBeenCalled());
  });

  it("sends downloaded after a combined products download only", async () => {
    const api = fakeApi({
      createImport: vi.fn().mockResolvedValueOnce(ready("s1")).mockResolvedValueOnce(ready("s2")),
      approve: vi.fn().mockResolvedValueOnce(approvedOf("s1")).mockResolvedValueOnce(approvedOf("s2")),
    });
    renderWithI18n(<ImportWizard api={api} />);
    await startWith([new File(["a"], "Ferreteria_lista.csv"), new File(["b"], "acme-semana-3.xlsx")]);
    await reviewAndApprove();
    await userEvent.click(await screen.findByRole("button", { name: "Review the next file (2 of 2)" }));
    await reviewAndApprove();
    await userEvent.click(await screen.findByRole("button", { name: "See the summary" }));
    await userEvent.click(screen.getByRole("button", { name: "Download the combined rejected rows" }));
    await waitFor(() => expect(api.downloadCombined).toHaveBeenCalledTimes(1));
    expect(sent(api).map(([event]) => event)).not.toContain("downloaded");

    await userEvent.click(screen.getByRole("button", { name: "Download the combined file" }));
    await waitFor(() => expect(sent(api).map(([event]) => event)).toContain("downloaded"));
    expect(sent(api).filter(([event]) => event === "import_started")).toHaveLength(2);
  }, 30000);
});
