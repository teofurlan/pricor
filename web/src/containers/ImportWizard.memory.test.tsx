import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ApiError, type ApiClient, type MemoryApiClient } from "../api/client";
import type { Memory, SessionState } from "../api/types";
import { previewPage, question, session } from "../test/fixtures";
import { renderWithI18n } from "../test/render";
import { ImportWizard } from "./ImportWizard";

const memory: Memory = {
  id: "m1",
  text: "Prices include VAT",
  supplier_name: "Acme",
  source: "user_note",
  created_at: "2026-10-18T10:00:00Z",
  updated_at: "2026-10-18T10:00:00Z",
};

function fakeApi(overrides: Partial<ApiClient & MemoryApiClient> = {}): ApiClient & MemoryApiClient {
  const unexpected = (name: string) => () => Promise.reject(new Error(`unexpected call: ${name}`));
  return {
    createImport: vi.fn(unexpected("createImport")), getImport: vi.fn(unexpected("getImport")),
    chooseHeader: vi.fn(unexpected("chooseHeader")), setRoles: vi.fn(unexpected("setRoles")),
    answer: vi.fn(unexpected("answer")), setManualRate: vi.fn(unexpected("setManualRate")),
    refreshRate: vi.fn(unexpected("refreshRate")), preview: vi.fn().mockResolvedValue(previewPage()),
    approve: vi.fn(unexpected("approve")), report: vi.fn(unexpected("report")),
    exportUrl: () => "", rejectedUrl: () => "", reportUrl: () => "",
    listMemories: vi.fn().mockResolvedValue([memory]), createMemoryNote: vi.fn(unexpected("createMemoryNote")),
    rememberSuggestion: vi.fn().mockResolvedValue(memory), editMemory: vi.fn(unexpected("editMemory")),
    deleteMemory: vi.fn(unexpected("deleteMemory")),
    ...overrides,
  };
}

async function startImport() {
  await userEvent.type(screen.getByLabelText("Supplier name"), "Acme");
  await userEvent.upload(screen.getByLabelText("Price list file"), new File(["a,b"], "list.csv"));
  await userEvent.click(screen.getByRole("button", { name: "Start import" }));
  await userEvent.click(await screen.findByRole("button", { name: "Confirm columns" }));
}

const suggested = question({
  suggestion: { suggested_by: "model", option: "USD", confidence: 0.6, calibrated: false, evidence: [], memory_ids: ["m1", "gone"] },
});
const asking = session({ questions: [suggested] });

describe("ImportWizard memory", () => {
  it("loads memories once and displays suggestion citations including deleted ids", async () => {
    const api = fakeApi({ createImport: vi.fn().mockResolvedValue(asking) });
    renderWithI18n(<ImportWizard api={api} />);
    await startImport();
    expect(await screen.findByText("Based on your memory:")).toBeInTheDocument();
    expect(screen.getByText("Prices include VAT")).toBeInTheDocument();
    expect(screen.getByText("a memory that was deleted")).toBeInTheDocument();
    expect(api.listMemories).toHaveBeenCalledTimes(1);
  });

  it("remembers only an accepted model suggestion after the question leaves the server session", async () => {
    const accepted: SessionState = session({ status: "ready_for_preview", answers: { currency: "USD" }, questions: [] });
    const api = fakeApi({ createImport: vi.fn().mockResolvedValue(asking), answer: vi.fn().mockResolvedValue(accepted) });
    renderWithI18n(<ImportWizard api={api} />);
    await startImport();
    await userEvent.click(screen.getByRole("radio", { name: /US dollars/ }));
    await userEvent.click(await screen.findByRole("button", { name: "Remember this" }));
    expect(api.rememberSuggestion).toHaveBeenCalledWith("s1", "currency");
    expect(await screen.findByText("Saved to memory")).toBeInTheDocument();
  });

  it("does not offer Remember this when the user rejected the suggestion", async () => {
    const rejected = session({ status: "ready_for_preview", answers: { currency: "ARS" }, questions: [] });
    const api = fakeApi({ createImport: vi.fn().mockResolvedValue(asking), answer: vi.fn().mockResolvedValue(rejected) });
    renderWithI18n(<ImportWizard api={api} />);
    await startImport();
    await userEvent.click(screen.getByRole("radio", { name: /Argentine pesos/ }));
    expect(await screen.findByRole("radio", { name: /Argentine pesos/ })).toBeChecked();
    expect(screen.queryByRole("button", { name: "Remember this" })).toBeNull();
  });

  it("shows the server message when remembering is rejected", async () => {
    const accepted = session({ status: "ready_for_preview", answers: { currency: "USD" }, questions: [] });
    const api = fakeApi({
      createImport: vi.fn().mockResolvedValue(asking),
      answer: vi.fn().mockResolvedValue(accepted),
      rememberSuggestion: vi.fn().mockRejectedValue(new ApiError(409, "suggestion_not_accepted", "The recorded answer is not the suggestion.")),
    });
    renderWithI18n(<ImportWizard api={api} />);
    await startImport();
    await userEvent.click(screen.getByRole("radio", { name: /US dollars/ }));
    await userEvent.click(await screen.findByRole("button", { name: "Remember this" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The recorded answer is not the suggestion.");
  });
});
