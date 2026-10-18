import { useId, useState } from "react";
import type { Memory, Question } from "../../api/types";
import { useI18n } from "../../i18n";
import { Button } from "../atoms/Button";
import { SuggestionBadge } from "./SuggestionBadge";
import { MemoryCitation } from "./MemoryCitation";

interface Props {
  question: Question;
  answer: string | undefined;
  onAnswer(questionId: string, option: string): void;
  disabled?: boolean;
  memories?: Memory[];
  onRemember?(questionId: string): Promise<string | null>;
}

/**
 * One closed question. A model suggestion is shown on its option as a label,
 * but nothing is ever selected until the user picks it.
 */
export function QuestionCard({ question, answer, onAnswer, disabled = false, memories = [], onRemember }: Props) {
  const { t, language } = useI18n();
  const [custom, setCustom] = useState("");
  const [remembering, setRemembering] = useState(false);
  const [remembered, setRemembered] = useState(false);
  const [rememberError, setRememberError] = useState<string | null>(null);
  const customId = useId();
  const listed = question.options.some((option) => option.token === answer);
  const customAnswer = answer !== undefined && !listed ? answer.replace(/^constant:/, "") : null;
  const suggestionAccepted =
    answer !== undefined &&
    answer === question.suggestion?.option &&
    ["model", "gemma"].includes(question.suggestion.suggested_by);

  async function rememberSuggestion() {
    if (!onRemember) return;
    setRemembering(true);
    setRememberError(null);
    const message = await onRemember(question.id);
    if (message) setRememberError(message);
    else setRemembered(true);
    setRemembering(false);
  }

  return (
    <fieldset className="question" disabled={disabled}>
      <legend className="question__text">{question.text[language]}</legend>
      <p className="question__reason">{t("question.reason", { reason: question.reason })}</p>
      {question.model_phrasing && <p className="question__phrasing">{question.model_phrasing}</p>}
      <div className="question__options">
        {question.options.map((option) => (
          <label key={option.token} className="choice">
            <input
              type="radio"
              name={question.id}
              value={option.token}
              checked={answer === option.token}
              onChange={() => onAnswer(question.id, option.token)}
            />
            <span className="choice__label">{option.label[language]}</span>
            {question.suggestion?.option === option.token && <SuggestionBadge suggestion={question.suggestion} />}
          </label>
        ))}
      </div>
      <MemoryCitation memoryIds={question.suggestion?.memory_ids} memories={memories} />
      {suggestionAccepted && onRemember && (
        <div className="question__remember">
          {remembered ? (
            <span className="memory-saved" role="status">{t("memory.saved")}</span>
          ) : (
            <Button disabled={disabled || remembering} onClick={() => void rememberSuggestion()}>{t("memory.remember")}</Button>
          )}
          {rememberError && <span role="alert">{rememberError}</span>}
        </div>
      )}
      {question.allows_custom && (
        <div className="question__custom">
          <label htmlFor={customId}>{t("question.custom.label")}</label>
          <input id={customId} inputMode="decimal" value={custom} onChange={(event) => setCustom(event.target.value)} />
          <Button disabled={custom.trim() === ""} onClick={() => onAnswer(question.id, `constant:${custom.trim()}`)}>
            {t("question.custom.use")}
          </Button>
          {customAnswer !== null && (
            <span className="question__chosen">{t("question.custom.chosen", { value: customAnswer })}</span>
          )}
        </div>
      )}
    </fieldset>
  );
}
