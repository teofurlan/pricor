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

describe("ColumnsTable completeness", () => {
  const sparse = column({ index: 0, header: "CODIGO", role: null, decided_by: null, empty_rows: 2043, data_rows: 3439 });

  it("says in Spanish how many rows are empty, with thousands separators", () => {
    renderWithI18n(<ColumnsTable columns={[sparse]} issues={[]} busy={false} onConfirm={vi.fn()} />, "es");
    expect(within(screen.getByRole("row", { name: /CODIGO/ })).getByText("Vacía en 2.043 de 3.439 filas")).toBeInTheDocument();
  });

  it("says it in English", () => {
    renderWithI18n(<ColumnsTable columns={[sparse]} issues={[]} busy={false} onConfirm={vi.fn()} />);
    expect(screen.getByText("Empty in 2,043 of 3,439 rows")).toBeInTheDocument();
  });

  it("stays silent below 5% of the rows", () => {
    const nearlyFull = column({ empty_rows: 4, data_rows: 100 });
    renderWithI18n(<ColumnsTable columns={[nearlyFull]} issues={[]} busy={false} onConfirm={vi.fn()} />);
    expect(screen.queryByText(/Empty in/)).not.toBeInTheDocument();
  });
});

describe("ColumnsTable duplicate roles", () => {
  const codigo = column({ index: 0, header: "CODIGO", role: "code" });
  const provider = column({ index: 1, header: "COD_PROV", role: null, decided_by: null, proposals: [{ stage: "heuristics", role: "code", score: 0.9, rationale: "x" }] });

  it("marks both rows when the user assigns a unique role twice", async () => {
    renderWithI18n(<ColumnsTable columns={[codigo, provider]} issues={[]} busy={false} onConfirm={vi.fn()} />, "es");
    expect(screen.queryByText(/Otra columna también es/)).not.toBeInTheDocument();
    await userEvent.click(within(screen.getByRole("row", { name: /COD_PROV/ })).getByRole("button", { name: /Aceptar/ }));
    expect(screen.getAllByText("Otra columna también es Código de producto")).toHaveLength(2);
  });

  it("does not warn about a role that may repeat", () => {
    const a = column({ index: 0, header: "A", role: "ignore" });
    const b = column({ index: 1, header: "B", role: "ignore" });
    renderWithI18n(<ColumnsTable columns={[a, b]} issues={[]} busy={false} onConfirm={vi.fn()} />);
    expect(screen.queryByText(/is also/)).not.toBeInTheDocument();
  });

  it("accept all never creates a duplicate: the colliding suggestion is left for the user", async () => {
    const onConfirm = vi.fn();
    const other = column({ index: 2, header: "DESC", role: null, decided_by: null, proposals: [{ stage: "heuristics", role: "description", score: 0.9, rationale: "x" }] });
    renderWithI18n(<ColumnsTable columns={[codigo, provider, other]} issues={[]} busy={false} onConfirm={onConfirm} />);
    await userEvent.click(screen.getByRole("button", { name: "✓ Accept all suggestions" }));
    expect(screen.queryByText(/Another column is also/)).not.toBeInTheDocument();
    expect(screen.getByText("1 still needs your choice.")).toBeInTheDocument();
    await userEvent.click(within(screen.getByRole("row", { name: /COD_PROV/ })).getByRole("button", { name: /Ignore/ }));
    await userEvent.click(screen.getByRole("button", { name: "Confirm columns" }));
    expect(onConfirm).toHaveBeenCalledWith({ 1: "ignore", 2: "description" });
  });

  it("accept all picks the best-scored of two colliding suggestions", async () => {
    const onConfirm = vi.fn();
    const weak = column({ index: 0, header: "ALFA", role: null, decided_by: null, proposals: [{ stage: "heuristics", role: "code", score: 0.6, rationale: "x" }] });
    const strong = column({ index: 1, header: "BETA", role: null, decided_by: null, proposals: [{ stage: "heuristics", role: "code", score: 0.9, rationale: "x" }] });
    renderWithI18n(<ColumnsTable columns={[weak, strong]} issues={[]} busy={false} onConfirm={onConfirm} />);
    await userEvent.click(screen.getByRole("button", { name: "✓ Accept all suggestions" }));
    await userEvent.click(within(screen.getByRole("row", { name: /ALFA/ })).getByRole("button", { name: /Ignore/ }));
    await userEvent.click(screen.getByRole("button", { name: "Confirm columns" }));
    expect(onConfirm).toHaveBeenCalledWith({ 0: "ignore", 1: "code" });
  });

  it("hides retail_price from the role picker in both English and Spanish", () => {
    const { unmount } = renderWithI18n(<ColumnsTable columns={[column({ index: 0, header: "PVP" })]} issues={[]} busy={false} onConfirm={vi.fn()} />);
    expect(screen.queryByRole("option", { name: /Suggested retail price/ })).not.toBeInTheDocument();
    unmount();

    renderWithI18n(<ColumnsTable columns={[column({ index: 0, header: "PVP" })]} issues={[]} busy={false} onConfirm={vi.fn()} />, "es");
    expect(screen.queryByRole("option", { name: /Precio de venta sugerido/ })).not.toBeInTheDocument();
  });

  it("offers unit_price as an optional role and renders its suggestion in English and Spanish", async () => {
    const onConfirm = vi.fn();
    const prUnit = column({
      index: 0,
      header: "PR. UNIT",
      role: null,
      decided_by: null,
      proposals: [{ stage: "heuristics", role: "unit_price", score: 0.95, rationale: "unit price" }],
    });
    const { unmount } = renderWithI18n(<ColumnsTable columns={[prUnit]} issues={[]} busy={false} onConfirm={onConfirm} />, "es");
    const esRow = screen.getByRole("row", { name: /PR\. UNIT/ });
    expect(within(esRow).getByText("Precio unitario", { selector: ".suggestion__label" })).toBeInTheDocument();
    expect(within(esRow).getByRole("option", { name: /Precio unitario/ })).toBeInTheDocument();
    await userEvent.click(within(esRow).getByRole("button", { name: /Aceptar/ }));
    await userEvent.click(screen.getByRole("button", { name: "Confirmar columnas" }));
    expect(onConfirm).toHaveBeenCalledWith({ 0: "unit_price" });
    unmount();

    renderWithI18n(<ColumnsTable columns={[prUnit]} issues={[]} busy={false} onConfirm={vi.fn()} />);
    const enRow = screen.getByRole("row", { name: /PR\. UNIT/ });
    expect(within(enRow).getByText("Unit price", { selector: ".suggestion__label" })).toBeInTheDocument();
    expect(within(enRow).getByRole("option", { name: /Unit price/ })).toBeInTheDocument();
  });
});
