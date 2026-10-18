import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { Memory } from "../../api/types";
import { renderWithI18n } from "../../test/render";
import { MemoryPanel } from "./MemoryPanel";

const memories: Memory[] = [
  {
    id: "m1",
    text: "Prices include VAT",
    supplier_name: "Acme",
    source: "user_note",
    created_at: "2026-10-18T10:00:00Z",
    updated_at: "2026-10-18T10:00:00Z",
  },
  {
    id: "m2",
    text: "Use 12 units per pack",
    supplier_name: null,
    source: "accepted_suggestion",
    created_at: "2026-10-17T10:00:00Z",
    updated_at: "2026-10-17T10:00:00Z",
  },
];

function renderPanel(overrides: Partial<React.ComponentProps<typeof MemoryPanel>> = {}) {
  const props: React.ComponentProps<typeof MemoryPanel> = {
    memories,
    loading: false,
    busy: false,
    onAdd: vi.fn(),
    onEdit: vi.fn(),
    onDelete: vi.fn(),
    ...overrides,
  };
  renderWithI18n(<MemoryPanel {...props} />);
  return props;
}

describe("MemoryPanel", () => {
  it("lists text, supplier, source and date", () => {
    renderPanel();
    const first = screen.getByRole("article", { name: /Prices include VAT/ });
    expect(within(first).getByText("Acme")).toBeInTheDocument();
    expect(within(first).getByText("Your note")).toBeInTheDocument();
    expect(within(first).getByText(/Oct 18, 2026/)).toBeInTheDocument();
    expect(screen.getByText("Accepted suggestion")).toBeInTheDocument();
  });

  it("submits a note with an optional supplier", async () => {
    const props = renderPanel({ memories: [] });
    await userEvent.type(screen.getByLabelText("Note"), "Currency is always USD");
    await userEvent.type(screen.getByLabelText("Supplier (optional)"), "Acme");
    await userEvent.click(screen.getByRole("button", { name: "Add note" }));
    expect(props.onAdd).toHaveBeenCalledWith("Currency is always USD", "Acme");
  });

  it("edits a memory in place", async () => {
    const props = renderPanel();
    const first = screen.getByRole("article", { name: /Prices include VAT/ });
    await userEvent.click(within(first).getByRole("button", { name: "Edit" }));
    const editor = within(first).getByLabelText("Memory text");
    await userEvent.clear(editor);
    await userEvent.type(editor, "Prices exclude VAT");
    await userEvent.click(within(first).getByRole("button", { name: "Save changes" }));
    expect(props.onEdit).toHaveBeenCalledWith("m1", "Prices exclude VAT");
  });

  it("asks for confirmation before deleting", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    const props = renderPanel();
    const first = screen.getByRole("article", { name: /Prices include VAT/ });
    await userEvent.click(within(first).getByRole("button", { name: "Delete" }));
    expect(confirm).toHaveBeenCalledWith("Delete this memory? This cannot be undone.");
    expect(props.onDelete).toHaveBeenCalledWith("m1");
    confirm.mockRestore();
  });

  it("shows an inviting empty state", () => {
    renderPanel({ memories: [] });
    expect(screen.getByText("No memories yet. Add a note to help Gemma with future lists.")).toBeInTheDocument();
  });
});
