import { useId, useState } from "react";
import type { FxState } from "../../api/types";
import { useI18n } from "../../i18n";
import { Badge } from "../atoms/Badge";
import { Button } from "../atoms/Button";

interface Props {
  fx: FxState;
  busy: boolean;
  onManual(rate: string): void;
  onRefresh(): void;
}

/** The exchange rate of this run: what was used and where it came from, or a way to supply one. */
export function FxPanel({ fx, busy, onManual, onRefresh }: Props) {
  const { t } = useI18n();
  const [typed, setTyped] = useState("");
  const inputId = useId();
  const snapshot = fx.snapshot;
  return (
    <section className="fx stack" aria-label={t("fx.title")}>
      <h2 className="subtitle">{t("fx.title")}</h2>
      {snapshot ? (
        <div className="fx__rate">
          <p className="fx__line">{t("fx.rateLine", { from: fx.from, to: fx.to, rate: snapshot.rate })}</p>
          <p className="fx__detail">{t("fx.type", { type: snapshot.rate_type, side: snapshot.side })}</p>
          <p className="fx__detail">{t("fx.source", { source: snapshot.source })}</p>
          <p className="fx__detail">{t("fx.date", { date: snapshot.date })}</p>
          {snapshot.stale && <Badge tone="bad">{t("fx.stale")}</Badge>}
          {snapshot.source === "manual" && <Badge tone="user">{t("fx.manualBadge")}</Badge>}
        </div>
      ) : (
        <p className="fx__required">{t("fx.required")}</p>
      )}
      {fx.error && <p className="fx__error">{t("fx.error", { error: fx.error })}</p>}
      <div className="fx__manual">
        <label htmlFor={inputId}>{t("fx.manual.label", { from: fx.from, to: fx.to })}</label>
        <input id={inputId} inputMode="decimal" value={typed} onChange={(event) => setTyped(event.target.value)} />
        <Button disabled={busy || typed.trim() === ""} onClick={() => onManual(typed.trim())}>
          {t("fx.manual.use")}
        </Button>
        {fx.rate_type !== "manual" && (
          <Button disabled={busy} onClick={onRefresh}>
            {t("fx.refresh")}
          </Button>
        )}
      </div>
    </section>
  );
}
