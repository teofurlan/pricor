import type { PreviewTotals } from "../../api/types";
import { useI18n } from "../../i18n";
import { Button } from "../atoms/Button";
import { CountsSummary } from "../molecules/CountsSummary";

export interface DownloadLinks {
  products: { csv: string; xlsx: string };
  rejected: { csv: string; xlsx: string };
}

interface Props {
  totals: PreviewTotals;
  approved: boolean;
  busy: boolean;
  links: DownloadLinks;
  supplier?: string;
  file?: string;
  onApprove(): void;
}

/** The signature and its receipts share the exact counts that were previewed. */
export function ApprovePanel({ totals, approved, busy, links, supplier, file, onApprove }: Props) {
  const { t } = useI18n();
  return (
    <div className="workbench workbench--approval">
      <div className="sign">
        <p className="sign__statement">
          {approved ? t("approve.done", { count: totals.accepted }) : <>
            {t(totals.accepted === 1 ? "approve.statement.one" : "approve.statement.other", { count: totals.accepted })}{" "}
            {t(totals.rejected === 1 ? "approve.rejected.one" : "approve.rejected.other", { count: totals.rejected })}
          </>}
        </p>
        {approved && <div className="downloads">
          <a className="receipt" href={links.products.csv} download>{t("approve.productsCsv")}<span aria-hidden="true"> ↓</span></a>
          <a className="receipt" href={links.products.xlsx} download>{t("approve.productsXlsx")}<span aria-hidden="true"> ↓</span></a>
          <a className="receipt" href={links.rejected.csv} download>{t("approve.rejectedCsv")}<span aria-hidden="true"> ↓</span></a>
          <a className="receipt" href={links.rejected.xlsx} download>{t("approve.rejectedXlsx")}<span aria-hidden="true"> ↓</span></a>
        </div>}
      </div>
      <section className="tape tape--sticky tape--approval" aria-label={t("title.approve")}>
        <h2 className="tape__heading">{t("title.approve")}</h2>
        {supplier && <p className="tape__reference"># {t("session.supplier")} / {supplier}</p>}
        {file && <p className="tape__reference"># {t("session.file")} / {file}</p>}
        <CountsSummary totals={totals} tape />
        {!approved && <Button variant="primary" className="button--sign" disabled={busy} onClick={onApprove}>{t("approve.button")}<span aria-hidden="true"> =</span></Button>}
        <div className="tape__tear" aria-hidden="true" />
      </section>
    </div>
  );
}
