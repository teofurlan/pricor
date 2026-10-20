import { useI18n, type TextKey } from "../../i18n";

export type StepId = "upload" | "header" | "columns" | "questions" | "preview" | "approve";
export interface StepItem {
  id: StepId;
  state: "done" | "current" | "upcoming";
  /** A finished step that can no longer change, such as the plan of an approved import. */
  locked?: boolean;
}

const LABELS: Record<StepId, TextKey> = {
  upload: "step.upload",
  header: "step.header",
  columns: "step.columns",
  questions: "step.questions",
  preview: "step.preview",
  approve: "step.approve",
};

/** The route of the import. Finished steps can be revisited unless locked; later ones cannot be skipped to. */
export function Stepper({ steps, onSelect }: { steps: StepItem[]; onSelect(id: StepId): void }) {
  const { t } = useI18n();
  return (
    <nav aria-label={t("step.nav")}>
      <ol className="stepper">
        {steps.map((step, position) => (
          <li
            key={step.id}
            className={`stepper__item stepper__item--${step.state}`}
            aria-current={step.state === "current" ? "step" : undefined}
            title={step.locked ? t("step.lockedHint") : undefined}
          >
            <span className="stepper__index" aria-hidden="true">
              {step.state === "done" ? "✓" : position + 1}
            </span>
            {step.locked ? (
              <span className="stepper__label">
                {t(LABELS[step.id])} <span className="stepper__lock">{t("step.locked")}</span>
              </span>
            ) : step.state === "done" ? (
              <button type="button" className="stepper__link" onClick={() => onSelect(step.id)}>
                {t(LABELS[step.id])}
              </button>
            ) : (
              <span className="stepper__label">{t(LABELS[step.id])}</span>
            )}
          </li>
        ))}
      </ol>
    </nav>
  );
}
