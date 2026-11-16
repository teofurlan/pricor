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

function TracePrint({ trace, currency, convertedCurrency, animate, announce }: {
  trace: TraceStep[]; currency: string | null; convertedCurrency: string | null; animate: boolean; announce: boolean;
}) {
  const { t, language } = useI18n();
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
      {announce && <p className="sr-only" role="status" aria-live="polite" aria-atomic="true">{complete && result ? `${t("trace.rounding")}: ${result}` : ""}</p>}
      {complete && <div className="tape__tear" aria-hidden="true" />}
    </>
  );
}
