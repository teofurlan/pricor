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
import { AskGemma } from "./AskGemma";
import { ServerConfigProvider } from "../../api/serverConfig";
import type { Memory } from "../../api/types";

describe("ProvenanceBadge", () => {
  it.each([
    ["heuristics", "Automatic detection"],
    ["gemma", "Automatic suggestion"],
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

  it("puts an automatic suggestion in plain words", () => {
    renderWithI18n(<SuggestionBadge suggestion={suggestion} />);
    expect(screen.getByText("Automatic suggestion · medium confidence")).toHaveAttribute("title", "Suggested automatically, medium confidence (60%). Check it before accepting.");
  });

  it("treats the server label 'model', the only advisor behind it", () => {
    renderWithI18n(<SuggestionBadge suggestion={{ ...suggestion, suggested_by: "model", confidence: 0.4 }} />);
    expect(screen.getByText("Automatic suggestion · low confidence")).toHaveAttribute("title", "Suggested automatically, low confidence (40%). Check it before accepting.");
  });

  it("labels a value read from the file as detected, with no model confidence", () => {
    renderWithI18n(
      <SuggestionBadge suggestion={{ ...suggestion, suggested_by: "detected", confidence: 1, calibrated: true }} />,
    );
    expect(screen.getByText("DETECTED · confirm or change")).toBeInTheDocument();
  });

  it("drops the warning once the confidence is calibrated", () => {
    renderWithI18n(<SuggestionBadge suggestion={{ ...suggestion, calibrated: true }} />);
    expect(screen.getByText("Automatic suggestion · medium confidence")).toHaveAttribute("title", "Suggested automatically, medium confidence (60%).");
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
    expect(steps[1]).toHaveTextContent("÷VAT removed1,000.00");
    expect(steps[2]).toHaveTextContent("=Cost without VAT1,000.00 ARS✱");
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
    const shown = screen.getByText((_, el) => Boolean(el?.classList.contains("trace__value") && el?.textContent === "1,720.6611…"));
    expect(shown).toHaveAttribute("title", long);
    const finalVal = screen.getByText((_, el) => Boolean(el?.classList.contains("trace__value") && el?.textContent === "1,720.66 ARS"));
    expect(finalVal).not.toHaveAttribute("title");
  });

  it("prints Spanish figures with the thousands dot and keeps the decimal column aligned", () => {
    renderWithI18n(
      <StepTrace trace={[{ step: "original", value: "3387" }, { step: "rounding", value: "3387.84" }]} currency="ARS" />,
      "es",
    );
    const values = Array.from(document.querySelectorAll(".trace__value"));
    expect(values[0]).toHaveTextContent("3.387");
    expect(values[1]).toHaveTextContent("3.387,84 ARS");
    expect(values[1].querySelector(".num-int")).toHaveTextContent("3.387");
    expect(values[1].querySelector(".num-frac")).toHaveTextContent(",84 ARS");
    expect(values[0].querySelector(".num-frac")).toBeEmptyDOMElement();
  });

  it("falls back to the raw step name for a step it does not know", () => {
    renderWithI18n(<StepTrace trace={[{ step: "new_step", value: "1" }]} currency={null} />);
    expect(screen.getByText("new_step")).toBeInTheDocument();
  });
});

describe("StepTrace unchanged steps", () => {
  const noop = [
    { step: "original", value: "3387.84" },
    { step: "parse_number", value: "3387.84" },
    { step: "apply_discounts", value: "3387.84" },
    { step: "strip_vat", value: "3387.84" },
    { step: "per_unit", value: "3387.84" },
    { step: "rounding", value: "3387.84" },
  ];

  it("keeps the original and the final cost and summarizes the steps that changed nothing", () => {
    renderWithI18n(<StepTrace trace={noop} currency="ARS" />);
    const steps = screen.getAllByRole("listitem");
    expect(steps).toHaveLength(2);
    expect(steps[0]).toHaveTextContent("#Original3,387.84");
    expect(steps[1]).toHaveTextContent("=Final cost3,387.84 ARS✱");
    expect(screen.getByText("No discounts · no VAT to remove · already a unit price")).toBeInTheDocument();
  });

  it("says the same in Spanish, with the first word capitalized and the Argentine format", () => {
    renderWithI18n(<StepTrace trace={noop} currency="ARS" />, "es");
    expect(screen.getAllByRole("listitem")[1]).toHaveTextContent("=Costo unitario3.387,84 ARS✱");
    expect(screen.getByText("Sin descuentos · sin IVA para quitar · ya es precio por unidad")).toBeInTheDocument();
    expect(screen.queryByText(/número|redondeado/)).toBeNull();
  });

  it("shows the VAT step when it changes the value and leaves it out of the summary", () => {
    const withVat = [
      { step: "original", value: "1210.00" },
      { step: "parse_number", value: "1210.00" },
      { step: "apply_discounts", value: "1210.00" },
      { step: "strip_vat", value: "1000.00" },
      { step: "per_unit", value: "1000.00" },
      { step: "rounding", value: "1000.00" },
    ];
    renderWithI18n(<StepTrace trace={withVat} currency="ARS" />);
    const steps = screen.getAllByRole("listitem");
    expect(steps).toHaveLength(3);
    expect(steps[1]).toHaveTextContent("÷VAT removed1,000.00");
    const summary = screen.getByText(/^No discounts/);
    expect(summary).toHaveTextContent("No discounts · already a unit price");
    expect(summary).not.toHaveTextContent(/VAT/);
  });

  it("shows the per-unit step when it changes the value", () => {
    renderWithI18n(
      <StepTrace trace={[
        { step: "original", value: "120.00" },
        { step: "strip_vat", value: "120.00" },
        { step: "per_unit", value: "10.00" },
        { step: "rounding", value: "10.00" },
      ]} currency="ARS" />,
    );
    expect(screen.getAllByRole("listitem")[1]).toHaveTextContent("÷Per unit10.00");
    expect(screen.getByText("No VAT to remove")).toBeInTheDocument();
  });

  it("shows the reading step when the original text is not already a plain number", () => {
    renderWithI18n(
      <StepTrace trace={[
        { step: "original", value: "$ 3.387,84" },
        { step: "parse_number", value: "3387.84" },
        { step: "rounding", value: "3387.84" },
      ]} currency="ARS" />,
      "es",
    );
    expect(screen.getAllByRole("listitem")[1]).toHaveTextContent("◇Leído como número3.387,84");
    expect(screen.queryByText(/Ya es un número/)).toBeNull();
  });

  it("compares exact decimal values, not their spelling, and prints no line when nothing was hidden", () => {
    renderWithI18n(
      <StepTrace trace={[
        { step: "original", value: "100" },
        { step: "apply_discounts", value: "100.00" },
        { step: "rounding", value: "100.00" },
      ]} currency="ARS" />,
    );
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    expect(screen.getByText("No discounts")).toBeInTheDocument();
    const { container } = renderWithI18n(<StepTrace trace={[{ step: "original", value: "100" }, { step: "rounding", value: "100.01" }]} currency="ARS" />);
    expect(container.querySelector(".trace__skipped")).toBeNull();
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

  it("explains a model notice in Spanish and keeps the error only as technical detail", () => {
    renderWithI18n(
      <NoticeList
        notices={[{ code: "model_unavailable", message: "stage 'gemma' could not classify columns (ModelUnavailableError): connection refused", stage: "gemma" }]}
      />,
      "es",
    );
    const notice = screen.getByRole("status");
    expect(notice).toHaveTextContent("Gemma no estaba disponible");
    expect(notice).toHaveTextContent("La etapa 'gemma' no pudo clasificar las columnas.");
    expect(notice).toHaveTextContent("Detalle técnico: ModelUnavailableError: connection refused");
    expect(notice).not.toHaveTextContent("could not classify columns");
  });

  it("shows other notices with the server message", () => {
    renderWithI18n(<NoticeList notices={[{ code: "other", message: "Something to know", stage: null }]} />);
    expect(screen.getByRole("status")).toHaveTextContent("Something to know");
  });

  it("shows compact one-line version with title only when compact is true", () => {
    renderWithI18n(
      <NoticeList
        compact
        notices={[{ code: "model_unavailable", message: "stage 'gemma' could not classify columns (ModelUnavailableError): connection refused", stage: "gemma" }]}
      />,
      "es",
    );
    const notice = screen.getByRole("status");
    expect(notice).toHaveTextContent("Gemma no estaba disponible");
    expect(notice).not.toHaveTextContent("La etapa 'gemma' no pudo clasificar las columnas.");
    expect(notice).not.toHaveTextContent("Detalle técnico");
    expect(notice).not.toHaveTextContent("La importación sigue solo con detección automática");
  });

  it("does not blame Gemma for another stage that was skipped or failed", () => {
    renderWithI18n(
      <ServerConfigProvider hosted={true}>
        <NoticeList
          compact
          notices={[{ code: "model_unavailable", message: "stage 'laya' was skipped: the 'laya' extra is not installed", stage: "laya" }]}
        />
      </ServerConfigProvider>,
      "es",
    );
    const notice = screen.getByRole("status");
    expect(notice).toHaveTextContent("Un paso automático no estaba disponible");
    expect(notice).not.toHaveTextContent("Gemma");
  });

  it("names Gemma when the plan advisor is the one that failed", () => {
    renderWithI18n(
      <ServerConfigProvider hosted={true}>
        <NoticeList
          compact
          notices={[{ code: "model_unavailable", message: "the plan advisor could not help (ModelTimeoutError): slow", stage: "advisor" }]}
        />
      </ServerConfigProvider>,
      "es",
    );
    expect(screen.getByRole("status")).toHaveTextContent("Gemma no respondió");
  });

  it("shows hosted-aware title when hosted is true", () => {
    renderWithI18n(
      <ServerConfigProvider hosted={true}>
        <NoticeList notices={[{ code: "model_unavailable", message: "connection refused", stage: "gemma" }]} />
      </ServerConfigProvider>,
    );
    expect(screen.getByRole("status")).toHaveTextContent("Gemma did not answer");
  });

  it("shows hosted-aware title in Spanish when hosted is true", () => {
    renderWithI18n(
      <ServerConfigProvider hosted={true}>
        <NoticeList notices={[{ code: "model_unavailable", message: "connection refused", stage: "gemma" }]} />
      </ServerConfigProvider>,
      "es",
    );
    expect(screen.getByRole("status")).toHaveTextContent("Gemma no respondió");
  });
});

describe("AskGemma", () => {
  it("shows local waiting text while pending by default", () => {
    renderWithI18n(<AskGemma thread={[]} pending={true} error={null} onAsk={vi.fn()} />);
    expect(screen.getByText("Gemma is thinking. Local models can take up to a minute.")).toBeInTheDocument();
  });

  it("shows local waiting text in Spanish while pending by default", () => {
    renderWithI18n(<AskGemma thread={[]} pending={true} error={null} onAsk={vi.fn()} />, "es");
    expect(screen.getByText("Gemma está pensando. Los modelos locales pueden tardar hasta un minuto.")).toBeInTheDocument();
  });

  it("shows hosted waiting text while pending in hosted mode", () => {
    renderWithI18n(
      <ServerConfigProvider hosted={true}>
        <AskGemma thread={[]} pending={true} error={null} onAsk={vi.fn()} />
      </ServerConfigProvider>,
    );
    expect(screen.getByText("Gemma is thinking. This can take up to a minute.")).toBeInTheDocument();
  });

  it("shows hosted waiting text in Spanish while pending in hosted mode", () => {
    renderWithI18n(
      <ServerConfigProvider hosted={true}>
        <AskGemma thread={[]} pending={true} error={null} onAsk={vi.fn()} />
      </ServerConfigProvider>,
      "es",
    );
    expect(screen.getByText("Gemma está pensando. Puede demorar hasta un minuto.")).toBeInTheDocument();
  });
});

describe("QuestionCard", () => {
  const suggestion = { suggested_by: "gemma", option: "USD", confidence: 0.6, calibrated: false, evidence: [] };

  it("never preselects an option, even when the model made a suggestion", () => {
    renderWithI18n(<QuestionCard question={question({ suggestion })} answer={undefined} onAnswer={vi.fn()} />);

    const buttons = screen.getAllByRole("button");
    expect(buttons).toHaveLength(2);
    expect(buttons.every((button) => button.getAttribute("aria-pressed") === "false")).toBe(true);
    expect(screen.getByText("Automatic suggestion · medium confidence")).toHaveAttribute("title", "Suggested automatically, medium confidence (60%). Check it before accepting.");
  });

  it("does not commit an option when navigating with keyboard arrow keys", async () => {
    const onAnswer = vi.fn();
    renderWithI18n(<QuestionCard question={question()} answer={undefined} onAnswer={onAnswer} />);
    const first = screen.getByRole("button", { name: /Argentine pesos/ });
    first.focus();
    await userEvent.keyboard("{ArrowDown}{ArrowRight}");
    expect(onAnswer).not.toHaveBeenCalled();
  });

  it("puts the suggestion badge on the suggested option only", () => {
    renderWithI18n(<QuestionCard question={question({ suggestion })} answer={undefined} onAnswer={vi.fn()} />);
    const usd = screen.getByRole("button", { name: /US dollars/ });
    const ars = screen.getByRole("button", { name: /Argentine pesos/ });
    expect(within(usd).getByText("Automatic suggestion · medium confidence")).toHaveAttribute("title", "Suggested automatically, medium confidence (60%). Check it before accepting.");
    expect(within(ars).queryByText(/Automatic suggestion/)).toBeNull();
  });

  it("reports the token the user picks", async () => {
    const onAnswer = vi.fn();
    renderWithI18n(<QuestionCard question={question()} answer={undefined} onAnswer={onAnswer} />);
    await userEvent.click(screen.getByRole("button", { name: /Argentine pesos/ }));
    expect(onAnswer).toHaveBeenCalledWith("currency", "ARS");
  });

  it("marks the stored answer as chosen", () => {
    renderWithI18n(<QuestionCard question={question()} answer="USD" onAnswer={vi.fn()} />);
    expect(screen.getByRole("button", { name: /US dollars/ })).toHaveAttribute("aria-pressed", "true");
  });

  it("explains why it asks in Spanish", () => {
    renderWithI18n(<QuestionCard question={question({ reason: "the currency of the prices is not known" })} answer={undefined} onAnswer={vi.fn()} />, "es");
    expect(screen.getByText("Por qué lo preguntamos: no se sabe en qué moneda están los precios")).toBeInTheDocument();
  });

  it("shows a typed value the way the interface language writes it", () => {
    const vat = question({ id: "vat_rate", allows_custom: true });
    const { unmount } = renderWithI18n(<QuestionCard question={vat} answer="constant:10.5" onAnswer={vi.fn()} />, "es");
    expect(screen.getByText("Su valor: 10,5 %")).toBeInTheDocument();
    unmount();
    renderWithI18n(<QuestionCard question={vat} answer="constant:10.5" onAnswer={vi.fn()} />);
    expect(screen.getByText("Your value: 10.5%")).toBeInTheDocument();
  });

  it("asks in the interface language", () => {
    renderWithI18n(<QuestionCard question={question()} answer={undefined} onAnswer={vi.fn()} />, "es");
    expect(screen.getByText("¿En qué moneda están los precios?")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Pesos argentinos/ })).toBeInTheDocument();
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

  it("refuses a custom value that is not a number and says why", async () => {
    const onAnswer = vi.fn();
    renderWithI18n(
      <QuestionCard question={question({ id: "vat_rate", allows_custom: true })} answer={undefined} onAnswer={onAnswer} />,
    );
    await userEvent.type(screen.getByLabelText("Another value"), "45,sfdgsdfgsd");
    expect(screen.getByRole("button", { name: "Use this value" })).toBeDisabled();
    expect(screen.getByText("Enter a percentage between 0 and 100, such as 10,5.")).toBeInTheDocument();
    expect(onAnswer).not.toHaveBeenCalled();
  });

  it("accepts a decimal comma and sends the value with a decimal point", async () => {
    const onAnswer = vi.fn();
    renderWithI18n(
      <QuestionCard question={question({ id: "vat_rate", allows_custom: true })} answer={undefined} onAnswer={onAnswer} />,
    );
    await userEvent.type(screen.getByLabelText("Another value"), "10,5");
    await userEvent.click(screen.getByRole("button", { name: "Use this value" }));
    expect(onAnswer).toHaveBeenCalledWith("vat_rate", "constant:10.5");
  });

  it("refuses a VAT rate above 100 and a pack of zero units", async () => {
    const { unmount } = renderWithI18n(
      <QuestionCard question={question({ id: "vat_rate", allows_custom: true })} answer={undefined} onAnswer={vi.fn()} />,
    );
    await userEvent.type(screen.getByLabelText("Another value"), "150");
    expect(screen.getByRole("button", { name: "Use this value" })).toBeDisabled();
    unmount();

    renderWithI18n(
      <QuestionCard question={question({ id: "units_per_pack", allows_custom: true })} answer={undefined} onAnswer={vi.fn()} />,
    );
    await userEvent.type(screen.getByLabelText("Another value"), "0");
    expect(screen.getByRole("button", { name: "Use this value" })).toBeDisabled();
    expect(screen.getByText("Enter a number greater than 0, such as 12.")).toBeInTheDocument();
  });
});

describe("QuestionCard with grouped options", () => {
  const grouped = question({
    id: "fx_conversion",
    text: { en: "Convert?", es: "¿Se convierte?" },
    options: [
      { token: "keep", label: { en: "Keep", es: "Mantener" }, group: "primary" },
      { token: "oficial:venta", label: { en: "Official, sell", es: "Oficial, venta" }, group: "primary" },
      { token: "manual", label: { en: "Type a rate", es: "Escribir cotización" }, group: "primary" },
      { token: "blue:venta", label: { en: "Blue, sell", es: "Blue, venta" }, group: "more" },
      { token: "bolsa:compra", label: { en: "MEP, buy", es: "MEP, compra" }, group: "more" },
    ],
  });

  it("keeps the primary options as buttons and puts the rest in one labeled select", () => {
    renderWithI18n(<QuestionCard question={grouped} answer={undefined} onAnswer={vi.fn()} />);

    expect(screen.getAllByRole("button").map((button) => button.textContent)).toEqual(["Keep", "Official, sell", "Type a rate"]);
    const select = screen.getByRole("combobox", { name: "Another rate…" });
    expect(within(select).getAllByRole("option").map((option) => option.textContent)).toEqual(["Another rate…", "Blue, sell", "MEP, buy"]);
    expect(select).toHaveValue("");
  });

  it("answers exactly like a button when a rate is picked from the select", async () => {
    const onAnswer = vi.fn();
    renderWithI18n(<QuestionCard question={grouped} answer={undefined} onAnswer={onAnswer} />);

    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Another rate…" }), "bolsa:compra");

    expect(onAnswer).toHaveBeenCalledWith("fx_conversion", "bolsa:compra");
  });

  it("shows a stored answer that lives in the select as selected, and no button as pressed", () => {
    renderWithI18n(<QuestionCard question={grouped} answer="blue:venta" onAnswer={vi.fn()} />);

    expect(screen.getByRole("combobox", { name: "Another rate…" })).toHaveValue("blue:venta");
    expect(screen.getAllByRole("button").every((button) => button.getAttribute("aria-pressed") === "false")).toBe(true);
  });

  it("marks a suggestion that lives in the select without choosing it", () => {
    const suggestion = { suggested_by: "gemma", option: "blue:venta", confidence: 0.7, calibrated: false, evidence: [] };
    renderWithI18n(<QuestionCard question={{ ...grouped, suggestion }} answer={undefined} onAnswer={vi.fn()} />);

    const select = screen.getByRole("combobox", { name: "Another rate…" });
    expect(select).toHaveValue("");
    expect(screen.getByText("Automatic suggestion · medium confidence")).toBeInTheDocument();
  });

  it("labels the select in Spanish", () => {
    renderWithI18n(<QuestionCard question={grouped} answer={undefined} onAnswer={vi.fn()} />, "es");

    expect(screen.getByRole("combobox", { name: "Otra cotización…" })).toBeInTheDocument();
  });

  it("renders questions without groups exactly as before", () => {
    renderWithI18n(<QuestionCard question={question()} answer={undefined} onAnswer={vi.fn()} />);

    expect(screen.queryByRole("combobox")).toBeNull();
    expect(screen.getAllByRole("button")).toHaveLength(2);
  });
});

describe("StepTrace conversion", () => {
  const converted = [
    { step: "parse_number", value: "2.588" },
    { step: "rounding", value: "2.59" },
    { step: "convert_currency", value: "4011.40", source: "2.588", rate: "1550" },
  ];

  it("shows the unrounded source and the rate under the conversion step", () => {
    renderWithI18n(<StepTrace trace={converted} currency="USD" convertedCurrency="ARS" />, "es");

    expect(screen.getByText("2,588 USD × 1.550 = 4.011,40 ARS")).toBeInTheDocument();
  });

  it("uses the language's number format in English", () => {
    renderWithI18n(<StepTrace trace={converted} currency="USD" convertedCurrency="ARS" />);

    expect(screen.getByText("2.588 USD × 1,550 = 4,011.40 ARS")).toBeInTheDocument();
  });

  it("prints nothing extra when the server sent no source", () => {
    renderWithI18n(<StepTrace trace={[converted[1], { step: "convert_currency", value: "4011.40" }]} currency="USD" convertedCurrency="ARS" />);

    expect(screen.queryByText(/×/)).toBeNull();
  });
});
