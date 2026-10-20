import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { OutputFormat } from "../../api/types";
import { renderWithI18n } from "../../test/render";
import { OutputFormatPanel } from "./OutputFormatPanel";

const fields = ["supplier_code", "description", "unit_cost_net", "currency", "source_row"];

function format(overrides: Partial<OutputFormat> = {}): OutputFormat {
  return {
    name: "mi-sistema.xlsx",
    state: "proposed",
    fields,
    columns: [
      { index: 0, name: "Código", samples: ["A1", "B2"], proposal: { source: "field:supplier_code", proposed_by: "gemma", confidence: 0.92 }, source: null },
      { index: 1, name: "Stock", samples: ["4"], proposal: { source: "empty", proposed_by: "heuristics", confidence: 0.5 }, source: null },
      { index: 2, name: "Moneda", samples: [], proposal: { source: "constant:ARS", proposed_by: "gemma", confidence: 0.7 }, source: null },
    ],
    ...overrides,
  };
}

const confirmed = () => format({
  state: "confirmed",
  columns: format().columns.map((column) => ({ ...column, source: column.proposal.source })),
});

function renderPanel(overrides: Partial<React.ComponentProps<typeof OutputFormatPanel>> = {}) {
  const props: React.ComponentProps<typeof OutputFormatPanel> = {
    format: null,
    loading: false,
    busy: false,
    error: null,
    fields,
    onUpload: vi.fn(),
    onSave: vi.fn(),
    onRemove: vi.fn(),
    ...overrides,
  };
  renderWithI18n(<OutputFormatPanel {...props} />);
  return props;
}

const rows = () => screen.getAllByRole("listitem");

