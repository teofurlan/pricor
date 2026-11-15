import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api/client";
import type { SampleListing } from "../../api/types";
import { renderWithI18n } from "../../test/render";
import { UploadForm } from "./UploadForm";

const week1: SampleListing = {
  id: "demo-1",
  file_name: "demo-semana-1.xlsx",
  supplier_name: "Distribuidora Ejemplo",
  week: 1,
  title: { en: "Example distributor, week 1", es: "Distribuidora Ejemplo, semana 1" },
  description: { en: "About 300 products.", es: "Unos 300 productos." },
};
const week2: SampleListing = {
  ...week1,
  id: "demo-2",
  file_name: "demo-semana-2-simulada.xlsx",
  week: 2,
  description: { en: "Next week, simulated.", es: "La semana siguiente, simulada." },
  title: { en: "Example distributor, week 2 (simulated)", es: "Distribuidora Ejemplo, semana 2 (simulada)" },
};

describe("UploadForm sample picker", () => {
  it("lists the samples in the interface language", async () => {
    renderWithI18n(
      <UploadForm busy={false} onSubmit={vi.fn()} onListSamples={vi.fn().mockResolvedValue([week1, week2])} onLoadSample={vi.fn()} />,
      "es",
    );

    expect(await screen.findByText("¿No tiene una lista a mano? Pruebe con un ejemplo")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Distribuidora Ejemplo, semana 1/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /semana 2 \(simulada\)/ })).toBeInTheDocument();
    expect(screen.getByText("Unos 300 productos.")).toBeInTheDocument();
  });

  it("loads the chosen file and the supplier name into the form as if it had been dropped", async () => {
    const file = new File(["x"], "demo-semana-1.xlsx");
    const onLoadSample = vi.fn().mockResolvedValue(file);
    const onInspectSheets = vi.fn().mockResolvedValue(["Lista de precios"]);
    const onSubmit = vi.fn();
    renderWithI18n(
      <UploadForm busy={false} onSubmit={onSubmit} onInspectSheets={onInspectSheets}
        onListSamples={vi.fn().mockResolvedValue([week1])} onLoadSample={onLoadSample} />,
    );

    await userEvent.click(await screen.findByRole("button", { name: /Example distributor, week 1/ }));

    await waitFor(() => expect(screen.getByLabelText("Supplier for demo-semana-1.xlsx")).toHaveValue("Distribuidora Ejemplo"));
    expect(onLoadSample).toHaveBeenCalledWith(week1);
    expect(await screen.findByText("demo-semana-1")).toBeInTheDocument();
    expect(onInspectSheets).toHaveBeenCalledWith(file);
    await userEvent.click(screen.getByRole("button", { name: "Start import" }));
    expect(onSubmit).toHaveBeenCalledWith({ file, supplierName: "Distribuidora Ejemplo", sheet: "", language: "en" });
  });

  it("says so, and keeps the form as it was, when the file cannot be loaded", async () => {
    const onLoadSample = vi.fn().mockRejectedValue(new ApiError(404, "sample_not_found", "no sample list"));
    renderWithI18n(
      <UploadForm busy={false} onSubmit={vi.fn()} onListSamples={vi.fn().mockResolvedValue([week1])} onLoadSample={onLoadSample} />,
    );

    await userEvent.click(await screen.findByRole("button", { name: /week 1/ }));

    expect(await screen.findByText(/Could not load the sample list/)).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Chosen files" })).toBeNull();
    expect(screen.queryByLabelText(/^Supplier for /)).toBeNull();
    expect(screen.getByRole("button", { name: "Start import" })).toBeDisabled();
  });

  it("is hidden when the list is empty", async () => {
    const onListSamples = vi.fn().mockResolvedValue([]);
    renderWithI18n(<UploadForm busy={false} onSubmit={vi.fn()} onListSamples={onListSamples} onLoadSample={vi.fn()} />);

    await waitFor(() => expect(onListSamples).toHaveBeenCalled());
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(screen.queryByText("Don't have a list at hand? Try an example")).not.toBeInTheDocument();
  });

  it("is hidden when the request fails", async () => {
    const onListSamples = vi.fn().mockRejectedValue(new ApiError(0, "network_error", "cannot be reached"));
    renderWithI18n(<UploadForm busy={false} onSubmit={vi.fn()} onListSamples={onListSamples} onLoadSample={vi.fn()} />);

    await waitFor(() => expect(onListSamples).toHaveBeenCalled());
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(screen.queryByText("Don't have a list at hand? Try an example")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("is absent when the form is not given a sample source", () => {
    renderWithI18n(<UploadForm busy={false} onSubmit={vi.fn()} />);

    expect(screen.queryByText("Don't have a list at hand? Try an example")).not.toBeInTheDocument();
  });
});
