import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { column } from "../../test/fixtures";
import { renderWithI18n } from "../../test/render";
import { ColumnsTable } from "./ColumnsTable";

const quantityDiscount = column({
  index: 1,
  header: "DTO_X_CANT",
  role: null,
  decided_by: null,
  score: 0.9,
  rationale: "quantity discount: english text from the server",
  samples: ["10% x 10 UN"],
  quantity_discount: true,
  proposals: [{ stage: "heuristics", role: "ignore", score: 0.9, rationale: "quantity discount" }],
});

describe("ColumnsTable quantity discounts", () => {
  it("explains in Spanish why the column is not applied and suggests ignoring it", () => {
    renderWithI18n(<ColumnsTable columns={[quantityDiscount]} issues={[]} busy={false} onConfirm={vi.fn()} />, "es");
    const row = screen.getByRole("row", { name: /DTO_X_CANT/ });
    expect(
      within(row).getByText("Descuento por cantidad: depende de cuánto se compre, no se aplica al costo unitario"),
    ).toBeInTheDocument();
    expect(within(row).getByText("Falta su confirmación")).toBeInTheDocument();
  });

  it("explains it in English and accepting the suggestion assigns ignore", async () => {
    const onConfirm = vi.fn();
    renderWithI18n(<ColumnsTable columns={[quantityDiscount]} issues={[]} busy={false} onConfirm={onConfirm} />);
    const row = screen.getByRole("row", { name: /DTO_X_CANT/ });
    expect(
      within(row).getByText("Quantity discount: it depends on how much is bought, so it is not applied to the unit cost"),
    ).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "✓ Accept all suggestions" }));
    await userEvent.click(screen.getByRole("button", { name: "Confirm columns" }));
    expect(onConfirm).toHaveBeenCalledWith({ 1: "ignore" });
  });

  it("shows no such note on an ordinary column", () => {
    renderWithI18n(<ColumnsTable columns={[column()]} issues={[]} busy={false} onConfirm={vi.fn()} />);
    expect(screen.queryByText(/Quantity discount/)).not.toBeInTheDocument();
  });
});