describe("OutputFormatPanel", () => {
  it("explains the standard format and uploads a template file", async () => {
    const props = renderPanel();
    expect(screen.getByText(/Pricor's standard columns/)).toBeInTheDocument();
    const file = new File(["Código,Stock\n"], "mi-sistema.csv");
    await userEvent.upload(screen.getByLabelText("Template file"), file);
    await userEvent.click(screen.getByRole("button", { name: "Read the template" }));
    expect(props.onUpload).toHaveBeenCalledWith(file);
  });

  it("adds columns by hand and saves exactly those, in that order", async () => {
    const props = renderPanel();
    await userEvent.click(screen.getByRole("button", { name: "Add column" }));
    await userEvent.type(screen.getByRole("textbox", { name: "Name of column 1" }), "SKU");
    await userEvent.click(screen.getByRole("button", { name: "Add column" }));
    await userEvent.type(screen.getByRole("textbox", { name: "Name of column 2" }), "Rubro");
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Source for Rubro" }), "constant");
    await userEvent.type(screen.getByRole("textbox", { name: "Fixed value for Rubro" }), "Ferretería");
    expect(screen.getByText("Only these columns will be in the products file, in this order.")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Use these columns" }));
    expect(props.onSave).toHaveBeenCalledWith([
      { name: "SKU", source: "field:supplier_code", template_index: null },
      { name: "Rubro", source: "constant:Ferretería", template_index: null },
    ]);
  });

  it("shows each template column with its samples and proposal, applied only on save", async () => {
    const props = renderPanel({ format: format() });
    expect(rows()).toHaveLength(3);
    expect(within(rows()[0]).getByRole("textbox", { name: "Name of column 1" })).toHaveValue("Código");
    expect(within(rows()[0]).getByText("A1, B2")).toBeInTheDocument();
    expect(within(rows()[0]).getByText("Gemma 92%")).toBeInTheDocument();
    expect(within(rows()[1]).getByText("Rule")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Source for Código" })).toHaveValue("field:supplier_code");
    expect(screen.getByRole("combobox", { name: "Source for Stock" })).toHaveValue("empty");
    expect(screen.getByRole("textbox", { name: "Fixed value for Moneda" })).toHaveValue("ARS");
    expect(screen.getByText("Not in use yet: save to use these columns.")).toBeInTheDocument();
    expect(props.onSave).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: "Use these columns" }));
    expect(props.onSave).toHaveBeenCalledWith([
      { name: "Código", source: "field:supplier_code", template_index: 0 },
      { name: "Stock", source: "empty", template_index: 1 },
      { name: "Moneda", source: "constant:ARS", template_index: 2 },
    ]);
  });

  it("renames, reorders, removes and adds columns on top of a template", async () => {
    const props = renderPanel({ format: confirmed() });
    expect(screen.getByRole("button", { name: "Use these columns" })).toBeDisabled(); // nothing changed yet
    const name = screen.getByRole("textbox", { name: "Name of column 2" });
    await userEvent.clear(name);
    await userEvent.type(name, "Existencia");
    await userEvent.click(screen.getByRole("button", { name: "Move Existencia up" }));
    await userEvent.click(screen.getByRole("button", { name: "Remove Moneda" }));
    await userEvent.click(screen.getByRole("button", { name: "Add column" }));
    await userEvent.type(screen.getByRole("textbox", { name: "Name of column 3" }), "Costo");
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Source for Costo" }), "field:unit_cost_net");
    expect(screen.getByText("Not in use yet: save to use these columns.")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Use these columns" }));
    expect(props.onSave).toHaveBeenCalledWith([
      { name: "Existencia", source: "empty", template_index: 1 },
      { name: "Código", source: "field:supplier_code", template_index: 0 },
      { name: "Costo", source: "field:unit_cost_net", template_index: null },
    ]);
  });

  it("says what is missing and blocks saving until every column is valid", async () => {
    renderPanel();
    await userEvent.click(screen.getByRole("button", { name: "Add column" }));
    await userEvent.click(screen.getByRole("button", { name: "Add column" }));
    expect(screen.getByRole("button", { name: "Use these columns" })).toBeDisabled();
    expect(screen.getAllByText("Give this column a name.")).toHaveLength(2);
    await userEvent.type(screen.getByRole("textbox", { name: "Name of column 1" }), "SKU");
    await userEvent.type(screen.getByRole("textbox", { name: "Name of column 2" }), "sku ");
    expect(screen.getByText("Another column already has this name.")).toBeInTheDocument();
    await userEvent.clear(screen.getByRole("textbox", { name: "Name of column 2" }));
    await userEvent.type(screen.getByRole("textbox", { name: "Name of column 2" }), "Nota");
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Source for Nota" }), "constant");
    expect(screen.getByText("Type the fixed value.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Use these columns" })).toBeDisabled();
  });

  it("names Pricor fields in plain words", async () => {
    renderPanel();
    await userEvent.click(screen.getByRole("button", { name: "Add column" }));
    const source = screen.getByRole("combobox", { name: "Source for column 1" });
    const labels = within(source).getAllByRole("option").map((option) => option.textContent);
    expect(labels).toEqual(["Product code", "Description", "Net unit cost", "Currency", "Row in the supplier file", "Leave empty", "Fixed value"]);
  });

  it("says when the columns are in use and can go back to the standard ones", async () => {
    const props = renderPanel({ format: confirmed() });
    expect(screen.getByText("In use: the products file has exactly these columns, in this order.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Use standard columns" }));
    expect(props.onRemove).toHaveBeenCalled();
  });

  it("discards unsaved hand-made columns without calling the server", async () => {
    const props = renderPanel();
    await userEvent.click(screen.getByRole("button", { name: "Add column" }));
    await userEvent.click(screen.getByRole("button", { name: "Use standard columns" }));
    expect(screen.queryAllByRole("listitem")).toHaveLength(0);
    expect(props.onRemove).not.toHaveBeenCalled();
  });

  it("shows the animated loader while the format loads", () => {
    renderPanel({ loading: true });
    expect(screen.getByRole("status")).toHaveClass("tape-loader");
  });
});
