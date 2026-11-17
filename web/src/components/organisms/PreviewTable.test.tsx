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

describe("PreviewTable Argentine numbers", () => {
  const big = () => previewPage({
    items: [previewItem({ row_number: 3, record: { supplier_code: "A1", description: "Cable", unit_cost_net: "3387.84", currency: "ARS" } })],
    total_items: 1234,
  });

  it("writes costs, the tape and the pager with dots for thousands and commas for decimals in Spanish", () => {
    renderWithI18n(<PreviewTable page={big()} busy={false} onPage={vi.fn()} />, "es");
    const table = screen.getByRole("table");
    expect(within(table).getByText("3.387,84")).toBeInTheDocument();
    expect(within(table).queryByText("3387.84")).not.toBeInTheDocument();
    expect(screen.getByText(/de 1\.234/)).toBeInTheDocument();
  });

  it("keeps the same grouping logic in English", () => {
    renderWithI18n(<PreviewTable page={big()} busy={false} onPage={vi.fn()} />, "en");
    expect(within(screen.getByRole("table")).getByText("3,387.84")).toBeInTheDocument();
  });

  it("labels the column and tape total 'Costo sin IVA' when VAT was stripped, and 'Costo unitario' when kept", async () => {
    const withVatStripped = previewPage({
      items: [previewItem({
        row_number: 3,
        trace: [
          { step: "original", value: "1210.00" },
          { step: "strip_vat", value: "1000.00" },
          { step: "rounding", value: "1000.00" },
        ],
        record: { supplier_code: "A1", description: "Cable", unit_cost_net: "1000.00", currency: "ARS" },
      })],
    });
    const { rerender } = renderWithI18n(<PreviewTable page={withVatStripped} busy={false} onPage={vi.fn()} />, "es");
    expect(within(screen.getByRole("table")).getByRole("columnheader", { name: "Costo sin IVA" })).toBeInTheDocument();
    expect(await within(screen.getByRole("region", { name: "Del archivo al costo" })).findByText("Costo sin IVA")).toBeInTheDocument();

    const withoutVatStripped = previewPage({
      items: [previewItem({
        row_number: 3,
        trace: [
          { step: "original", value: "1210.00" },
          { step: "strip_vat", value: "1210.00" },
          { step: "rounding", value: "1210.00" },
        ],
        record: { supplier_code: "A1", description: "Cable", unit_cost_net: "1210.00", currency: "ARS" },
      })],
    });
    rerender(<PreviewTable page={withoutVatStripped} busy={false} onPage={vi.fn()} />);
    expect(within(screen.getByRole("table")).getByRole("columnheader", { name: "Costo unitario" })).toBeInTheDocument();
    expect(await within(screen.getByRole("region", { name: "Del archivo al costo" })).findByText("Costo unitario")).toBeInTheDocument();
  });
});
