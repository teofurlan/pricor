import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { previewItem, previewPage } from "../../test/fixtures";
import { renderWithI18n } from "../../test/render";
import { PreviewTable } from "./PreviewTable";

const page = () => previewPage({
  items: [
    previewItem({ row_number: 3 }),
    previewItem({ row_number: 4, record: { supplier_code: "B2", description: "Tuerca", unit_cost_net: "50.00", currency: "ARS" } }),
  ],
});

describe("PreviewTable calculation tape", () => {
  it("says in plain words that a row can be clicked or tapped for its step-by-step calculation", () => {
    renderWithI18n(<PreviewTable page={page()} busy={false} onPage={vi.fn()} />);
    expect(screen.getByText(/Click or tap a row to see its step-by-step calculation/)).toBeVisible();
  });

  it("says it in Spanish with usted", () => {
    renderWithI18n(<PreviewTable page={page()} busy={false} onPage={vi.fn()} />, "es");
    expect(screen.getByText(/Haga clic o toque una fila para ver el cálculo paso a paso/)).toBeVisible();
  });

  it("opens the first row on its own and follows the row the user picks", async () => {
    renderWithI18n(<PreviewTable page={page()} busy={false} onPage={vi.fn()} />);
    const tape = screen.getByRole("region", { name: "From file to cost" });
    expect(screen.getByRole("button", { name: "Row 3" })).toHaveAttribute("aria-pressed", "true");
    expect(within(tape).getByText("Tornillo")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Row 4" }));
    expect(within(tape).getByText("Tuerca")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Row 3" })).toHaveAttribute("aria-pressed", "false");
  });
});
