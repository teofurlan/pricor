import { useServerConfig } from "../../api/serverConfig";
import type { Notice } from "../../api/types";
import { useI18n } from "../../i18n";
import { localizeNotice } from "../../i18n/serverText";

/** Session notices, calm but impossible to miss. */
export function NoticeList({ notices, compact = false }: { notices: Notice[]; compact?: boolean }) {
  const { t, language } = useI18n();
  const { hosted } = useServerConfig();
  if (notices.length === 0) return null;
  return (
    <div className="notices">
      {notices.map((notice) => {
        const modelNotice = notice.code === "model_unavailable";
        if (compact && modelNotice) {
          return (
            <div key={`${notice.code}-${notice.stage}-${notice.message}`} role="status" className="notice">
              <strong className="notice__title">{t(hosted ? "notice.modelUnavailable.title.hosted" : "notice.modelUnavailable.title")}</strong>
            </div>
          );
        }
        const { text, detail } = localizeNotice(notice.message, language);
        return (
          <div key={`${notice.code}-${notice.stage}-${notice.message}`} role="status" className="notice">
            {modelNotice && (
              <>
                <strong className="notice__title">{t(hosted ? "notice.modelUnavailable.title.hosted" : "notice.modelUnavailable.title")}</strong>
                <p>{t("notice.modelUnavailable.body")}</p>
              </>
            )}
            {detail === null ? (
              // An untranslated server text under the explanation is detail; on its own it is the message.
              <p className={modelNotice ? "notice__detail" : undefined}>{text}</p>
            ) : (
              <>
                <p>{text}</p>
                <p className="notice__detail">{t("notice.detail", { detail })}</p>
              </>
            )}
          </div>
        );
      })}
    </div>
  );
}
