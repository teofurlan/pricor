import { useI18n } from "../../i18n";
import { decimalTail } from "./StepTrace";

/** A pinned engine regression, not a prediction or an uploaded product. */
export function ExampleTape() {
  const { t } = useI18n();
  const lines = [
    ["#", "12,100.00", "example.box"],
    ["×", "0.90", "example.discount10"],
    ["×", "0.95", "example.discount5"],
    ["÷", "1.21", "example.vat"],
    ["÷", "10", "example.units"],
    ["=", "855.00 ARS", "trace.rounding"],
  ] as const;
  const decimalColumn = Math.max(0, ...lines.map(([, val]) => decimalTail(val)));
  return (
    <section className="tape tape--example" aria-label={t("example.title")}>
      <h2 className="tape__heading">{t("example.title")}</h2>
      <p className="tape__description">{t("example.lede")}</p>
      <ol className="trace">
        {lines.map(([operator, value, label], index) => {
          const isFinal = index === lines.length - 1;
          const pad = decimalColumn - decimalTail(value);
          return (
            <li key={label} className={`trace__step${isFinal ? " trace__step--final" : ""}`}>
              <span className="trace__operator" aria-hidden="true">{operator}</span>
              <span className="trace__label">{t(label)}</span>
              <span className="trace__value" style={{ paddingInlineEnd: `${pad}ch` }}>{value}</span>
              {isFinal && <span className="trace__mark" aria-hidden="true">✱</span>}
            </li>
          );
        })}
      </ol>
      <div className="tape__tear" aria-hidden="true" />
    </section>
  );
}
