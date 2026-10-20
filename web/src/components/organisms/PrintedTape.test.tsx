import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { previewItem, previewPage } from "../../test/fixtures";
import { renderWithI18n } from "../../test/render";
import { TapeFigure } from "../atoms/TapeFigure";
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
  const traceVal = (text: string) => (_: string, el: Element | null) =>
    Boolean(el?.classList.contains("trace__value") && el?.textContent === text);

  it("selects rows with Down and Up while the row journal has focus, without wrapping", () => {
    motion(true);
    renderWithI18n(<PreviewTable page={page} busy={false} onPage={vi.fn()} />);
    const journal = screen.getByRole("region", { name: "Preview rows" });
    const tape = screen.getByRole("region", { name: "From file to cost" });
    journal.focus();
    expect(within(tape).getByText(traceVal("1000.00 ARS"))).toBeInTheDocument();
    fireEvent.keyDown(journal, { key: "ArrowDown" });
    expect(within(tape).getByText(traceVal("2420.00 ARS"))).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Row 4" })).toHaveAttribute("aria-pressed", "true");
    expect(journal).toHaveFocus();
    fireEvent.keyDown(journal, { key: "ArrowDown" });
    expect(within(tape).getByText(traceVal("2420.00 ARS"))).toBeInTheDocument();
    fireEvent.keyDown(journal, { key: "ArrowUp" });
    expect(within(tape).getByText(traceVal("1000.00 ARS"))).toBeInTheDocument();
    fireEvent.keyDown(journal, { key: "ArrowUp" });
    expect(within(tape).getByText(traceVal("1000.00 ARS"))).toBeInTheDocument();
  });

  it("prints the selected row's actual trace and final cost, not the worked example", () => {
    motion(true);
    renderWithI18n(<PreviewTable page={page} busy={false} onPage={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Row 4" }));
    const tape = screen.getByRole("region", { name: "From file to cost" });
    expect(within(tape).getByText(traceVal("2420.00 ARS")).closest("li")).toHaveClass("trace__step--final");
    expect(within(tape).getAllByRole("listitem")).toHaveLength(second.trace.length);
    expect(within(tape).queryByText(traceVal("1000.00 ARS"))).not.toBeInTheDocument();
    expect(within(tape).queryByText(traceVal("855.00 ARS"))).not.toBeInTheDocument();
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

  it("prints the first trace one line per 70 ms, then shows later selections at once", () => {
    motion(false);
    vi.useFakeTimers();
    renderWithI18n(<PreviewTable page={page} busy={false} onPage={vi.fn()} />);
    const tape = screen.getByRole("region", { name: "From file to cost" });
    expect(within(tape).getAllByRole("listitem")).toHaveLength(1);
    expect(within(tape).getByRole("status")).toBeEmptyDOMElement();
    act(() => vi.advanceTimersByTime(70));
    expect(within(tape).getAllByRole("listitem")).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: "Row 4" }));
    expect(within(tape).getAllByRole("listitem")).toHaveLength(second.trace.length);
    expect(within(tape).getByRole("status")).toHaveTextContent("Final cost: 2420.00 ARS");
    expect(vi.getTimerCount()).toBe(0);
    fireEvent.click(screen.getByRole("button", { name: "Row 3" }));
    expect(within(tape).getAllByRole("listitem")).toHaveLength(page.items[0].trace.length);
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

describe("upload step", () => {
  it("shows only the upload form, without a worked example beside it", () => {
    renderWithI18n(<UploadForm busy={false} onSubmit={vi.fn()} />);
    expect(screen.queryByRole("region", { name: "How Pricor works out a cost" })).not.toBeInTheDocument();
    expect(document.querySelector(".tape")).toBeNull();
  });
});

describe("tape figures", () => {
  it("aligns figures on the decimal point when values have no decimals (10 vs 0.90)", () => {
    render(<>
      <TapeFigure value="10" fracWidth={3} />
      <TapeFigure value="0.90" fracWidth={3} />
      <TapeFigure value="855.00 ARS" fracWidth={3} />
    </>);
    const [val10, val90, total] = Array.from(document.querySelectorAll(".num-split"));
    expect(within(val10 as HTMLElement).getByText("10")).toHaveClass("num-int");
    expect(val10.querySelector(".num-frac")).toBeEmptyDOMElement();
    expect(within(val90 as HTMLElement).getByText("0")).toHaveClass("num-int");
    expect(within(val90 as HTMLElement).getByText(".90")).toHaveClass("num-frac");
    expect(within(total as HTMLElement).getByText("855")).toHaveClass("num-int");
    expect(within(total as HTMLElement).getByText(".00 ARS")).toHaveClass("num-frac");
  });
});
