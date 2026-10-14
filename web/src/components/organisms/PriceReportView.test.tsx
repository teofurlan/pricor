import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { priceReport, reportChange } from "../../test/fixtures";
import { renderWithI18n } from "../../test/render";
import { PriceReportView } from "./PriceReportView";

function view(report = priceReport(), props: Partial<Parameters<typeof PriceReportView>[0]> = {}) {
  const onThreshold = vi.fn();
  renderWithI18n(
    <PriceReportView report={report} csvUrl="/imports/s2/report/export?format=csv" busy={false} onThreshold={onThreshold} {...props} />,
  );
  return { onThreshold };
}

describe("PriceReportView", () => {
  it("opens with a one-line summary of the whole comparison", () => {
    view();

    expect(screen.getByRole("heading", { level: 2, name: /unchanged/ })).toHaveTextContent(
      "312 unchanged, 85 up, 4 down (median change +4.20%), 3 anomalies to review",
    );
    expect(screen.getByText("2 new products, 1 discontinued.")).toBeInTheDocument();
  });

  it("uses the singular for a single anomaly and leaves the median out when nothing changed", () => {
    const base = priceReport();
    view(
      priceReport({
        summary: { ...base.summary, increases: 0, decreases: 0, anomalies: 1, median_change_pct: null },
      }),
    );

    expect(screen.getByRole("heading", { level: 2, name: /unchanged/ })).toHaveTextContent(
      "312 unchanged, 0 up, 0 down, 1 anomaly to review",
    );
  });

  it("highlights anomalies in their own section", () => {
    const big = reportChange({
      supplier_code: "A2",
      description: "Tuerca",
      previous_cost: "800.00",
      current_cost: "3200.00",
      change: "2400.00",
      change_pct: "300.00",
      anomaly: true,
    });
    view(priceReport({ anomalies: [big], increases: [big, reportChange()] }));

    const section = screen.getByRole("region", { name: "Anomalies to review (1)" });
    const row = within(section).getByRole("row", { name: /A2/ });
    expect(row).toHaveClass("row--anomaly");
    expect(within(row).getByText("800.00 ARS")).toBeInTheDocument();
    expect(within(row).getByText("3200.00 ARS")).toBeInTheDocument();
    expect(within(row).getByText("+2400.00 ARS")).toBeInTheDocument();
    expect(within(row).getByText("+300.00%")).toBeInTheDocument();
  });

  it("marks the same anomaly inside the increases table too", () => {
    const big = reportChange({ supplier_code: "A2", change_pct: "300.00", anomaly: true });
    view(priceReport({ anomalies: [big], increases: [big, reportChange()] }));

    const increases = screen.getByRole("region", { name: "Price increases (2)" });
    expect(within(increases).getByRole("row", { name: /A2/ })).toHaveClass("row--anomaly");
    expect(within(increases).getByRole("row", { name: /A1/ })).not.toHaveClass("row--anomaly");
  });

  it("says so when nothing goes beyond the threshold", () => {
    const base = priceReport();
    view(priceReport({ summary: { ...base.summary, anomalies: 0 }, anomalies: [] }));

    expect(screen.getByText("No change goes beyond 30%.")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: /Anomalies/ })).not.toBeInTheDocument();
  });

  it("shows increases and decreases with the amount and percentage of each", () => {
    view(
      priceReport({
        decreases: [
          reportChange({
            supplier_code: "B1",
            description: "Arandela",
            previous_cost: "100.00",
            current_cost: "90.00",
            change: "-10.00",
            change_pct: "-10.00",
          }),
        ],
      }),
    );

    const up = within(screen.getByRole("region", { name: "Price increases (1)" })).getByRole("row", { name: /A1/ });
    expect(within(up).getByText("1000.00 ARS")).toBeInTheDocument();
    expect(within(up).getByText("+100.00 ARS")).toBeInTheDocument();
    expect(within(up).getByText("+10.00%")).toBeInTheDocument();
    const down = within(screen.getByRole("region", { name: "Price decreases (1)" })).getByRole("row", { name: /B1/ });
    expect(within(down).getByText("-10.00 ARS")).toBeInTheDocument();
    expect(within(down).getByText("-10.00%")).toBeInTheDocument();
  });

  it("leaves out the sections that are empty", () => {
    const base = priceReport();
    view(priceReport({ summary: { ...base.summary, decreases: 0, new_products: 0, discontinued: 0 } }));

    expect(screen.queryByRole("region", { name: /decreases/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: /New products/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: /Discontinued/ })).not.toBeInTheDocument();
  });

  it("lists new and discontinued products with their cost", () => {
    view(
      priceReport({
        new_products: [{ supplier_code: "N1", description: "Nuevo", currency: "USD", unit_cost_net: "12.00" }],
        discontinued: [{ supplier_code: "G1", description: "Viejo", currency: "ARS", unit_cost_net: "7.50" }],
      }),
    );

    const fresh = within(screen.getByRole("region", { name: "New products (1)" })).getByRole("row", { name: /N1/ });
    expect(within(fresh).getByText("12.00 USD")).toBeInTheDocument();
    const gone = within(screen.getByRole("region", { name: "Discontinued products (1)" })).getByRole("row", { name: /G1/ });
    expect(within(gone).getByText("7.50 ARS")).toBeInTheDocument();
  });

  it("explains a cost that left zero instead of showing a percentage", () => {
    const base = priceReport();
    view(
      priceReport({
        summary: { ...base.summary, from_zero: 1 },
        from_zero: [
          reportChange({
            supplier_code: "Z1",
            previous_cost: "0.00",
            current_cost: "3.00",
            change: "3.00",
            change_pct: null,
            anomaly: true,
          }),
        ],
      }),
    );

    const section = screen.getByRole("region", { name: "Cost came from zero (1)" });
    expect(within(section).getByText(/no percentage/)).toBeInTheDocument();
    const row = within(section).getByRole("row", { name: /Z1/ });
    expect(within(row).getByText("+3.00 ARS")).toBeInTheDocument();
    expect(within(row).queryByText(/%/)).not.toBeInTheDocument();
  });

  it("keeps products that changed currency apart and says they were not compared", () => {
    const base = priceReport();
    view(
      priceReport({
        summary: { ...base.summary, currency_changed: 1 },
        currency_changed: [
          {
            supplier_code: "C1",
            description: "Cable",
            previous_currency: "ARS",
            current_currency: "USD",
            previous_cost: "1000.00",
            current_cost: "1.00",
          },
        ],
      }),
    );

    const section = screen.getByRole("region", { name: "Currency changed (1)" });
    expect(within(section).getByText(/not compared/)).toBeInTheDocument();
    const row = within(section).getByRole("row", { name: /C1/ });
    expect(within(row).getByText("1000.00 ARS")).toBeInTheDocument();
    expect(within(row).getByText("1.00 USD")).toBeInTheDocument();
  });

  it("reports repeated codes that were left out", () => {
    const base = priceReport();
    view(
      priceReport({
        summary: { ...base.summary, ambiguous: 1 },
        ambiguous_codes: [{ supplier_code: "DUP", previous_count: 2, current_count: 1 }],
      }),
    );

    const section = screen.getByRole("region", { name: "Codes left out (1)" });
    expect(within(section).getByText(/DUP/)).toHaveTextContent("DUP: 2 times before, 1 time now");
  });

  it("shows the first rows of a long section and the rest on request", async () => {
    const many = Array.from({ length: 60 }, (_, n) =>
      reportChange({ supplier_code: `P${String(n).padStart(2, "0")}`, description: `Producto ${n}` }),
    );
    view(priceReport({ increases: many }));
    const section = screen.getByRole("region", { name: "Price increases (60)" });

    expect(within(section).getAllByRole("row")).toHaveLength(51); // header + 50
    await userEvent.click(within(section).getByRole("button", { name: "Show all 60" }));
    expect(within(section).getAllByRole("row")).toHaveLength(61);
    expect(within(section).queryByRole("button", { name: /Show all/ })).not.toBeInTheDocument();
  });

  it("lets the user change the threshold in percent and hands the ratio on", async () => {
    const { onThreshold } = view();
    const field = screen.getByLabelText("Anomaly threshold (%)");
    expect(field).toHaveValue("30");

    await userEvent.clear(field);
    await userEvent.type(field, "12,5");
    await userEvent.click(screen.getByRole("button", { name: "Apply" }));

    expect(onThreshold).toHaveBeenCalledWith("0.125");
  });

  it("does not apply a threshold that is not a number", async () => {
    const { onThreshold } = view();
    const field = screen.getByLabelText("Anomaly threshold (%)");

    await userEvent.clear(field);
    await userEvent.type(field, "abc");

    expect(screen.getByRole("button", { name: "Apply" })).toBeDisabled();
    expect(screen.getByText("Enter a percentage such as 30.")).toBeInTheDocument();
    expect(onThreshold).not.toHaveBeenCalled();
  });

  it("links to the CSV of the report", () => {
    view();

    expect(screen.getByRole("link", { name: "Report (CSV)" })).toHaveAttribute(
      "href",
      "/imports/s2/report/export?format=csv",
    );
  });

  it("speaks Spanish", () => {
    renderWithI18n(
      <PriceReportView report={priceReport()} csvUrl="/x" busy={false} onThreshold={vi.fn()} />,
      "es",
    );

    expect(screen.getByRole("heading", { level: 2, name: /sin cambios/ })).toHaveTextContent(
      "312 sin cambios, 85 subieron, 4 bajaron (variación mediana +4.20%), 3 anomalías para revisar",
    );
  });
});
