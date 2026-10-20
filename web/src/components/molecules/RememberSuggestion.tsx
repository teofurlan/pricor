import { useState } from "react";
import type { Question } from "../../api/types";
import { useI18n } from "../../i18n";
import { Button } from "../atoms/Button";

/** True when the user chose exactly what Gemma suggested, the only answer worth remembering. */
export function acceptedModelSuggestion(question: Question, answer: string | undefined): boolean {
  return (
    answer !== undefined &&
    answer === question.suggestion?.option &&
    ["model", "gemma"].includes(question.suggestion.suggested_by)
  );
}

/** "Remember this" for an accepted Gemma suggestion; nothing is remembered without this press. */
export function RememberSuggestion({ questionId, disabled = false, onRemember }: {
  questionId: string;
  disabled?: boolean;
  onRemember(questionId: string): Promise<string | null>;
}) {
  const { t } = useI18n();
  const [remembering, setRemembering] = useState(false);
  const [remembered, setRemembered] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function remember() {
    setRemembering(true);
    setError(null);
    const message = await onRemember(questionId);
    if (message) setError(message);
    else setRemembered(true);
    setRemembering(false);
  }

  return (
    <div className="question__remember">
      {remembered ? (
        <span className="memory-saved" role="status">{t("memory.saved")}</span>
      ) : (
        <Button disabled={disabled} loading={remembering} onClick={() => void remember()}>{t("memory.remember")}</Button>
      )}
      {error && <span role="alert">{error}</span>}
    </div>
  );
}
