import { act, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { previewItem, previewPage } from "../../test/fixtures";
import { renderWithI18n } from "../../test/render";
import { PreviewTable } from "./PreviewTable";
import { UploadForm } from "./UploadForm";

function motion(reduced: boolean) {
  vi.stubGlobal("matchMedia", vi.fn(() => ({
    matches: reduced, addEventListener: vi.fn(), removeEventListener: vi.fn(),
  })));
}

const second = previewItem({
  row_number: 4,
  original: ["B2", "Nut", "2420"],
  trace: [{ step: "original", value: "2420" }, { step: "rounding", value: "2420.00" }],
  record: { supplier_code: "B2", description: "Nut", unit_cost_net: "2420.00", currency: "ARS" },
});
const page = previewPage({ items: [previewItem(), second] });

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

describe("printed preview tape", () => {
  it("selects rows with Down and Up while the row journal has focus, without wrapping", () => {
    motion(true);
    renderWithI18n(<PreviewTable page={page} busy={false} onPage={vi.fn()} />);
    const journal = screen.getByRole("region", { name: "Preview rows" });
    const tape = screen.getByRole("region", { name: "From file to cost" });
    journal.focus();
    expect(within(tape).getByText("1000.00 ARS")).toBeInTheDocument();
    fireEvent.keyDown(journal, { key: "ArrowDown" });
    expect(within(tape).getByText("2420.00 ARS")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Row 4" })).toHaveAttribute("aria-pressed", "true");
    expect(journal).toHaveFocus();
    fireEvent.keyDown(journal, { key: "ArrowDown" });
    expect(within(tape).getByText("2420.00 ARS")).toBeInTheDocument();
    fireEvent.keyDown(journal, { key: "ArrowUp" });
    expect(within(tape).getByText("1000.00 ARS")).toBeInTheDocument();
    fireEvent.keyDown(journal, { key: "ArrowUp" });
    expect(within(tape).getByText("1000.00 ARS")).toBeInTheDocument();
  });

  it("prints the selected row's actual trace and final cost, not the worked example", () => {
    motion(true);
    renderWithI18n(<PreviewTable page={page} busy={false} onPage={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Row 4" }));
    const tape = screen.getByRole("region", { name: "From file to cost" });
    expect(within(tape).getByText("2420.00 ARS").closest("li")).toHaveClass("trace__step--final");
    expect(within(tape).getAllByRole("listitem")).toHaveLength(second.trace.length);
    expect(within(tape).queryByText("1000.00 ARS")).not.toBeInTheDocument();
    expect(within(tape).queryByText("855.00 ARS")).not.toBeInTheDocument();
  });

  it("renders every line immediately under reduced motion and announces only the final cost", () => {
    motion(true);
    vi.useFakeTimers();
    renderWithI18n(<PreviewTable page={page} busy={false} onPage={vi.fn()} />);
    const tape = screen.getByRole("region", { name: "From file to cost" });
    expect(within(tape).getAllByRole("listitem")).toHaveLength(page.items[0].trace.length);
    expect(within(tape).getByRole("status")).toHaveTextContent("Final cost: 1000.00 ARS");
    expect(vi.getTimerCount()).toBe(0);
  });

  it("advances one trace line per 70 ms and cancels the old print when selection changes", () => {
    motion(false);
    vi.useFakeTimers();
    renderWithI18n(<PreviewTable page={page} busy={false} onPage={vi.fn()} />);
    const tape = screen.getByRole("region", { name: "From file to cost" });
    expect(within(tape).getAllByRole("listitem")).toHaveLength(1);
    expect(within(tape).getByRole("status")).toBeEmptyDOMElement();
    act(() => vi.advanceTimersByTime(70));
    expect(within(tape).getAllByRole("listitem")).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: "Row 4" }));
    expect(within(tape).getAllByRole("listitem")).toHaveLength(1);
    act(() => vi.advanceTimersByTime(70));
    expect(within(tape).getAllByRole("listitem")).toHaveLength(2);
    expect(within(tape).getByRole("status")).toHaveTextContent("Final cost: 2420.00 ARS");
    expect(vi.getTimerCount()).toBe(0);
  });

  it("shows rejection reasons on selection instead of manufacturing a calculation", () => {
    motion(true);
    const rejected = previewItem({ row_number: 9, status: "rejected", trace: [], record: null, reasons: ["Invalid cost"] });
    renderWithI18n(<PreviewTable page={previewPage({ items: [previewItem(), rejected] })} busy={false} onPage={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Row 9" }));
    const tape = screen.getByRole("region", { name: "From file to cost" });
    expect(within(tape).getByText("Invalid cost")).toBeInTheDocument();
    expect(within(tape).queryByText(/Final cost/)).not.toBeInTheDocument();
  });
});

describe("upload worked example", () => {
  it("labels engine test data and prints the pinned 855.00 total with every operation", () => {
    renderWithI18n(<UploadForm busy={false} onSubmit={vi.fn()} />);
    const tape = screen.getByRole("region", { name: "How Pricor works out a cost" });
    expect(within(tape).getByText("855.00 ARS")).toBeInTheDocument();
    expect(within(tape).getByText("Example: a box of 10 at $12,100 with VAT and two discounts.")).toBeInTheDocument();
    expect(screen.queryByText(/Worked example from the engine tests/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Not your data/i)).not.toBeInTheDocument();
    for (const value of ["12,100.00", "0.90", "0.95", "1.21", "10"]) {
      expect(within(tape).getByText(value)).toBeInTheDocument();
    }
    expect(within(tape).getAllByRole("listitem")).toHaveLength(6);
  });

  it("renders the new example copy in Spanish", () => {
    renderWithI18n(<UploadForm busy={false} onSubmit={vi.fn()} />, "es");
    const tape = screen.getByRole("region", { name: "Así calcula Pricor un costo" });
    expect(within(tape).getByText("Ejemplo: caja de 10 a $12.100 con IVA y dos descuentos.")).toBeInTheDocument();
    expect(screen.queryByText(/Ejemplo de las pruebas del motor/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/No son sus datos/i)).not.toBeInTheDocument();
  });

  it("aligns figures on the decimal point when values have no decimals (10 vs 0.90)", () => {
    renderWithI18n(<UploadForm busy={false} onSubmit={vi.fn()} />);
    const tape = screen.getByRole("region", { name: "How Pricor works out a cost" });
    const val10 = within(tape).getByText("10");
    const val90 = within(tape).getByText("0.90");
    const total = within(tape).getByText("855.00 ARS");
    // "10" has 0 tail chars, needs 7ch padding to align with "855.00 ARS" (7 chars) and "0.90" (3 chars + 4ch pad = 7ch)
    expect(val10.style.paddingInlineEnd).toBe("7ch");
    expect(val90.style.paddingInlineEnd).toBe("4ch");
    expect(total.style.paddingInlineEnd).toBe("0ch");
  });
});
