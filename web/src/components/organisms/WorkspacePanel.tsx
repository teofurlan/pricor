import { useState } from "react";
import { useI18n } from "../../i18n";
import { Button } from "../atoms/Button";

/** The visitor's personal link, quiet but copyable; whoever holds the link sees the lists. */
export function WorkspacePanel({ link }: { link: string }) {
  const { t } = useI18n();
  const [outcome, setOutcome] = useState<"copied" | "failed" | null>(null);

  async function copy() {
    try {
      await navigator.clipboard.writeText(link);
      setOutcome("copied");
    } catch {
      setOutcome("failed");
    }
  }

  return (
    <section className="workspace" aria-labelledby="workspace-title">
      <h2 id="workspace-title" className="workspace__title">{t("workspace.title")}</h2>
      <p className="workspace__body">{t("workspace.body")}</p>
      <div className="workspace__row">
        <input
          className="workspace__link"
          readOnly
          value={link}
          aria-label={t("workspace.linkLabel")}
          onFocus={(event) => event.currentTarget.select()}
        />
        <Button variant="quiet" onClick={copy}>{t("workspace.copy")}</Button>
        <span className="workspace__status" role="status">
          {outcome === "copied" ? t("workspace.copied") : outcome === "failed" ? t("workspace.copyFailed") : ""}
        </span>
      </div>
    </section>
  );
}
