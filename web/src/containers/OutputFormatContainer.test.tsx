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
    deleteOutputFormat: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  };
}

describe("OutputFormatContainer", () => {
  it("loads the stored format once and reports it", async () => {
    const onChange = vi.fn();
    const api = fakeApi({ getOutputFormat: vi.fn().mockResolvedValue(confirmed) });
    renderWithI18n(<OutputFormatContainer api={api} open onClose={vi.fn()} onChange={onChange} />);
    expect(await screen.findByText("In use: the products file follows these columns.")).toBeInTheDocument();
    expect(onChange).toHaveBeenCalledWith(confirmed);
    expect(api.getOutputFormat).toHaveBeenCalledTimes(1);
  });

  it("uploads a template, confirms the proposal and can remove it", async () => {
    const onChange = vi.fn();
    const api = fakeApi();
    renderWithI18n(<OutputFormatContainer api={api} open onClose={vi.fn()} onChange={onChange} />);
    const file = new File(["Código,Costo\n"], "mi-sistema.csv");
    await userEvent.upload(await screen.findByLabelText("Template file"), file);
    await userEvent.click(screen.getByRole("button", { name: "Read the template" }));
    expect(api.uploadOutputFormat).toHaveBeenCalledWith(file);
    expect(await screen.findByText("Not in use yet: confirm the columns to use this format.")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Use this format" }));
    expect(api.confirmOutputFormat).toHaveBeenCalledWith(["field:supplier_code", "field:unit_cost_net"]);
    expect(await screen.findByText("In use: the products file follows these columns.")).toBeInTheDocument();
    expect(onChange).toHaveBeenLastCalledWith(confirmed);

    await userEvent.click(screen.getByRole("button", { name: "Remove this format" }));
    expect(api.deleteOutputFormat).toHaveBeenCalled();
    await waitFor(() => expect(onChange).toHaveBeenLastCalledWith(null));
    expect(screen.getByText(/Pricor's standard columns/)).toBeInTheDocument();
  });

  it("shows the server's message when a template cannot be read", async () => {
    const api = fakeApi({ uploadOutputFormat: vi.fn().mockRejectedValue(new ApiError(422, "invalid_template", "The template has no column names.")) });
    renderWithI18n(<OutputFormatContainer api={api} open onClose={vi.fn()} />);
    await userEvent.upload(await screen.findByLabelText("Template file"), new File([""], "vacio.csv"));
    await userEvent.click(screen.getByRole("button", { name: "Read the template" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The template has no column names.");
  });
});
