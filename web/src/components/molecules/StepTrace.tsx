import { useEffect, useState } from "react";
import type { Language, TraceStep } from "../../api/types";
import { isTextKey, useI18n } from "../../i18n";
import { conversionText, formatDecimalText, formatFigure } from "../../lib/decimalText";
import { splitFigure, TapeFigure } from "../atoms/TapeFigure";

const LONG_DECIMAL = /^(-?\d+)\.(\d{7,})$/;
const OPERATORS: Record<string, string> = {
  original: "#", parse_number: "◇", apply_discounts: "×", strip_vat: "÷",
  per_unit: "÷", rounding: "=", convert_currency: "×",
};

/** Display shortening only; the exact intermediate value remains available on hover. */
function readable(value: string, language: Language): { text: string; full?: string } {
  const match = LONG_DECIMAL.exec(value);
  return match
    ? { text: `${formatDecimalText(`${match[1]}.${match[2].slice(0, 4)}`, language)}…`, full: value }
    : { text: formatDecimalText(value, language) };
}

export function decimalTail(text: string, language: Language = "en"): number {
  return splitFigure(text, language).fracPart.length;
}

const PLAIN_NUMBER = /^(-?)0*(\d+)(?:\.(\d*?)0*)?$/;
/** Exact decimal identity without floats: "100", "100.00" and "0100.0" are the same number; text is never a plain number. */
function plainNumber(value: string): string | null {
  const match = PLAIN_NUMBER.exec(value.trim());
  if (!match) return null;
  const [, sign, whole, fraction = ""] = match;
  return fraction ? `${sign}${whole}.${fraction}` : whole === "0" ? "0" : `${sign}${whole}`;
}

const SKIPPED_TEXT = {
  parse_number: "trace.skip.parse_number",
  apply_discounts: "trace.skip.apply_discounts",
  strip_vat: "trace.skip.strip_vat",
  per_unit: "trace.skip.per_unit",
  rounding: "trace.skip.rounding",
} as const;

/**
 * Keep the first and last lines, and any known step whose value differs from the previous kept one.
 * Unknown steps are always kept; a step is never hidden unless its effect is known to be nil.
 */
export function visibleSteps(trace: TraceStep[], currency: string | null, convertedCurrency: string | null) {
  const shown: TraceStep[] = [];
  const hidden: TraceStep[] = [];
  let previous: TraceStep | null = null;
  trace.forEach((item, position) => {
    const known = item.step in SKIPPED_TEXT;
    const exact = plainNumber(item.value);
    const unchanged = previous !== null && exact !== null && exact === plainNumber(previous.value);
    const sameCurrency = item.step !== "convert_currency" || convertedCurrency === currency;
    if (position === 0 || position === trace.length - 1 || !known || !unchanged || !sameCurrency) {
      shown.push(item);
      previous = item;
    } else {
      hidden.push(item);
    }
  });
  return { shown, hidden };
}

function useReducedMotion() {
  const [reduced, setReduced] = useState(() => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false);
  useEffect(() => {
    const query = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    if (!query) return;
    const change = () => setReduced(query.matches);
    query.addEventListener("change", change);
    return () => query.removeEventListener("change", change);
  }, []);
  return reduced;
}

/** Only server-provided steps are printed: an operation's value is its result, not an inferred operand. */
export function StepTrace({
  trace, currency, convertedCurrency = null, animate = false, announce = animate,
}: {
  trace: TraceStep[];
  currency: string | null;
  convertedCurrency?: string | null;
  animate?: boolean;
  /** Announce the final cost to screen readers; defaults to `animate`. */
  announce?: boolean;
}) {
  // Replacing a trace cancels the previous print, even when it has the same number of lines.
  return <TracePrint key={JSON.stringify([trace, currency, convertedCurrency])} trace={trace} currency={currency} convertedCurrency={convertedCurrency} animate={animate} announce={announce} />;
}

function TracePrint({ trace: fullTrace, currency, convertedCurrency, animate, announce }: {
  trace: TraceStep[]; currency: string | null; convertedCurrency: string | null; animate: boolean; announce: boolean;
}) {
  const { t, language } = useI18n();
  const { shown: trace, hidden } = visibleSteps(fullTrace, currency, convertedCurrency);
  // Reading and rounding are technical: when they change nothing they hide without being named.
  const skipped = hidden
    .filter((item) => item.step !== "parse_number" && item.step !== "rounding")
    .map((item) => t(SKIPPED_TEXT[item.step as keyof typeof SKIPPED_TEXT]))
    .map((text, index) => (index === 0 ? text.charAt(0).toUpperCase() + text.slice(1) : text))
    .join(" · ");
  const reduced = useReducedMotion();
  const [printed, setPrinted] = useState(1);
  const count = !animate || reduced ? trace.length : printed;
  const complete = count >= trace.length;
  useEffect(() => {
    if (!animate || reduced || complete) return;
    const timer = window.setTimeout(() => setPrinted((current) => current + 1), 70);
    return () => window.clearTimeout(timer);
  }, [animate, reduced, complete, printed]);
  const last = trace.at(-1);
  const lastCurrency = last?.step === "convert_currency" ? convertedCurrency : currency;
  const result = last && ["rounding", "convert_currency"].includes(last.step)
    ? `${formatDecimalText(last.value, language)}${lastCurrency ? ` ${lastCurrency}` : ""}` : null;
  const shownValues = trace.map((item) => {
    const unit = item.step === "convert_currency" ? convertedCurrency : currency;
    return ["rounding", "convert_currency"].includes(item.step)
      ? { text: formatFigure(unit ? `${item.value} ${unit}` : item.value, language) }
      : readable(item.value, language);
  });
  const decimalColumn = Math.max(0, ...shownValues.map((value) => splitFigure(value.text, language).fracPart.length));
  return (
    <>
      <ol className={`trace${animate && !reduced ? " trace--printing" : ""}`}>
        {trace.slice(0, count).map((item, position) => {
          const key = `trace.${item.step}`;
          const label = isTextKey(key) ? t(key) : item.step;
          const isTotal = position === trace.length - 1 && result !== null;
          const shown = shownValues[position];
          return (
            <li key={`${item.step}-${position}`} className={`trace__step${isTotal ? " trace__step--final" : ""}`}>
              <span className="trace__operator" aria-hidden="true">{isTotal ? "=" : OPERATORS[item.step] ?? "◇"}</span>
              <span className="trace__label">
                {label}
                {item.step === "convert_currency" && item.source !== undefined && item.rate !== undefined && currency && convertedCurrency && (
                  <small className="trace__basis">
                    {conversionText({ source: item.source, rate: item.rate, value: item.value }, currency, convertedCurrency, language)}
                  </small>
                )}
              </span>
              <TapeFigure className="trace__value" language={language} value={shown.text} full={shown.full} fracWidth={decimalColumn} />
              {isTotal && <span className="trace__mark" aria-hidden="true">✱</span>}
            </li>
          );
        })}
      </ol>
      {complete && skipped && <p className="trace__skipped">{skipped}</p>}
      {announce && <p className="sr-only" role="status" aria-live="polite" aria-atomic="true">{complete && result ? `${t("trace.rounding")}: ${result}` : ""}</p>}
      {complete && <div className="tape__tear" aria-hidden="true" />}
    </>
  );
}
