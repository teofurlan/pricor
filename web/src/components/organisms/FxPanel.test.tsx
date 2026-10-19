import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { fxState, previewItem, previewPage, question } from "../../test/fixtures";
import { renderWithI18n } from "../../test/render";
import { SuggestionBadge } from "../molecules/SuggestionBadge";
import { FxPanel } from "./FxPanel";
import { PreviewTable } from "./PreviewTable";
import { QuestionsPanel } from "./QuestionsPanel";

const noop = () => undefined;

function snapshot(overrides: Partial<NonNullable<ReturnType<typeof fxState>["snapshot"]>> = {}) {
  return { ...fxState().snapshot!, ...overrides };
}

describe("FxPanel", () => {
  it("shows the rate used with its type, side, source and date", () => {
    renderWithI18n(<FxPanel fx={fxState()} busy={false} onManual={noop} onRefresh={noop} />);

    expect(screen.getByText("1 USD = 1535 ARS")).toBeInTheDocument();
    expect(screen.getByText("Rate: oficial, venta")).toBeInTheDocument();
    expect(screen.getByText("Source: dolarapi")).toBeInTheDocument();
    expect(screen.getByText("Quoted 2026-10-14")).toBeInTheDocument();
    expect(screen.queryByText(/Stale/)).not.toBeInTheDocument();
  });

  it("flags a cached quote used offline as stale", () => {
    renderWithI18n(
      <FxPanel fx={fxState({ snapshot: snapshot({ stale: true }) })} busy={false} onManual={noop} onRefresh={noop} />,
    );

    expect(screen.getByText("Stale: offline, last saved quote")).toBeInTheDocument();
  });

  it("marks a rate the user typed", () => {
    renderWithI18n(
      <FxPanel
        fx={fxState({ snapshot: snapshot({ source: "manual", rate_type: "manual" }) })}
        busy={false}
        onManual={noop}
        onRefresh={noop}
      />,
    );

    expect(screen.getByText("Typed by you")).toBeInTheDocument();
  });

  it("explains that a rate is needed, and why the live one failed, when there is none", () => {
    renderWithI18n(
      <FxPanel
        fx={fxState({ snapshot: null, error: "cannot reach DolarAPI" })}
        busy={false}
        onManual={noop}
        onRefresh={noop}
      />,
    );

    expect(screen.getByText(/never guesses/)).toBeInTheDocument();
    expect(screen.getByText("Could not get a live rate: cannot reach DolarAPI")).toBeInTheDocument();
    expect(screen.queryByText(/^1 USD =/)).not.toBeInTheDocument();
  });

  it("sends the typed rate and cannot send an empty one", async () => {
    const onManual = vi.fn();
    renderWithI18n(<FxPanel fx={fxState({ snapshot: null })} busy={false} onManual={onManual} onRefresh={noop} />);
    const use = screen.getByRole("button", { name: "Use this rate" });
    expect(use).toBeDisabled();

    await userEvent.type(screen.getByLabelText("Rate typed by you (USD to ARS)"), "1420,50");
    await userEvent.click(use);

    expect(onManual).toHaveBeenCalledWith("1420,50");
  });

  it("asks for the live rate again", async () => {
    const onRefresh = vi.fn();
    renderWithI18n(<FxPanel fx={fxState()} busy={false} onManual={noop} onRefresh={onRefresh} />);

    await userEvent.click(screen.getByRole("button", { name: "Get the live rate again" }));

    expect(onRefresh).toHaveBeenCalled();
  });

  it("never offers the live source when the plan uses a typed rate", () => {
    renderWithI18n(
      <FxPanel fx={fxState({ rate_type: "manual", snapshot: null })} busy={false} onManual={noop} onRefresh={noop} />,
    );

    expect(screen.queryByRole("button", { name: "Get the live rate again" })).not.toBeInTheDocument();
  });

  it("speaks Spanish", () => {
    renderWithI18n(<FxPanel fx={fxState()} busy={false} onManual={noop} onRefresh={noop} />, "es");

    expect(screen.getByText("Cotización: oficial, venta")).toBeInTheDocument();
  });
});

describe("converted costs in the preview", () => {
  const converted = previewItem({
    row_number: 4,
    record: {
      supplier_code: "A2",
      description: "Antenna",
      unit_cost_net: "2.50",
      currency: "USD",
      unit_cost_net_converted: "3837.50",
    },
    trace: [
      { step: "original", value: "2.50" },
      { step: "parse_number", value: "2.50" },
      { step: "rounding", value: "2.50" },
      { step: "convert_currency", value: "3837.50" },
    ],
  });

  it("adds a converted column and names the conversion step", async () => {
    renderWithI18n(
      <PreviewTable page={previewPage({ items: [converted, previewItem()] })} busy={false} onPage={noop} fx={fxState()} />,
    );

    expect(screen.getByRole("columnheader", { name: "Converted (ARS)" })).toBeInTheDocument();
    expect(screen.getAllByText("3837.50 ARS").length).toBeGreaterThan(0);
    expect(await screen.findByText("2.50 USD")).toBeInTheDocument(); // the original stays visible as the tape prints
    expect(await screen.findByText("Converted")).toBeInTheDocument();
  });

  it("has no converted column when nothing is converted", () => {
    renderWithI18n(<PreviewTable page={previewPage()} busy={false} onPage={noop} fx={null} />);

    expect(screen.queryByRole("columnheader", { name: /Converted/ })).not.toBeInTheDocument();
  });
});

describe("conversion question", () => {
  it("cannot move on while a rate is still required", () => {
    renderWithI18n(
      <QuestionsPanel questions={[question()]} answers={{ currency: "USD" }} busy={false} blocked onAnswer={noop} onContinue={noop} />,
    );

    expect(screen.getByRole("button", { name: "See the preview" })).toBeDisabled();
  });

  it("labels a default from the settings instead of blaming Gemma", () => {
    renderWithI18n(
      <SuggestionBadge
        suggestion={{ suggested_by: "setting", option: "oficial:venta", confidence: 1, calibrated: true, evidence: [] }}
      />,
    );

    expect(screen.getByText("YOUR DEFAULT")).toBeInTheDocument();
  });
});
