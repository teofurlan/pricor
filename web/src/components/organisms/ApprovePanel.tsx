import type { PreviewTotals } from "../../api/types";
import { useI18n } from "../../i18n";
import { Button } from "../atoms/Button";

export interface DownloadLinks {
  products: { csv: string; xlsx: string };
  rejected: { csv: string; xlsx: string };
}

interface Props {
  totals: PreviewTotals;
  approved: boolean;
  busy: boolean;
  links: DownloadLinks;
  onApprove(): void;
}

/** The signature: the user states, in plain numbers, what is being approved. */
export function ApprovePanel({ totals, approved, busy, links, onApprove }: Props) {
  const { t } = useI18n();
  return (
    <div className="stack sign">
      {approved ? (
        <>
          <p className="sign__statement">{t("approve.done", { count: totals.accepted })}</p>
          <div className="downloads">
            <a className="button button--primary" href={links.products.csv} download>
              {t("approve.productsCsv")}
            </a>
            <a className="button button--quiet" href={links.products.xlsx} download>
              {t("approve.productsXlsx")}
            </a>
            <a className="button button--quiet" href={links.rejected.csv} download>
              {t("approve.rejectedCsv")}
            </a>
            <a className="button button--quiet" href={links.rejected.xlsx} download>
              {t("approve.rejectedXlsx")}
            </a>
          </div>
        </>
      ) : (
        <>
          <p className="sign__statement">
            {t(totals.accepted === 1 ? "approve.statement.one" : "approve.statement.other", { count: totals.accepted })}{" "}
            {t(totals.rejected === 1 ? "approve.rejected.one" : "approve.rejected.other", { count: totals.rejected })}
          </p>
          <div className="actions">
            <Button variant="primary" disabled={busy} onClick={onApprove}>
              {t("approve.button")}
            </Button>
          </div>
        </>
      )}
    </div>
  );
}
