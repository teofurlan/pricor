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

function renderPanel(overrides: Partial<React.ComponentProps<typeof OutputFormatPanel>> = {}) {
  const props: React.ComponentProps<typeof OutputFormatPanel> = {
    format: null,
    loading: false,
    busy: false,
    error: null,
    onUpload: vi.fn(),
    onConfirm: vi.fn(),
    onRemove: vi.fn(),
    ...overrides,
  };
  renderWithI18n(<OutputFormatPanel {...props} />);
  return props;
}

describe("OutputFormatPanel", () => {
  it("explains the standard format and uploads a template file", async () => {
    const props = renderPanel();
    expect(screen.getByText(/Pricor's standard columns/)).toBeInTheDocument();
    const file = new File(["Código,Stock\n"], "mi-sistema.csv");
    await userEvent.upload(screen.getByLabelText("Template file"), file);
    await userEvent.click(screen.getByRole("button", { name: "Read the template" }));
    expect(props.onUpload).toHaveBeenCalledWith(file);
  });

  it("shows each template column with its samples and the model's proposal, applied only on confirm", async () => {
    const props = renderPanel({ format: format() });
    const table = screen.getByRole("table", { name: "Template columns" });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(3);
    expect(within(rows[0]).getByText("Código")).toBeInTheDocument();
    expect(within(rows[0]).getByText("A1, B2")).toBeInTheDocument();
    expect(within(rows[0]).getByText("Gemma 92%")).toBeInTheDocument();
    expect(within(rows[1]).getByText("Rule")).toBeInTheDocument();
    expect(within(rows[0]).getByRole("combobox", { name: "Source for Código" })).toHaveValue("field:supplier_code");
    expect(within(rows[1]).getByRole("combobox", { name: "Source for Stock" })).toHaveValue("empty");
    expect(within(rows[2]).getByRole("textbox", { name: "Fixed value for Moneda" })).toHaveValue("ARS");
    expect(screen.getByText("Not in use yet: confirm the columns to use this format.")).toBeInTheDocument();
    expect(props.onConfirm).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: "Use this format" }));
    expect(props.onConfirm).toHaveBeenCalledWith(["field:supplier_code", "empty", "constant:ARS"]);
  });

  it("lets the user change a source, including a fixed value they type", async () => {
    const props = renderPanel({ format: format() });
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Source for Stock" }), "constant");
    const fixed = screen.getByRole("textbox", { name: "Fixed value for Stock" });
    expect(screen.getByRole("button", { name: "Use this format" })).toBeDisabled();
    await userEvent.type(fixed, "0");
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Source for Código" }), "field:description");
    await userEvent.click(screen.getByRole("button", { name: "Use this format" }));
    expect(props.onConfirm).toHaveBeenCalledWith(["field:description", "constant:0", "constant:ARS"]);
  });

  it("names Pricor fields in plain words", () => {
    renderPanel({ format: format() });
    const source = screen.getByRole("combobox", { name: "Source for Código" });
    const labels = within(source).getAllByRole("option").map((option) => option.textContent);
    expect(labels).toEqual(["Product code", "Description", "Net unit cost", "Currency", "Row in the supplier file", "Leave empty", "Fixed value"]);
  });

  it("says when the format is in use and can remove it", async () => {
    const confirmed = format({
      state: "confirmed",
      columns: format().columns.map((column) => ({ ...column, source: column.proposal.source })),
    });
    const props = renderPanel({ format: confirmed });
    expect(screen.getByText("In use: the products file follows these columns.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Remove this format" }));
    expect(props.onRemove).toHaveBeenCalled();
  });

  it("shows the animated loader while the format loads", () => {
    renderPanel({ loading: true });
    expect(screen.getByRole("status")).toHaveClass("tape-loader");
  });
});
