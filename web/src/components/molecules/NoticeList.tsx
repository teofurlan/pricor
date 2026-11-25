import { useServerConfig } from "../../api/serverConfig";
import type { Notice } from "../../api/types";
import { useI18n } from "../../i18n";
import { localizeNotice } from "../../i18n/serverText";

/** The stages that are Gemma: the column stage of that name and the plan advisor. Any other stage is not Gemma's to answer for. */
const GEMMA_STAGES = new Set(["gemma", "advisor"]);

/** Session notices, calm but impossible to miss. */
export function NoticeList({ notices, compact = false }: { notices: Notice[]; compact?: boolean }) {
  const { t, language } = useI18n();
  const { hosted } = useServerConfig();
  if (notices.length === 0) return null;
  return (
    <div className="notices">
      {notices.map((notice) => {
        if (notice.code === "pdf_vision_extracted") {
          return (
            <div key={`${notice.code}-${notice.stage}-${notice.message}`} role="status" className="notice">
              <strong className="notice__title">{t("notice.pdfVision.title")}</strong>
              <p>{t("notice.pdfVision.body")}</p>
            </div>
          );
        }
        const modelNotice = notice.code === "model_unavailable";
        const title = t(
          notice.stage !== null && !GEMMA_STAGES.has(notice.stage)
            ? "notice.stageUnavailable.title"
            : hosted ? "notice.modelUnavailable.title.hosted" : "notice.modelUnavailable.title",
        );
        if (compact && modelNotice) {
          return (
            <div key={`${notice.code}-${notice.stage}-${notice.message}`} role="status" className="notice">
              <strong className="notice__title">{title}</strong>
            </div>
          );
        }
        const { text, detail } = localizeNotice(notice.message, language);
        return (
          <div key={`${notice.code}-${notice.stage}-${notice.message}`} role="status" className="notice">
            {modelNotice && (
              <>
                <strong className="notice__title">{title}</strong>
                <p>{t("notice.modelUnavailable.body")}</p>
              </>
            )}
            {!modelNotice && <p>{text}</p>}
            {(detail !== null || modelNotice) && (
              <details className="notice__tech">
                <summary>{t("notice.techDetails")}</summary>
                {modelNotice && detail !== null && <p className="notice__detail">{text}</p>}
                <p className="notice__detail">{detail !== null ? t("notice.detail", { detail }) : text}</p>
              </details>
            )}
          </div>
        );
      })}
    </div>
  );
}
