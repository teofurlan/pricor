import { useEffect, useState } from "react";
import type { TraceStep } from "../../api/types";
import { isTextKey, useI18n } from "../../i18n";

const LONG_DECIMAL = /^(-?\d+)\.(\d{7,})$/;
const OPERATORS: Record<string, string> = {
  original: "#", parse_number: "◇", apply_discounts: "×", strip_vat: "÷",
  per_unit: "÷", rounding: "=", convert_currency: "×",
};

/** Display shortening only; the exact intermediate value remains available on hover. */
function readable(value: string): { text: string; full?: string } {
  const match = LONG_DECIMAL.exec(value);
  return match ? { text: `${match[1]}.${match[2].slice(0, 4)}…`, full: value } : { text: value };
}

export function decimalTail(text: string): number {
  const decimalMatch = text.match(/([.,]\d+…?)(\s+\S+)?$/);
  if (decimalMatch) {
    return decimalMatch[0].length;
  }
  const unitMatch = text.match(/\s+\S+$/);
  if (unitMatch) {
    return unitMatch[0].length;
  }
  return 0;
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
  trace, currency, convertedCurrency = null, animate = false,
}: {
  trace: TraceStep[];
  currency: string | null;
  convertedCurrency?: string | null;
  animate?: boolean;
}) {
  // Replacing a trace cancels the previous print, even when it has the same number of lines.
  return <TracePrint key={JSON.stringify([trace, currency, convertedCurrency])} trace={trace} currency={currency} convertedCurrency={convertedCurrency} animate={animate} />;
}

function TracePrint({ trace, currency, convertedCurrency, animate }: {
  trace: TraceStep[]; currency: string | null; convertedCurrency: string | null; animate: boolean;
}) {
  const { t } = useI18n();
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
    ? `${last.value}${lastCurrency ? ` ${lastCurrency}` : ""}` : null;
  const shownValues = trace.map((item) => {
    const unit = item.step === "convert_currency" ? convertedCurrency : currency;
    return ["rounding", "convert_currency"].includes(item.step)
      ? { text: unit ? `${item.value} ${unit}` : item.value }
      : readable(item.value);
  });
  const decimalColumn = Math.max(0, ...shownValues.map((value) => decimalTail(value.text)));
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
              <span className="trace__label">{label}</span>
              <span className="trace__value" title={shown.full} style={{ paddingInlineEnd: `${decimalColumn - decimalTail(shown.text)}ch` }}>{shown.text}</span>
              {isTotal && <span className="trace__mark" aria-hidden="true">✱</span>}
            </li>
          );
        })}
      </ol>
      {animate && <p className="sr-only" role="status" aria-live="polite" aria-atomic="true">{complete && result ? `${t("trace.rounding")}: ${result}` : ""}</p>}
      {complete && <div className="tape__tear" aria-hidden="true" />}
    </>
  );
}
