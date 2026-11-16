import { useId, useState, type FormEvent, type ReactNode } from "react";
import type { Language, PriceReport, ReportChange, ReportProduct } from "../../api/types";
import { formatFigure, formatInteger } from "../../lib/decimalText";
import { percentToRatio, ratioToPercent, signedPercent } from "../../lib/percent";
import { useI18n, type TextKey } from "../../i18n";
import { Button } from "../atoms/Button";
import { TapeFigure } from "../atoms/TapeFigure";

const ROW_LIMIT = 50;

interface Props {
  report: PriceReport;
  csvUrl: string;
  busy: boolean;
  /** The user applied a new anomaly threshold, as a ratio ("0.30"). */
  onThreshold(ratio: string): void;
}

const money = (value: string, currency: string, language: Language) => formatFigure(`${value} ${currency}`, language);
const signedMoney = (value: string, currency: string, language: Language) =>
  money(value.startsWith("-") ? value : `+${value}`, currency, language);

function Section({
  title,
  lede,
  count,
  children,
}: {
  title: string;
  lede?: string;
  count: number;
  children(visible: number): ReactNode;
}) {
  const { t, language } = useI18n();
  const headingId = useId();
  const [expanded, setExpanded] = useState(false);
  const visible = expanded ? count : Math.min(count, ROW_LIMIT);
  return (
    <section className="stack report__section" aria-labelledby={headingId}>
      <h3 id={headingId} className="subtitle">
        {title}
      </h3>
      {lede && <p className="hint">{lede}</p>}
      <div className="table-wrap">{children(visible)}</div>
      {visible < count && (
        <div className="actions">
          <Button onClick={() => setExpanded(true)}>{t("report.showAll", { count: formatInteger(count, language) })}</Button>
        </div>
      )}
    </section>
  );
}

