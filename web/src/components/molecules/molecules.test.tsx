import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { renderWithI18n } from "../../test/render";
import { previewPage, question } from "../../test/fixtures";
import { CountsSummary } from "./CountsSummary";
import { NoticeList } from "./NoticeList";
import { ProvenanceBadge } from "./ProvenanceBadge";
import { QuestionCard } from "./QuestionCard";
import { StepTrace } from "./StepTrace";
import { SuggestionBadge } from "./SuggestionBadge";
import { MemoryCitation } from "./MemoryCitation";
import type { Memory } from "../../api/types";

describe("ProvenanceBadge", () => {
  it.each([
    ["heuristics", "Heuristics"],
    ["gemma", "Gemma"],
    ["user", "YOU"],
    ["saved_plan", "Saved plan"],
  ])("names who decided: %s", (decidedBy, label) => {
    renderWithI18n(<ProvenanceBadge decidedBy={decidedBy} />);
    expect(screen.getByText(label)).toBeInTheDocument();
  });

  it("asks for a choice while nobody has decided", () => {
    renderWithI18n(<ProvenanceBadge decidedBy={null} />);
    expect(screen.getByText("Needs your choice")).toBeInTheDocument();
  });

  it("shows an unknown stage under its own name instead of hiding it", () => {
    renderWithI18n(<ProvenanceBadge decidedBy="laya" />);
    expect(screen.getByText("laya")).toBeInTheDocument();
  });
});

describe("SuggestionBadge", () => {
  const suggestion = { suggested_by: "gemma", option: "yes", confidence: 0.6, calibrated: false, evidence: [] };

  it("labels an uncalibrated model confidence as such", () => {
    renderWithI18n(<SuggestionBadge suggestion={suggestion} />);
    expect(screen.getByText("GEMMA ~.6")).toHaveAttribute("title", "Suggested by Gemma (uncalibrated: 0.6)");
  });

  it("names Gemma when the server only says 'model', the only advisor behind it", () => {
    renderWithI18n(<SuggestionBadge suggestion={{ ...suggestion, suggested_by: "model", confidence: 0.4 }} />);
    expect(screen.getByText("GEMMA ~.4")).toHaveAttribute("title", "Suggested by Gemma (uncalibrated: 0.4)");
  });

  it("labels a value read from the file as detected, with no model confidence", () => {
    renderWithI18n(
      <SuggestionBadge suggestion={{ ...suggestion, suggested_by: "detected", confidence: 1, calibrated: true }} />,
    );
    expect(screen.getByText("DETECTED · confirm or change")).toBeInTheDocument();
  });

  it("drops the warning once the confidence is calibrated", () => {
    renderWithI18n(<SuggestionBadge suggestion={{ ...suggestion, calibrated: true }} />);
    expect(screen.getByText("GEMMA .6")).toHaveAttribute("title", "Suggested by Gemma (calibrated: 0.6)");
  });
});

