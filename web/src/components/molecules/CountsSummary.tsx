import type { PreviewTotals } from "../../api/types";
import { useI18n, type TextKey } from "../../i18n";

const SKIPPED: [string, TextKey][] = [
  ["empty", "counts.skipped.empty"],
  ["total", "counts.skipped.total"],
  ["section", "counts.skipped.section"],
  ["preamble", "counts.skipped.preamble"],
];

/** Accepted + rejected = data rows, with the rows that were left out of the count named. */
export function CountsSummary({ totals, tape = false }: { totals: PreviewTotals; tape?: boolean }) {
  const { t } = useI18n();
  const adds = totals.accepted + totals.rejected === totals.data_rows;
  const skipped = SKIPPED.filter(([kind]) => (totals.skipped_rows[kind] ?? 0) > 0).map(([kind, key]) =>
    t(key, { count: totals.skipped_rows[kind] }),
  );
  return (
    <section className={`counts${tape ? " counts--tape" : ""}`}>
      <div className="counts__equation">
        <div className="count count--good" role="group" aria-label={t("counts.accepted")}>
          <span className="count__value">{totals.accepted}</span>
          <span className="count__label">{t("counts.accepted")}</span>
        </div>
        <span className="counts__sign" aria-hidden="true">+</span>
        <div className="count count--bad" role="group" aria-label={t("counts.rejected")}>
          <span className="count__value">{totals.rejected}</span>
          <span className="count__label">{t("counts.rejected")}</span>
        </div>
        <span className="counts__sign" aria-hidden="true">=</span>
        <div className="count" role="group" aria-label={t("counts.dataRows")}>
          <span className="count__value">{totals.data_rows}</span>
          <span className="count__label">{t("counts.dataRows")}</span>
        </div>
      </div>
      {!adds && (
        <p role="alert" className="counts__alert">
          {t("counts.mismatch", { accepted: totals.accepted, rejected: totals.rejected, total: totals.data_rows })}
        </p>
      )}
      {skipped.length > 0 && <p className="counts__skipped">{t("counts.skipped", { list: skipped.join(", ") })}</p>}
    </section>
  );
}
