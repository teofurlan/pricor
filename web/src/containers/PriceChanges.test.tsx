import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, type ApiClient } from "../api/client";
import { priceReport } from "../test/fixtures";
import { renderWithI18n } from "../test/render";
import { PriceChanges } from "./PriceChanges";

function fakeApi(report: ApiClient["report"]): ApiClient {
  return {
    report,
    reportUrl: (id, threshold) => `/imports/${id}/report/export?format=csv${threshold ? `&threshold=${threshold}` : ""}`,
  } as ApiClient;
}

const noPrevious = () => Promise.reject(new ApiError(409, "no_previous_import", "nothing to compare with"));

beforeEach(() => localStorage.clear());
afterEach(() => localStorage.clear());

describe("PriceChanges", () => {
  it("loads the report of the approved import and shows its summary", async () => {
    const report = vi.fn().mockResolvedValue(priceReport());
    renderWithI18n(<PriceChanges api={fakeApi(report)} sessionId="s2" supplierName="Ferreteria Ejemplo" />);

    expect(screen.getByText("Loading…")).toBeInTheDocument();
    expect(await screen.findByRole("heading", { level: 2, name: /312 unchanged/ })).toBeInTheDocument();
    expect(report).toHaveBeenCalledWith("s2", undefined);
    expect(screen.getByRole("link", { name: "Report (CSV)" })).toHaveAttribute(
      "href",
      "/imports/s2/report/export?format=csv&threshold=0.30",
    );
  });

  it("shows a calm empty state for the first import of a supplier", async () => {
    renderWithI18n(<PriceChanges api={fakeApi(vi.fn(noPrevious))} sessionId="s1" supplierName="Ferreteria Ejemplo" />);

    expect(
      await screen.findByText(
        "This is the first approved list from Ferreteria Ejemplo. When you approve the next one, you will see here what changed.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows any other failure as an error", async () => {
    const report = vi.fn().mockRejectedValue(new ApiError(500, "internal_error", "unexpected server error"));
    renderWithI18n(<PriceChanges api={fakeApi(report)} sessionId="s2" supplierName="Ferreteria Ejemplo" />);

    expect(await screen.findByRole("alert")).toHaveTextContent("unexpected server error");
  });

  it("asks again with the new threshold and remembers it", async () => {
    const report = vi.fn().mockResolvedValue(priceReport());
    renderWithI18n(<PriceChanges api={fakeApi(report)} sessionId="s2" supplierName="Ferreteria Ejemplo" />);
    const field = await screen.findByLabelText("Anomaly threshold (%)");

    await userEvent.clear(field);
    await userEvent.type(field, "50");
    await userEvent.click(screen.getByRole("button", { name: "Apply" }));

    await waitFor(() => expect(report).toHaveBeenLastCalledWith("s2", "0.50"));
    expect(localStorage.getItem("pricor.anomalyThresholdPercent")).toBe("50");
  });

  it("starts from the threshold the user chose last time", async () => {
    localStorage.setItem("pricor.anomalyThresholdPercent", "15");
    const report = vi.fn().mockResolvedValue(priceReport({ threshold: "0.15" }));
    renderWithI18n(<PriceChanges api={fakeApi(report)} sessionId="s2" supplierName="Ferreteria Ejemplo" />);

    await screen.findByRole("heading", { level: 2, name: /312 unchanged/ });

    expect(report).toHaveBeenCalledWith("s2", "0.15");
    expect(screen.getByLabelText("Anomaly threshold (%)")).toHaveValue("15");
  });

  it("ignores a remembered threshold that is not a number", async () => {
    localStorage.setItem("pricor.anomalyThresholdPercent", "lots");
    const report = vi.fn().mockResolvedValue(priceReport());
    renderWithI18n(<PriceChanges api={fakeApi(report)} sessionId="s2" supplierName="Ferreteria Ejemplo" />);

    await screen.findByRole("heading", { level: 2, name: /312 unchanged/ });

    expect(report).toHaveBeenCalledWith("s2", undefined);
  });

  it("works when the browser refuses to store the threshold", async () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    const report = vi.fn().mockResolvedValue(priceReport());
    renderWithI18n(<PriceChanges api={fakeApi(report)} sessionId="s2" supplierName="Ferreteria Ejemplo" />);
    const field = await screen.findByLabelText("Anomaly threshold (%)");

    await userEvent.clear(field);
    await userEvent.type(field, "40");
    await userEvent.click(screen.getByRole("button", { name: "Apply" }));

    await waitFor(() => expect(report).toHaveBeenLastCalledWith("s2", "0.40"));
    vi.restoreAllMocks();
  });
});
