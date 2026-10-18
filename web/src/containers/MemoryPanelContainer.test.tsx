import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ApiError, type MemoryApiClient } from "../api/client";
import type { Memory } from "../api/types";
import { renderWithI18n } from "../test/render";
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
    const editor = screen.getByLabelText("Memory text");
    await userEvent.clear(editor);
    await userEvent.type(editor, "Prices exclude VAT");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByText("Prices exclude VAT")).toBeInTheDocument();

    vi.spyOn(window, "confirm").mockReturnValue(true);
    await userEvent.click(screen.getAllByRole("button", { name: "Delete" })[0]);
    await waitFor(() => expect(screen.queryByText("Prices exclude VAT")).toBeNull());
    expect(onMemoriesChange).toHaveBeenCalled();
  });

  it("explains how to install the embedding model after a 503", async () => {
    const api = fakeApi({
      listMemories: vi.fn().mockRejectedValue(new ApiError(503, "memory_unavailable", "embedder unavailable")),
    });
    renderWithI18n(<MemoryPanelContainer api={api} open onClose={vi.fn()} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("ollama pull bge-m3");
  });
});
