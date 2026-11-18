import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, type MemoryApiClient } from "../api/client";
import type { Memory } from "../api/types";
import { renderWithI18n } from "../test/render";
import { I18nProvider } from "../i18n";
import { MemoryPanelContainer } from "./MemoryPanelContainer";

const memory: Memory = {
  id: "m1",
  text: "Prices include VAT",
  supplier_name: "Acme",
  source: "user_note",
  created_at: "2026-10-18T10:00:00Z",
  updated_at: "2026-10-18T10:00:00Z",
};

function fakeApi(overrides: Partial<MemoryApiClient> = {}): MemoryApiClient {
  return {
    listMemories: vi.fn().mockResolvedValue([memory]),
    createMemoryNote: vi.fn().mockResolvedValue({ ...memory, id: "m2", text: "USD" }),
    rememberSuggestion: vi.fn(),
    editMemory: vi.fn().mockResolvedValue({ ...memory, text: "Prices exclude VAT" }),
    deleteMemory: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  };
}

describe("MemoryPanelContainer", () => {
  afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

  it("opens as a non-modal side panel, closes with Escape and restores the opener's focus", async () => {
    const onClose = vi.fn();
    const api = fakeApi();
    const opener = document.createElement("button");
    document.body.append(opener);
    opener.focus();
    const { rerender } = renderWithI18n(<MemoryPanelContainer api={api} open onClose={onClose} />);
    const panel = await screen.findByRole("complementary", { name: "Saved notes & rules" });
    expect(screen.getByRole("button", { name: "Close notes" })).toHaveFocus();
    fireEvent.keyDown(panel, { key: "Escape" });
    expect(onClose).toHaveBeenCalledOnce();
    rerender(<I18nProvider><MemoryPanelContainer api={api} open={false} onClose={onClose} /></I18nProvider>);
    expect(opener).toHaveFocus();
    opener.remove();
  });
  it("slides out along its entry path before it is removed, and cannot be used meanwhile", () => {
    vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
    vi.useFakeTimers();
    const api = fakeApi();
    const { rerender } = renderWithI18n(<MemoryPanelContainer api={api} open onClose={vi.fn()} />);
    expect(screen.getByRole("complementary", { name: "Saved notes & rules" })).not.toHaveClass("memory-drawer--closing");
    rerender(<MemoryPanelContainer api={api} open={false} onClose={vi.fn()} />);
    const closing = document.querySelector(".memory-drawer");
    expect(closing).toHaveClass("memory-drawer--closing");
    expect(closing).toHaveAttribute("inert");
    act(() => vi.advanceTimersByTime(260));
    expect(document.querySelector(".memory-drawer")).toBeNull();
  });

  it("is removed at once under reduced motion", () => {
    vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
    const api = fakeApi();
    const { rerender } = renderWithI18n(<MemoryPanelContainer api={api} open onClose={vi.fn()} />);
    rerender(<MemoryPanelContainer api={api} open={false} onClose={vi.fn()} />);
    expect(document.querySelector(".memory-drawer")).toBeNull();
  });

  it("loads once and keeps add, edit and delete changes in the list", async () => {
    const api = fakeApi();
    const onMemoriesChange = vi.fn();
    renderWithI18n(<MemoryPanelContainer api={api} open onClose={vi.fn()} onMemoriesChange={onMemoriesChange} />);

    expect(await screen.findByText("Prices include VAT")).toBeInTheDocument();
    expect(api.listMemories).toHaveBeenCalledTimes(1);
    await userEvent.type(screen.getByLabelText("Note"), "USD");
    await userEvent.click(screen.getByRole("button", { name: "Add note" }));
    expect(await screen.findByText("USD")).toBeInTheDocument();

    await userEvent.click(screen.getAllByRole("button", { name: "Edit" })[0]);
    const editor = screen.getByLabelText("Note text");
    await userEvent.clear(editor);
    await userEvent.type(editor, "Prices exclude VAT");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByText("Prices exclude VAT")).toBeInTheDocument();

    await userEvent.click(screen.getAllByRole("button", { name: "Delete" })[0]);
    await userEvent.click(screen.getByRole("button", { name: "Confirm delete" }));
    await waitFor(() => expect(screen.queryByText("Prices exclude VAT")).toBeNull());
    expect(onMemoriesChange).toHaveBeenCalled();
  });

  it("reassures the user in plain language after a 503", async () => {
    const api = fakeApi({
      listMemories: vi.fn().mockRejectedValue(new ApiError(503, "memory_unavailable", "embedder unavailable")),
    });
    renderWithI18n(<MemoryPanelContainer api={api} open onClose={vi.fn()} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Saved notes are temporarily unavailable.");
  });
});
