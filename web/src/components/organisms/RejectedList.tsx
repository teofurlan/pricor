import { useState } from "react";
import type { PreviewTotals } from "../../api/types";
import { useI18n } from "../../i18n";
import { formatInteger } from "../../lib/decimalText";
import { Button } from "../atoms/Button";

const BATCH_SIZE = 50;

/** Rejected rows, by file row number, rendered in bounded batches to keep large lists responsive. */
export function RejectedList({ rows }: { rows: PreviewTotals["rejected_rows"] }) {
  const { t, language } = useI18n();
  const [limit, setLimit] = useState(BATCH_SIZE);
  if (rows.length === 0) return <p className="lede">{t("rejected.none")}</p>;
  const visible = rows.slice(0, limit);
  const remaining = rows.length - visible.length;
  return (
    <div className="stack">
      <ul className="rejected">
        {visible.map((row) => (
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
      {remaining > 0 && (
        <div className="actions">
          <Button variant="quiet" onClick={() => setLimit((current) => current + BATCH_SIZE)}>
            {t("rejected.showMore", { remaining: formatInteger(remaining, language) })}
          </Button>
        </div>
      )}
    </div>
  );
}
