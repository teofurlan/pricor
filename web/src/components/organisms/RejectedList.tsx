import type { PreviewTotals } from "../../api/types";
import { useI18n } from "../../i18n";

/** Every rejected row, by its number in the supplier's file, with the reasons. */
export function RejectedList({ rows }: { rows: PreviewTotals["rejected_rows"] }) {
  const { t } = useI18n();
  if (rows.length === 0) return <p className="lede">{t("rejected.none")}</p>;
  return (
    <ul className="rejected">
      {rows.map((row) => (
        <li key={row.row_number} className="rejected__item">
          <strong>{t("preview.rowNumber", { row: row.row_number })}</strong>
          <div>
            {row.reasons.map((reason) => (
              <p key={reason}>{reason}</p>
            ))}
          </div>
        </li>
      ))}
    </ul>
  );
}