function ChangeTable({ rows, showPercent = true }: { rows: ReportChange[]; showPercent?: boolean }) {
  const { t, language } = useI18n();
  return (
    <table className="table table--report">
      <thead>
        <tr>
          <th>{t("report.col.code")}</th>
          <th>{t("report.col.description")}</th>
          <th className="num">{t("report.col.before")}</th>
          <th className="num">{t("report.col.now")}</th>
          <th className="num">{t("report.col.change")}</th>
          {showPercent && <th className="num">{t("report.col.percent")}</th>}
          <th />
        </tr>
      </thead>
      <tbody>
        {rows.map((row, position) => (
          <tr key={`${row.supplier_code}-${position}`} className={row.anomaly ? "row--anomaly" : undefined}>
            <th scope="row">{row.supplier_code}</th>
            <td>{row.description}</td>
            <td className="num">{money(row.previous_cost, row.currency, language)}</td>
            <td className="num">{money(row.current_cost, row.currency, language)}</td>
            <td className={`num${row.change.startsWith("-") ? " num--negative" : ""}`}>{signedMoney(row.change, row.currency, language)}</td>
            {showPercent && <td className={`num${row.change_pct?.startsWith("-") ? " num--negative" : ""}`}>{row.change_pct === null ? "" : formatFigure(signedPercent(row.change_pct), language)}</td>}
            <td>{row.anomaly && <span className="anomaly-mark">✱ {t("report.review")}</span>}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function ProductTable({ rows }: { rows: ReportProduct[] }) {
  const { t, language } = useI18n();
  return (
    <table className="table table--report">
      <thead>
        <tr>
          <th>{t("report.col.code")}</th>
          <th>{t("report.col.description")}</th>
          <th className="num">{t("report.col.cost")}</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row, position) => (
          <tr key={`${row.supplier_code}-${position}`}>
            <th scope="row">{row.supplier_code}</th>
            <td>{row.description}</td>
            <td className="num">{money(row.unit_cost_net, row.currency, language)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function ThresholdForm({ initial, busy, onApply }: { initial: string; busy: boolean; onApply(ratio: string): void }) {
  const { t } = useI18n();
  const [text, setText] = useState(initial);
  const fieldId = useId();
  const ratio = percentToRatio(text);
  const invalid = text.trim() !== "" && ratio === null;
  const apply = (event: FormEvent) => {
    event.preventDefault();
    if (ratio !== null && !busy) onApply(ratio);
  };
  return (
    <form className="report__threshold" onSubmit={apply}>
      <label className="field">
        <span className="field__label">{t("report.threshold")}</span>
        <input
          id={fieldId}
          value={text}
          inputMode="decimal"
          autoComplete="off"
          aria-invalid={invalid}
          onChange={(event) => setText(event.target.value)}
        />
      </label>
      <Button type="submit" disabled={busy || ratio === null} loading={busy}>
        {t("report.apply")}
      </Button>
      {(invalid || text.trim() === "") && <span className="hint">{t("report.threshold.invalid")}</span>}
    </form>
  );
}

/** What changed since the supplier's previous list: a one-line summary, then every section. */
export function PriceReportView({ report, csvUrl, busy, onThreshold }: Props) {
  const { t, language } = useI18n();
  const { summary } = report;
  const threshold = ratioToPercent(report.threshold);
  const plural = (base: "report.anomaly" | "report.new", count: number) =>
    t(`${base}.${count === 1 ? "one" : "other"}` as TextKey, { count: formatInteger(count, language) });
  const times = (count: number) => t(`report.times.${count === 1 ? "one" : "other"}` as TextKey, { count });

  const summaryLines = [
    { mark: "◇", value: summary.unchanged, label: t("report.unchanged", { count: "" }).trim() },
    { mark: "↑", value: summary.increases, label: t("report.up", { count: "" }).trim() },
    { mark: "↓", value: summary.decreases, label: t("report.down", { count: "" }).trim(), negative: true },
    { mark: "+", value: summary.new_products, label: plural("report.new", summary.new_products).replace(formatInteger(summary.new_products, language), "").trim() },
    { mark: "−", value: summary.discontinued, label: t("report.gone", { count: "" }).trim() },
    { mark: "✱", value: summary.anomalies, label: plural("report.anomaly", summary.anomalies).replace(formatInteger(summary.anomalies, language), "").trim(), total: true },
  ];

  return (
    <div className="stack report">
      <div className="report__overview">
        <section className="tape report__summary" aria-label={t("report.summary")}>
          <h2 className="report__headline">{t("report.summary")}</h2>
          <ol className="report__summary-list">
            {summaryLines.map((line) => <li key={line.label} className={`report__summary-line${line.negative ? " report__summary-line--negative" : ""}${line.total ? " report__summary-line--total" : ""}`}>
              <span aria-hidden="true">{line.mark}</span><span className="report__summary-label">{line.label}</span><TapeFigure className="report__summary-value" language={language} value={line.value} fracWidth={0} />
            </li>)}
          </ol>
          {summary.median_change_pct !== null && <p className="hint report__median">{t("report.median", { median: formatFigure(signedPercent(summary.median_change_pct), language) })}</p>}
          <div className="tape__tear" aria-hidden="true" />
        </section>
        <div className="report__tools">
        {summary.currency_changed > 0 && <p className="hint">{t("report.note.currency", { count: formatInteger(summary.currency_changed, language) })}</p>}
        {summary.ambiguous > 0 && <p className="hint">{t("report.note.ambiguous", { count: formatInteger(summary.ambiguous, language) })}</p>}
        <div className="actions">
          <ThresholdForm initial={threshold} busy={busy} onApply={onThreshold} />
          <a className="button button--quiet" href={csvUrl} download>
            {t("report.csv")}
          </a>
        </div>
        </div>
      </div>

      {report.anomalies.length > 0 ? (
        <Section
          title={t("report.anomalies", { count: formatInteger(report.anomalies.length, language) })}
          lede={t("report.anomalies.lede", { threshold })}
          count={report.anomalies.length}
        >
          {(visible) => <ChangeTable rows={report.anomalies.slice(0, visible)} />}
        </Section>
      ) : (
        <p className="lede">{t("report.noAnomalies", { threshold })}</p>
      )}
      {report.increases.length > 0 && (
        <Section title={t("report.increases", { count: formatInteger(report.increases.length, language) })} count={report.increases.length}>
          {(visible) => <ChangeTable rows={report.increases.slice(0, visible)} />}
        </Section>
      )}
      {report.decreases.length > 0 && (
        <Section title={t("report.decreases", { count: formatInteger(report.decreases.length, language) })} count={report.decreases.length}>
          {(visible) => <ChangeTable rows={report.decreases.slice(0, visible)} />}
        </Section>
      )}
      {report.from_zero.length > 0 && (
        <Section
          title={t("report.fromZero", { count: formatInteger(report.from_zero.length, language) })}
          lede={t("report.fromZero.lede")}
          count={report.from_zero.length}
        >
          {(visible) => <ChangeTable rows={report.from_zero.slice(0, visible)} showPercent={false} />}
        </Section>
      )}
      {report.new_products.length > 0 && (
        <Section title={t("report.newProducts", { count: formatInteger(report.new_products.length, language) })} count={report.new_products.length}>
          {(visible) => <ProductTable rows={report.new_products.slice(0, visible)} />}
        </Section>
      )}
      {report.discontinued.length > 0 && (
        <Section title={t("report.discontinued", { count: formatInteger(report.discontinued.length, language) })} count={report.discontinued.length}>
          {(visible) => <ProductTable rows={report.discontinued.slice(0, visible)} />}
        </Section>
      )}
      {report.currency_changed.length > 0 && (
        <Section
          title={t("report.currencyChanged", { count: formatInteger(report.currency_changed.length, language) })}
          lede={t("report.currencyChanged.lede")}
          count={report.currency_changed.length}
        >
          {(visible) => (
            <table className="table table--report">
              <thead>
                <tr>
                  <th>{t("report.col.code")}</th>
                  <th>{t("report.col.description")}</th>
                  <th className="num">{t("report.col.before")}</th>
                  <th className="num">{t("report.col.now")}</th>
                </tr>
              </thead>
              <tbody>
                {report.currency_changed.slice(0, visible).map((row, position) => (
                  <tr key={`${row.supplier_code}-${position}`}>
                    <th scope="row">{row.supplier_code}</th>
                    <td>{row.description}</td>
                    <td className="num">{money(row.previous_cost, row.previous_currency, language)}</td>
                    <td className="num">{money(row.current_cost, row.current_currency, language)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Section>
      )}
      {report.ambiguous_codes.length > 0 && (
        <section className="stack report__section" aria-labelledby="report-ambiguous">
          <h3 id="report-ambiguous" className="subtitle">
            {t("report.ambiguous", { count: formatInteger(report.ambiguous_codes.length, language) })}
          </h3>
          <p className="hint">{t("report.ambiguous.lede")}</p>
          <ul className="report__left-out">
            {report.ambiguous_codes.map((item, position) => (
              <li key={`${item.supplier_code}-${position}`}>
                {t("report.ambiguous.item", {
                  code: item.supplier_code,
                  before: times(item.previous_count),
                  after: times(item.current_count),
                })}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
