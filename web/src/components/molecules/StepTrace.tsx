import type { TraceStep } from "../../api/types";
import { isTextKey, useI18n } from "../../i18n";

const LONG_DECIMAL = /^(-?\d+)\.(\d{7,})$/;

/** Intermediate steps are exact and unrounded; long ones are shortened to read, never altered. */
function readable(value: string): { text: string; full?: string } {
  const match = LONG_DECIMAL.exec(value);
  return match ? { text: `${match[1]}.${match[2].slice(0, 4)}…`, full: value } : { text: value };
}

/** The path of one price through the plan: the cell as written, each step, the final cost. */
export function StepTrace({
  trace,
  currency,
  convertedCurrency = null,
}: {
  trace: TraceStep[];
  currency: string | null;
  /** The currency of the `convert_currency` step. */
  convertedCurrency?: string | null;
}) {
  const { t } = useI18n();
  return (
    <ol className="trace">
      {trace.map((item, position) => {
        const key = `trace.${item.step}`;
        const label = isTextKey(key) ? t(key) : item.step;
        const isFinal = item.step === "rounding" || item.step === "convert_currency";
        const unit = item.step === "convert_currency" ? convertedCurrency : currency;
        const shown = isFinal ? { text: unit ? `${item.value} ${unit}` : item.value } : readable(item.value);
        return (
          <li key={`${item.step}-${position}`} className={isFinal ? "trace__step trace__step--final" : "trace__step"}>
            <span className="trace__label">{label}</span>
            <span className="trace__value" title={shown.full}>
              {shown.text}
            </span>
          </li>
        );
      })}
    </ol>
  );
}
