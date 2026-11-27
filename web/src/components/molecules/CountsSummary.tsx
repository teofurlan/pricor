import type { PreviewTotals } from "../../api/types";
import { useI18n, type TextKey } from "../../i18n";
import { formatInteger } from "../../lib/decimalText";
import { Button } from "../atoms/Button";
import { TapeFigure } from "../atoms/TapeFigure";

const SKIPPED: [string, TextKey][] = [
  ["empty", "counts.skipped.empty"],
  ["total", "counts.skipped.total"],
  ["section", "counts.skipped.section"],
  ["preamble", "counts.skipped.preamble"],
  ["ignored_by_user", "counts.skipped.ignoredByUser"],
];

/** Accepted + rejected = data rows, with the rows that were left out of the count named. */
export function CountsSummary({
  totals,
  tape = false,
  onRestoreIgnored,
  busy = false,
}: {
  totals: PreviewTotals;
  tape?: boolean;
  onRestoreIgnored?: () => void;
  busy?: boolean;
}) {
  const { t, language } = useI18n();
  const adds = totals.accepted + totals.rejected === totals.data_rows;
  const ignoredCount = totals.skipped_rows.ignored_by_user ?? 0;
  const skipped = SKIPPED.filter(([kind]) => (totals.skipped_rows[kind] ?? 0) > 0).map(([kind, key]) =>
    t(key, { count: formatInteger(totals.skipped_rows[kind], language) }),
  );
  return (
    <section className={`counts${tape ? " counts--tape" : ""}`}>
      <div className="counts__equation">
        <div className="count count--good" role="group" aria-label={t("counts.accepted")}>
          <TapeFigure className="count__value" language={language} value={totals.accepted} fracWidth={0} />
          <span className="count__label">{t("counts.accepted")}</span>
        </div>
        <span className="counts__sign" aria-hidden="true">+</span>
        <div className="count count--bad" role="group" aria-label={t("counts.rejected")}>
          <TapeFigure className="count__value" language={language} value={totals.rejected} fracWidth={0} />
          <span className="count__label">{t("counts.rejected")}</span>
        </div>
        <span className="counts__sign" aria-hidden="true">=</span>
        <div className="count" role="group" aria-label={t("counts.dataRows")}>
          <TapeFigure className="count__value" language={language} value={totals.data_rows} fracWidth={0} />
          <span className="count__label">{t("counts.dataRows")}</span>
        </div>
      </div>
      {!adds && (
        <p role="alert" className="counts__alert">
          {t("counts.mismatch", { accepted: formatInteger(totals.accepted, language), rejected: formatInteger(totals.rejected, language), total: formatInteger(totals.data_rows, language) })}
        </p>
      )}
      {skipped.length > 0 && (
        <div className="counts__skipped-row">
          <p className="counts__skipped">{t("counts.skipped", { list: skipped.join(", ") })}</p>
          {ignoredCount > 0 && onRestoreIgnored && (
            <Button variant="quiet" disabled={busy} onClick={onRestoreIgnored}>
              {t("counts.restoreIgnored")}
            </Button>
          )}
        </div>
      )}
    </section>
  );
}
