import type { Notice } from "../../api/types";
import { useI18n } from "../../i18n";

/** Session notices, calm but impossible to miss. */
export function NoticeList({ notices }: { notices: Notice[] }) {
  const { t } = useI18n();
  if (notices.length === 0) return null;
  return (
    <div className="notices">
      {notices.map((notice) => (
        <div key={`${notice.code}-${notice.stage}-${notice.message}`} role="status" className="notice">
          {notice.code === "model_unavailable" ? (
            <>
              <strong className="notice__title">{t("notice.modelUnavailable.title")}</strong>
              <p>{t("notice.modelUnavailable.body")}</p>
              <p className="notice__detail">{notice.message}</p>
            </>
          ) : (
            <p>{notice.message}</p>
          )}
        </div>
      ))}
    </div>
  );
}
