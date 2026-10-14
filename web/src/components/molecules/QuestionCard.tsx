import { useId, useState } from "react";
import type { Question } from "../../api/types";
import { useI18n } from "../../i18n";
import { Button } from "../atoms/Button";
import { SuggestionBadge } from "./SuggestionBadge";

interface Props {
  question: Question;
  answer: string | undefined;
  onAnswer(questionId: string, option: string): void;
  disabled?: boolean;
}

/**
 * One closed question. A model suggestion is shown on its option as a label,
 * but nothing is ever selected until the user picks it.
 */
export function QuestionCard({ question, answer, onAnswer, disabled = false }: Props) {
  const { t, language } = useI18n();
  const [custom, setCustom] = useState("");
  const customId = useId();
  const listed = question.options.some((option) => option.token === answer);
  const customAnswer = answer !== undefined && !listed ? answer.replace(/^constant:/, "") : null;

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
