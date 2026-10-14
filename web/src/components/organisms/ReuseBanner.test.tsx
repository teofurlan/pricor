import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { change } from "../../test/fixtures";
import { renderWithI18n } from "../../test/render";
import { ReuseBanner } from "./ReuseBanner";

describe("ReuseBanner", () => {
  it("says which plan is being reused and that nothing changed", () => {
    renderWithI18n(<ReuseBanner version={2} supplier="Ferreteria Ejemplo" changes={[]} />);

    expect(screen.getByRole("heading", { name: "Reusing plan v2 for Ferreteria Ejemplo" })).toBeInTheDocument();
    expect(screen.getByText("The file keeps the same columns as before.")).toBeInTheDocument();
    expect(screen.queryByRole("list")).not.toBeInTheDocument();
  });

  it("lists every kind of change in plain words", () => {
    renderWithI18n(
      <ReuseBanner
        version={1}
        supplier="Acme"
        changes={[
          change({ kind: "sheet_changed", header: "", old_value: "Octubre", new_value: "Noviembre", role: null }),
          change({ kind: "header_row_changed", header: "", old_index: 0, new_index: 2, role: null }),
          change({ kind: "moved", header: "precio lista", old_index: 2, new_index: 4, role: "cost_price" }),
          change({
            kind: "retyped",
            header: "iva",
            old_index: 3,
            new_index: 3,
            old_type: "percent",
            new_type: "text",
            role: "vat_rate",
          }),
          change({
            kind: "new",
            header: "stock",
            old_index: null,
            new_index: 5,
            old_type: null,
            new_type: "integer",
            role: null,
          }),
          change({
            kind: "missing",
            header: "notas",
            old_index: 6,
            new_index: null,
            old_type: "text",
            new_type: null,
            role: null,
          }),
        ]}
      />,
    );

    const items = within(screen.getByRole("list"))
      .getAllByRole("listitem")
      .map((item) => item.textContent);
    expect(items).toEqual([
      "The sheet is now “Noviembre” (it was “Octubre”).",
      "The header is now on row 3 (it was on row 1).",
      "“precio lista” moved from column 3 to column 5. The plan follows it.",
      "“iva” now holds text values instead of percent. It was classified again.",
      "New column “stock” (column 6). It is not part of the plan until you decide.",
      "Column “notas” (was column 7) is gone. The plan did not use it.",
    ]);
  });

  it("calls out a missing column the plan depended on", () => {
    renderWithI18n(
      <ReuseBanner
        version={1}
        supplier="Acme"
        changes={[
          change({
            kind: "missing",
            header: "iva",
            old_index: 3,
            new_index: null,
            used_by_plan: true,
            role: "vat_rate",
          }),
        ]}
      />,
    );

    const item = screen.getByRole("listitem");
    expect(item).toHaveTextContent(
      "Column “iva” (was column 4) is gone, and the plan used it (role: VAT rate). That rule needs your attention.",
    );
    expect(item).toHaveClass("change--attention");
  });

  it("speaks Spanish", () => {
    renderWithI18n(<ReuseBanner version={3} supplier="Acme" changes={[]} />, "es");

    expect(screen.getByRole("heading", { name: "Reutilizando el plan v3 de Acme" })).toBeInTheDocument();
  });
});
