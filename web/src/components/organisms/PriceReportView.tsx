import { useId, useState, type FormEvent, type ReactNode } from "react";
import type { PriceReport, ReportChange, ReportProduct } from "../../api/types";
import { percentToRatio, ratioToPercent, signedPercent } from "../../lib/percent";
import { useI18n, type TextKey } from "../../i18n";
import { Badge } from "../atoms/Badge";
import { Button } from "../atoms/Button";

const ROW_LIMIT = 50;

interface Props {
  report: PriceReport;
  csvUrl: string;
  busy: boolean;
  /** The user applied a new anomaly threshold, as a ratio ("0.30"). */
  onThreshold(ratio: string): void;
}

const money = (value: string, currency: string) => `${value} ${currency}`;
const signedMoney = (value: string, currency: string) =>
  money(value.startsWith("-") ? value : `+${value}`, currency);

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
  const { t } = useI18n();
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
          <Button onClick={() => setExpanded(true)}>{t("report.showAll", { count })}</Button>
        </div>
      )}
    </section>
  );
}

function ChangeTable({ rows, showPercent = true }: { rows: ReportChange[]; showPercent?: boolean }) {
  const { t } = useI18n();
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
            <td className="num">{money(row.previous_cost, row.currency)}</td>
            <td className="num">{money(row.current_cost, row.currency)}</td>
            <td className="num">{signedMoney(row.change, row.currency)}</td>
            {showPercent && <td className="num">{row.change_pct === null ? "" : signedPercent(row.change_pct)}</td>}
            <td>{row.anomaly && <Badge tone="user">{t("report.review")}</Badge>}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function ProductTable({ rows }: { rows: ReportProduct[] }) {
  const { t } = useI18n();
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
            <td className="num">{money(row.unit_cost_net, row.currency)}</td>
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
      <Button type="submit" disabled={busy || ratio === null}>
        {t("report.apply")}
      </Button>
      {(invalid || text.trim() === "") && <span className="hint">{t("report.threshold.invalid")}</span>}
    </form>
  );
}

/** What changed since the supplier's previous list: a one-line summary, then every section. */
export function PriceReportView({ report, csvUrl, busy, onThreshold }: Props) {
  const { t } = useI18n();
  const { summary } = report;
  const threshold = ratioToPercent(report.threshold);
  const plural = (base: "report.anomaly" | "report.new", count: number) =>
    t(`${base}.${count === 1 ? "one" : "other"}` as TextKey, { count });
  const times = (count: number) => t(`report.times.${count === 1 ? "one" : "other"}` as TextKey, { count });

  const down = t("report.down", { count: summary.decreases });
  const median =
    summary.median_change_pct === null
      ? ""
      : ` (${t("report.median", { median: signedPercent(summary.median_change_pct) })})`;
  const headline = [
    t("report.unchanged", { count: summary.unchanged }),
    t("report.up", { count: summary.increases }),
    `${down}${median}`,
    plural("report.anomaly", summary.anomalies),
  ].join(", ");

  return (
    <div className="stack report">
      <div className="stack">
        <h2 className="report__headline">{headline}</h2>
        <p className="hint">
          {plural("report.new", summary.new_products)}, {t("report.gone", { count: summary.discontinued })}.
        </p>
        {summary.currency_changed > 0 && <p className="hint">{t("report.note.currency", { count: summary.currency_changed })}</p>}
        {summary.ambiguous > 0 && <p className="hint">{t("report.note.ambiguous", { count: summary.ambiguous })}</p>}
        <div className="actions">
          <ThresholdForm initial={threshold} busy={busy} onApply={onThreshold} />
          <a className="button button--quiet" href={csvUrl} download>
            {t("report.csv")}
          </a>
        </div>
      </div>

      {report.anomalies.length > 0 ? (
        <Section
          title={t("report.anomalies", { count: report.anomalies.length })}
          lede={t("report.anomalies.lede", { threshold })}
          count={report.anomalies.length}
        >
          {(visible) => <ChangeTable rows={report.anomalies.slice(0, visible)} />}
        </Section>
      ) : (
        <p className="lede">{t("report.noAnomalies", { threshold })}</p>
      )}
      {report.increases.length > 0 && (
        <Section title={t("report.increases", { count: report.increases.length })} count={report.increases.length}>
          {(visible) => <ChangeTable rows={report.increases.slice(0, visible)} />}
        </Section>
      )}
      {report.decreases.length > 0 && (
        <Section title={t("report.decreases", { count: report.decreases.length })} count={report.decreases.length}>
          {(visible) => <ChangeTable rows={report.decreases.slice(0, visible)} />}
        </Section>
      )}
      {report.from_zero.length > 0 && (
        <Section
          title={t("report.fromZero", { count: report.from_zero.length })}
          lede={t("report.fromZero.lede")}
          count={report.from_zero.length}
        >
          {(visible) => <ChangeTable rows={report.from_zero.slice(0, visible)} showPercent={false} />}
        </Section>
      )}
      {report.new_products.length > 0 && (
        <Section title={t("report.newProducts", { count: report.new_products.length })} count={report.new_products.length}>
          {(visible) => <ProductTable rows={report.new_products.slice(0, visible)} />}
        </Section>
      )}
      {report.discontinued.length > 0 && (
        <Section title={t("report.discontinued", { count: report.discontinued.length })} count={report.discontinued.length}>
          {(visible) => <ProductTable rows={report.discontinued.slice(0, visible)} />}
        </Section>
      )}
      {report.currency_changed.length > 0 && (
        <Section
          title={t("report.currencyChanged", { count: report.currency_changed.length })}
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
                    <td className="num">{money(row.previous_cost, row.previous_currency)}</td>
                    <td className="num">{money(row.current_cost, row.current_currency)}</td>
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
            {t("report.ambiguous", { count: report.ambiguous_codes.length })}
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
