import { useId, useState } from "react";
import type { Memory, Question } from "../../api/types";
import { useI18n } from "../../i18n";
import { Button } from "../atoms/Button";
import { SuggestionBadge } from "./SuggestionBadge";
import { MemoryCitation } from "./MemoryCitation";
import { acceptedModelSuggestion, RememberSuggestion } from "./RememberSuggestion";

interface Props {
  question: Question;
  answer: string | undefined;
  onAnswer(questionId: string, option: string): void;
  disabled?: boolean;
  memories?: Memory[];
  onRemember?(questionId: string): Promise<string | null>;
  /** An option Gemma suggested in the side conversation; marked, never selected. */
  chatSuggestion?: string | null;
}

/**
 * One closed question. A model suggestion is shown on its option as a label,
 * but nothing is ever selected until the user picks it.
 */
export function QuestionCard({ question, answer, onAnswer, disabled = false, memories = [], onRemember, chatSuggestion = null }: Props) {
  const { t, language } = useI18n();
  const [custom, setCustom] = useState("");
  const customId = useId();
  const listed = question.options.some((option) => option.token === answer);
  const customAnswer = answer !== undefined && !listed ? answer.replace(/^constant:/, "") : null;
  const suggestionAccepted = acceptedModelSuggestion(question, answer);

  return (
    <fieldset className="question" disabled={disabled}>
      <legend className="question__text">{question.text[language]}</legend>
      <p className="question__reason">{t("question.reason", { reason: question.reason })}</p>
      {question.model_phrasing && <p className="question__phrasing">{question.model_phrasing}</p>}
      <div className="question__options">
        {question.options.map((option) => {
          const isSelected = answer === option.token;
          return (
            <label key={option.token} className={`choice choice--key${isSelected ? " choice--pressed" : ""}`}>
              <input
                type="radio"
                className="sr-only"
                name={question.id}
                value={option.token}
                checked={isSelected}
                onChange={() => onAnswer(question.id, option.token)}
              />
              <span className="choice__mark" aria-hidden="true">
                {isSelected ? "✓" : ""}
              </span>
              <span className="choice__label">{option.label[language]}</span>
              {question.suggestion?.option === option.token && <SuggestionBadge suggestion={question.suggestion} />}
              {chatSuggestion === option.token && <span className="badge badge--chat">{t("ask.suggested")}</span>}
            </label>
          );
        })}
      </div>
      <MemoryCitation memoryIds={question.suggestion?.memory_ids} memories={memories} />
      {suggestionAccepted && onRemember && <RememberSuggestion questionId={question.id} disabled={disabled} onRemember={onRemember} />}
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
