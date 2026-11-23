import { useId, useState } from "react";
import type { Memory, Question } from "../../api/types";
import { useI18n } from "../../i18n";
import { formatTypedValue, localizeServerText } from "../../i18n/serverText";
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

const NUMBER = /^[0-9]+(?:[.,][0-9]+)?$/;

/**
 * The `constant:` token for a typed value, or null when the server would refuse it.
 * A decimal comma is accepted and sent with a decimal point.
 */
function customToken(questionId: string, text: string): string | null {
  const trimmed = text.trim();
  if (!NUMBER.test(trimmed)) return null;
  const value = trimmed.replace(",", ".");
  const number = Number(value);
  if (questionId === "vat_rate" && number > 100) return null;
  if (questionId === "units_per_pack" && number === 0) return null;
  return `constant:${value}`;
}

/**
 * One closed question. A model suggestion is shown on its option as a label,
 * but nothing is ever selected until the user picks it.
 */
export function QuestionCard({ question, answer, onAnswer, disabled = false, memories = [], onRemember, chatSuggestion = null }: Props) {
  const { t, language } = useI18n();
  const [custom, setCustom] = useState("");
  const customId = useId();
  const moreId = useId();
  const listed = question.options.some((option) => option.token === answer);
  const customAnswer = answer !== undefined && !listed ? formatTypedValue(question.id, answer, language) : null;
  const suggestionAccepted = acceptedModelSuggestion(question, answer);
  const primary = question.options.filter((option) => option.group !== "more");
  const more = question.options.filter((option) => option.group === "more");
  const token = customToken(question.id, custom);
  const customInvalid = custom.trim() !== "" && token === null;

  return (
    <fieldset className="question" disabled={disabled}>
      <legend className="question__text">{question.text[language]}</legend>
      <p className="question__reason">{t("question.reason", { reason: localizeServerText(question.reason, language) })}</p>
      {question.model_phrasing && <p className="question__phrasing">{question.model_phrasing}</p>}
      <div className="question__options">
        {primary.map((option) => {
          const isSelected = answer === option.token;
          return (
            <button
              key={option.token}
              type="button"
              className={`choice choice--key${isSelected ? " choice--pressed" : ""}`}
              aria-pressed={isSelected}
              disabled={disabled}
              onClick={() => onAnswer(question.id, option.token)}
            >
              <span className="choice__mark" aria-hidden="true">
                {isSelected ? "✓" : ""}
              </span>
              <span className="choice__label">{option.label[language]}</span>
              {question.suggestion?.option === option.token && <SuggestionBadge suggestion={question.suggestion} />}
              {chatSuggestion === option.token && <span className="badge badge--chat">{t("ask.suggested")}</span>}
            </button>
          );
        })}
      </div>
      {more.length > 0 && (
        <div className="question__custom">
          <label htmlFor={moreId}>{t("question.moreOptions")}</label>
          <select
            id={moreId}
            value={more.some((option) => option.token === answer) ? answer : ""}
            onChange={(event) => event.target.value && onAnswer(question.id, event.target.value)}
          >
            <option value="">{t("question.moreOptions")}</option>
            {more.map((option) => (
              <option key={option.token} value={option.token}>{option.label[language]}</option>
            ))}
          </select>
          {question.suggestion && more.some((option) => option.token === question.suggestion?.option) && (
            <>
              <span>{more.find((option) => option.token === question.suggestion?.option)?.label[language]}</span>
              <SuggestionBadge suggestion={question.suggestion} />
            </>
          )}
          {more.some((option) => option.token === chatSuggestion) && <span className="badge badge--chat">{t("ask.suggested")}</span>}
        </div>
      )}
      <MemoryCitation memoryIds={question.suggestion?.memory_ids} memories={memories} />
      {suggestionAccepted && onRemember && <RememberSuggestion questionId={question.id} disabled={disabled} onRemember={onRemember} />}
      {question.allows_custom && (
        <div className="question__custom">
          <label htmlFor={customId}>{t("question.custom.label")}</label>
          <input
            id={customId}
            inputMode="decimal"
            value={custom}
            aria-invalid={customInvalid}
            aria-describedby={customInvalid ? `${customId}-error` : undefined}
            onChange={(event) => setCustom(event.target.value)}
          />
          <Button disabled={token === null} onClick={() => token && onAnswer(question.id, token)}>
            {t("question.custom.use")}
          </Button>
          {customInvalid && (
            <span id={`${customId}-error`} className="question__invalid">
              {t(question.id === "vat_rate" ? "question.custom.invalidPercent" : "question.custom.invalidPositive")}
            </span>
          )}
          {customAnswer !== null && (
            <span className="question__chosen">{t("question.custom.chosen", { value: customAnswer })}</span>
          )}
        </div>
      )}
    </fieldset>
  );
}