describe("MemoryCitation", () => {
  const memories: Memory[] = [{
    id: "m1",
    text: "Prices include VAT",
    supplier_name: "Acme",
    source: "user_note",
    created_at: "2026-10-18T10:00:00Z",
    updated_at: "2026-10-18T10:00:00Z",
  }];

  it("shows cited text and a deleted-memory fallback", () => {
    renderWithI18n(<MemoryCitation memoryIds={["m1", "gone"]} memories={memories} />);
    expect(screen.getByText("Based on your memory:")).toBeInTheDocument();
    expect(screen.getByText("Prices include VAT")).toBeInTheDocument();
    expect(screen.getByText("a memory that was deleted")).toBeInTheDocument();
  });

  it("renders nothing for an old suggestion without memory ids", () => {
    const { container } = renderWithI18n(<MemoryCitation memoryIds={undefined} memories={memories} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("StepTrace", () => {
  const trace = [
    { step: "original", value: "1.210,00" },
    { step: "strip_vat", value: "1000.00" },
    { step: "rounding", value: "1000.00" },
  ];

  it("lists every step in order, from the original cell to the final value", () => {
    renderWithI18n(<StepTrace trace={trace} currency="ARS" />);
    const steps = screen.getAllByRole("listitem");
    expect(steps).toHaveLength(trace.length);
    expect(steps[0]).toHaveTextContent("#Original1.210,00");
    expect(steps[1]).toHaveTextContent("÷VAT removed1000.00");
    expect(steps[2]).toHaveTextContent("=Final cost1000.00 ARS✱");
  });

  it("shortens long intermediate decimals for reading but keeps the exact value in a tooltip", () => {
    const long = "1720.66115702479338842975206611570247933884297520661157";
    renderWithI18n(
      <StepTrace
        trace={[
          { step: "strip_vat", value: long },
          { step: "rounding", value: "1720.66" },
        ]}
        currency="ARS"
      />,
    );
    const shown = screen.getByText("1720.6611…");
    expect(shown).toHaveAttribute("title", long);
    expect(screen.getByText("1720.66 ARS")).not.toHaveAttribute("title");
  });

  it("falls back to the raw step name for a step it does not know", () => {
    renderWithI18n(<StepTrace trace={[{ step: "new_step", value: "1" }]} currency={null} />);
    expect(screen.getByText("new_step")).toBeInTheDocument();
  });
});

describe("CountsSummary", () => {
  it("shows accepted plus rejected equal to the data rows", () => {
    renderWithI18n(<CountsSummary totals={previewPage().totals} />);
    expect(screen.getByLabelText("Accepted")).toHaveTextContent("5");
    expect(screen.getByLabelText("Rejected")).toHaveTextContent("1");
    expect(screen.getByLabelText("Data rows")).toHaveTextContent("6");
  });

  it("states the skipped rows so nothing disappears unexplained", () => {
    renderWithI18n(<CountsSummary totals={previewPage().totals} />);
    expect(screen.getByText(/Not counted as products: 1 empty, 1 total, 1 preamble/)).toBeInTheDocument();
  });

  it("flags a mismatch instead of hiding it", () => {
    const totals = { ...previewPage().totals, data_rows: 9 };
    renderWithI18n(<CountsSummary totals={totals} />);
    expect(screen.getByRole("alert")).toHaveTextContent("do not add up");
  });
});

describe("NoticeList", () => {
  it("renders nothing without notices", () => {
    const { container } = renderWithI18n(<NoticeList notices={[]} />);
    expect(container.querySelector("[role=status]")).toBeNull();
  });

  it("explains model_unavailable in plain words and keeps the server detail", () => {
    renderWithI18n(
      <NoticeList notices={[{ code: "model_unavailable", message: "connection refused", stage: "gemma" }]} />,
    );
    const notice = screen.getByRole("status");
    expect(notice).toHaveTextContent("Gemma was not available");
    expect(notice).toHaveTextContent("connection refused");
  });

  it("shows other notices with the server message", () => {
    renderWithI18n(<NoticeList notices={[{ code: "other", message: "Something to know", stage: null }]} />);
    expect(screen.getByRole("status")).toHaveTextContent("Something to know");
  });
});

describe("QuestionCard", () => {
  const suggestion = { suggested_by: "gemma", option: "USD", confidence: 0.6, calibrated: false, evidence: [] };

  it("never preselects an option, even when the model made a suggestion", () => {
    renderWithI18n(<QuestionCard question={question({ suggestion })} answer={undefined} onAnswer={vi.fn()} />);

    const radios = screen.getAllByRole("radio");
    expect(radios).toHaveLength(2);
    expect(radios.every((radio) => !(radio as HTMLInputElement).checked)).toBe(true);
    expect(screen.getByText("GEMMA ~.6")).toHaveAttribute("title", "Suggested by Gemma (uncalibrated: 0.6)");
  });

  it("puts the suggestion badge on the suggested option only", () => {
    renderWithI18n(<QuestionCard question={question({ suggestion })} answer={undefined} onAnswer={vi.fn()} />);
    const usd = screen.getByRole("radio", { name: /US dollars/ }).closest("label")!;
    const ars = screen.getByRole("radio", { name: /Argentine pesos/ }).closest("label")!;
    expect(within(usd).getByText("GEMMA ~.6")).toHaveAttribute("title", "Suggested by Gemma (uncalibrated: 0.6)");
    expect(within(ars).queryByText(/GEMMA/)).toBeNull();
  });

  it("reports the token the user picks", async () => {
    const onAnswer = vi.fn();
    renderWithI18n(<QuestionCard question={question()} answer={undefined} onAnswer={onAnswer} />);
    await userEvent.click(screen.getByRole("radio", { name: /Argentine pesos/ }));
    expect(onAnswer).toHaveBeenCalledWith("currency", "ARS");
  });

  it("marks the stored answer as chosen", () => {
    renderWithI18n(<QuestionCard question={question()} answer="USD" onAnswer={vi.fn()} />);
    expect(screen.getByRole("radio", { name: /US dollars/ })).toBeChecked();
  });

  it("asks in the interface language", () => {
    renderWithI18n(<QuestionCard question={question()} answer={undefined} onAnswer={vi.fn()} />, "es");
    expect(screen.getByText("¿En qué moneda están los precios?")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /Pesos argentinos/ })).toBeInTheDocument();
  });

  it("accepts a custom constant when the question allows it", async () => {
    const onAnswer = vi.fn();
    renderWithI18n(
      <QuestionCard question={question({ id: "vat_rate", allows_custom: true })} answer={undefined} onAnswer={onAnswer} />,
    );
    await userEvent.type(screen.getByLabelText("Another value"), "27");
    await userEvent.click(screen.getByRole("button", { name: "Use this value" }));
    expect(onAnswer).toHaveBeenCalledWith("vat_rate", "constant:27");
  });
});
