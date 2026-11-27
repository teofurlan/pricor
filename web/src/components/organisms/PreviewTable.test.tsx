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
  it("says in plain words that a row can be clicked to inspect its step-by-step calculation", () => {
    renderWithI18n(<PreviewTable page={page()} busy={false} onPage={vi.fn()} />);
    expect(screen.getByText(/Click a row to inspect its step-by-step calculation/)).toBeVisible();
  });

  it("says it in Spanish with usted", () => {
    renderWithI18n(<PreviewTable page={page()} busy={false} onPage={vi.fn()} />, "es");
    expect(screen.getByText(/Haga clic en una fila para ver el detalle del cálculo/)).toBeVisible();
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

describe("PreviewTable search and status filters", () => {
  it("forwards search submission and status filter clicks, and offers Clear filters on empty matches", async () => {
    const onFilter = vi.fn();
    const { rerender } = renderWithI18n(
      <PreviewTable
        page={page()}
        busy={false}
        onPage={vi.fn()}
        filter={{ query: "", status: "all" }}
        onFilter={onFilter}
      />,
      "es",
    );

    const search = screen.getByRole("searchbox", { name: "Buscar filas por código o descripción" });
    await userEvent.type(search, "tuerca{enter}");
    expect(onFilter).toHaveBeenCalledWith({ query: "tuerca", status: "all" });

    await userEvent.click(screen.getByRole("button", { name: "Rechazadas" }));
    expect(onFilter).toHaveBeenLastCalledWith({ query: "tuerca", status: "rejected" });

    rerender(
      <PreviewTable
        page={previewPage({ items: [], total_items: 0 })}
        busy={false}
        onPage={vi.fn()}
        filter={{ query: "tuerca", status: "rejected" }}
        onFilter={onFilter}
      />,
    );
    expect(screen.getByText("Ninguna fila coincide con ese filtro.")).toBeInTheDocument();
    await userEvent.click(screen.getAllByRole("button", { name: "Limpiar filtros" })[0]);
    expect(onFilter).toHaveBeenLastCalledWith({ query: "", status: "all" });
  });
});

describe("PreviewTable contextual error preview and resolution", () => {
  const rejectedReason = "PRECIO: empty value, expected a number";
  const rejectedPage = () =>
    previewPage({
      items: [
        previewItem({
          row_number: 2,
          status: "rejected",
          original: ["", "GRUPO DE PRODUCTOS 01", ""],
          trace: [],
          record: null,
          reasons: [rejectedReason],
        }),
      ],
      total_items: 1,
      totals: {
        data_rows: 10,
        accepted: 7,
        rejected: 3,
        rejected_rows: [
          { row_number: 2, reasons: [rejectedReason] },
          { row_number: 11, reasons: [rejectedReason] },
          { row_number: 48, reasons: [rejectedReason] },
        ],
        reason_counts: { [rejectedReason]: 3 },
        skipped_rows: { empty: 0, total: 0, section: 0, preamble: 0 },
      },
    });

  const sampleContext = {
    row_number: 2,
    headers: ["CODIGO", "DESCRIPCION", "PRECIO"],
    target_columns: [2],
    rows: [
      { row_number: 1, row_class: "preamble", cells: ["CODIGO", "DESCRIPCION", "PRECIO"], is_target: false, ignored: false },
      { row_number: 2, row_class: "data", cells: ["", "GRUPO DE PRODUCTOS 01", ""], is_target: true, ignored: false },
      { row_number: 3, row_class: "data", cells: ["A-1", "Tornillo", "1210.00"], is_target: false, ignored: false },
    ],
  };

  it("loads the ±2-row file context and triggers batch ignore or cell edit", async () => {
    const onLoadRowContext = vi.fn().mockResolvedValue(sampleContext);
    const onResolveRows = vi.fn().mockResolvedValue({
      affected: 3,
      ignored_count: 3,
      override_count: 0,
      totals: rejectedPage().totals,
    });

    renderWithI18n(
      <PreviewTable
        page={rejectedPage()}
        busy={false}
        onPage={vi.fn()}
        onLoadRowContext={onLoadRowContext}
        onResolveRows={onResolveRows}
      />,
      "es",
    );

    expect(onLoadRowContext).toHaveBeenCalledWith(2);
    const ctxRegion = await screen.findByRole("region", { name: "Vista del archivo (±2 filas)" });
    expect(within(ctxRegion).getByText("GRUPO DE PRODUCTOS 01")).toBeInTheDocument();
    expect(within(ctxRegion).getByText("Tornillo")).toBeInTheDocument();
    expect(screen.getByText("Este error aparece en 3 filas.")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Ignorar las 3 filas con este error" }));
    expect(onResolveRows).toHaveBeenCalledWith({
      action: "ignore_by_reason",
      reason: rejectedReason,
    });

    const input = screen.getByLabelText("Corregir «PRECIO»");
    await userEvent.type(input, "500,00");
    await userEvent.click(screen.getByRole("button", { name: "Aplicar en esta fila" }));
    expect(onResolveRows).toHaveBeenCalledWith({
      action: "edit_cell",
      row_number: 2,
      column_index: 2,
      value: "500,00",
    });
  });

  it("hides resolution actions when readOnly is true", async () => {
    const onLoadRowContext = vi.fn().mockResolvedValue(sampleContext);
    renderWithI18n(
      <PreviewTable
        page={rejectedPage()}
        busy={false}
        onPage={vi.fn()}
        readOnly
        onLoadRowContext={onLoadRowContext}
        onResolveRows={vi.fn()}
      />,
      "es",
    );

    await screen.findByRole("region", { name: "Vista del archivo (±2 filas)" });
    expect(screen.queryByRole("button", { name: /Ignorar/ })).toBeNull();
    expect(screen.queryByLabelText(/Corregir/)).toBeNull();
  });
});
