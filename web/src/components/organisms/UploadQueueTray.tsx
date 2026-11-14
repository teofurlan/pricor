import { useI18n, type TextKey } from "../../i18n";
import { Button } from "../atoms/Button";
import type { QueueDraft } from "./UploadQueue";

export type QueueStatus = "pending" | "reviewing" | "approved" | "failed" | "skipped";

export interface QueueItem extends QueueDraft {
  /** The import session once the file was read; the unified download uses the approved ones. */
  sessionId: string | null;
  /** Products accepted when the file was approved. */
  accepted: number;
  status: QueueStatus;
  error: string | null;
}

const STATUS: Record<QueueStatus, TextKey> = {
  pending: "queue.status.pending",
  reviewing: "queue.status.reviewing",
  approved: "queue.status.approved",
  failed: "queue.status.failed",
  skipped: "queue.status.skipped",
};

/** Every file of the queue with its state, above the stepper. */
export function UploadQueueTray({ items }: { items: QueueItem[] }) {
  const { t } = useI18n();
  return (
    <ul className="queue-tray" aria-label={t("queue.tray")}>
      {items.map((item, index) => (
        <li key={`${item.file.name}-${index}`} className={`queue-tray__item queue-tray__item--${item.status}`}>
          <span className="queue-tray__file">{item.file.name}</span>
          <span className="queue-tray__status">{t(STATUS[item.status])}</span>
          {item.error && <span className="queue-tray__error">{t("queue.failed", { reason: item.error })}</span>}
        </li>
      ))}
    </ul>
  );
}

interface SummaryProps {
  items: QueueItem[];
  busy: boolean;
  onDownload?(format: "csv" | "xlsx", kind: "products" | "rejected"): void;
  onRestart(): void;
}

/** When no file is left: how many were approved and the unified downloads. */
export function QueueSummary({ items, busy, onDownload, onRestart }: SummaryProps) {
  const { t } = useI18n();
  const approved = items.filter((item) => item.status === "approved");
  const products = approved.reduce((sum, item) => sum + item.accepted, 0);
  return (
    <div className="stack">
      <p>{t("queue.summary", { approved: approved.length, total: items.length, products })}</p>
      {approved.length > 0 && onDownload && (
        <div className="actions">
          <Button variant="primary" disabled={busy} onClick={() => onDownload("xlsx", "products")}>{t("queue.download.products")}</Button>
          <Button variant="quiet" disabled={busy} onClick={() => onDownload("csv", "products")}>{t("queue.download.productsCsv")}</Button>
          <Button variant="quiet" disabled={busy} onClick={() => onDownload("xlsx", "rejected")}>{t("queue.download.rejected")}</Button>
          <Button variant="quiet" disabled={busy} onClick={() => onDownload("csv", "rejected")}>{t("queue.download.rejectedCsv")}</Button>
        </div>
      )}
      <div className="actions"><Button variant="quiet" onClick={onRestart}>{t("queue.restart")}</Button></div>
    </div>
  );
}
