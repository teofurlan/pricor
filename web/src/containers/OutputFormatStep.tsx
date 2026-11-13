import { useEffect, useState } from "react";
import type { OutputFormatApiClient } from "../api/client";
import type { OutputFormat } from "../api/types";
import { Button } from "../components/atoms/Button";
import { TapeLoader } from "../components/atoms/TapeLoader";
import { useI18n } from "../i18n";
import { OutputFormatContainer } from "./OutputFormatContainer";

interface Props {
  api: OutputFormatApiClient;
  onContinue(): void;
}

/**
 * The wizard step between preview and approval. A saved format is only summarised and the primary
 * key moves on; the editor opens on request, so the common path costs one click.
 */
export function OutputFormatStep({ api, onContinue }: Props) {
  const { t } = useI18n();
  const [format, setFormat] = useState<OutputFormat | null>(null);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(false);

  useEffect(() => {
    let active = true;
    api.getOutputFormat()
      .then((stored) => { if (active) setFormat(stored); })
      // A failed read leaves the standard columns in place; opening the editor shows the error again.
      .catch(() => undefined)
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [api]);

  if (loading) return <TapeLoader text={t("common.loading")} />;

  const saved = format?.state === "confirmed" ? format : null;
  const count = saved?.columns.length ?? 0;

  return (
    <div className="stack format-step">
      <div className="format-step__summary">
        <p className="format-step__line">
          {saved ? t(count === 1 ? "formatStep.using.one" : "formatStep.using", { n: count }) : t("formatStep.standard")}
        </p>
        {!editing && (
          <Button onClick={() => setEditing(true)}>{t(saved ? "formatStep.change" : "formatStep.setup")}</Button>
        )}
      </div>
      {editing && <OutputFormatContainer api={api} onChange={setFormat} />}
      <div className="actions">
        <Button variant="primary" onClick={onContinue}>{t("formatStep.continue")}</Button>
      </div>
    </div>
  );
}
