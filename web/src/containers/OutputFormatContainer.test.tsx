import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ApiError, type OutputFormatApiClient } from "../api/client";
import type { OutputFormat } from "../api/types";
import { renderWithI18n } from "../test/render";
import { OutputFormatContainer } from "./OutputFormatContainer";

const proposed: OutputFormat = {
  name: "mi-sistema.csv",
  state: "proposed",
  fields: ["supplier_code", "unit_cost_net"],
  columns: [
    { index: 0, name: "Código", samples: [], proposal: { source: "field:supplier_code", proposed_by: "heuristics", confidence: 0.6 }, source: null },
    { index: 1, name: "Costo", samples: [], proposal: { source: "field:unit_cost_net", proposed_by: "heuristics", confidence: 0.6 }, source: null },
  ],
};
const confirmed: OutputFormat = { ...proposed, state: "confirmed", columns: proposed.columns.map((column) => ({ ...column, source: column.proposal.source })) };

function fakeApi(overrides: Partial<OutputFormatApiClient> = {}): OutputFormatApiClient {
  return {
    getOutputFormat: vi.fn().mockResolvedValue(null),
    uploadOutputFormat: vi.fn().mockResolvedValue(proposed),
    confirmOutputFormat: vi.fn().mockResolvedValue(confirmed),
    defineOutputFormat: vi.fn().mockResolvedValue(confirmed),
    deleteOutputFormat: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  };
}

describe("OutputFormatContainer", () => {
  it("loads the stored format once and reports it", async () => {
    const onChange = vi.fn();
    const api = fakeApi({ getOutputFormat: vi.fn().mockResolvedValue(confirmed) });
    renderWithI18n(<OutputFormatContainer api={api} onChange={onChange} />);
    expect(await screen.findByText("In use: the products file has exactly these columns, in this order.")).toBeInTheDocument();
    expect(onChange).toHaveBeenCalledWith(confirmed);
    expect(api.getOutputFormat).toHaveBeenCalledTimes(1);
  });

  it("uploads a template, saves the proposal and can go back to the standard columns", async () => {
    const onChange = vi.fn();
    const api = fakeApi();
    renderWithI18n(<OutputFormatContainer api={api} onChange={onChange} />);
    const file = new File(["Código,Costo\n"], "mi-sistema.csv");
    await userEvent.upload(await screen.findByLabelText("Template file"), file);
    await userEvent.click(screen.getByRole("button", { name: "Read the template" }));
    expect(api.uploadOutputFormat).toHaveBeenCalledWith(file);
    expect(await screen.findByText("Not in use yet: save to use these columns.")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Use these columns" }));
    expect(api.defineOutputFormat).toHaveBeenCalledWith([
      { name: "Código", source: "field:supplier_code", template_index: 0 },
      { name: "Costo", source: "field:unit_cost_net", template_index: 1 },
    ]);
    expect(await screen.findByText("In use: the products file has exactly these columns, in this order.")).toBeInTheDocument();
    expect(onChange).toHaveBeenLastCalledWith(confirmed);

    await userEvent.click(screen.getByRole("button", { name: "Use standard columns" }));
    expect(api.deleteOutputFormat).toHaveBeenCalled();
    await waitFor(() => expect(onChange).toHaveBeenLastCalledWith(null));
    expect(screen.getByText(/Pricor's standard columns/)).toBeInTheDocument();
  });

  it("shows the server's message when a template cannot be read", async () => {
    const api = fakeApi({ uploadOutputFormat: vi.fn().mockRejectedValue(new ApiError(422, "invalid_template", "The template has no column names.")) });
    renderWithI18n(<OutputFormatContainer api={api} />);
    await userEvent.upload(await screen.findByLabelText("Template file"), new File([""], "vacio.csv"));
    await userEvent.click(screen.getByRole("button", { name: "Read the template" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The template has no column names.");
  });

  it("offers every product field before any format is stored", async () => {
    renderWithI18n(<OutputFormatContainer api={fakeApi()} />);
    await userEvent.click(await screen.findByRole("button", { name: "Add column" }));
    const options = screen.getByRole("combobox", { name: "Source for column 1" }).querySelectorAll("option");
    expect(options).toHaveLength(15); // 13 fields, empty and fixed value
  });
});
