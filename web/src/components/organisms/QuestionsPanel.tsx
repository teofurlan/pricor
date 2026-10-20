import { useState } from "react";
import { ApiError } from "../../api/client";
import type { AskReply, AskTurn, ColumnState, Memory, Question } from "../../api/types";
import { useI18n } from "../../i18n";
import { Button } from "../atoms/Button";
import { usePendingAction } from "../atoms/usePendingAction";
import { AskGemma } from "../molecules/AskGemma";
import { QuestionCard } from "../molecules/QuestionCard";
import { acceptedModelSuggestion, RememberSuggestion } from "../molecules/RememberSuggestion";
import { SamplePreview, type SampleData } from "../molecules/SamplePreview";

interface Props {
  questions: Question[];
  answers: Record<string, string>;
  busy: boolean;
  /** Something other than a question still blocks the preview (a missing exchange rate). */
  blocked?: boolean;
  onAnswer(questionId: string, option: string): void;
  onContinue(): void;
  memories?: Memory[];
  onRemember?(questionId: string): Promise<string | null>;
  /** Asks Gemma about one question; absent when no model client is wired. */
  onAsk?(questionId: string, message: string, history: AskTurn[]): Promise<AskReply>;
  sample?: SampleData | null;
  columns?: ColumnState[];
  finalCosts?: Array<string | null>;
}

/**
 * A guided conversation: answered questions stay above as a history that can be reopened,
 * and only the next open question is asked in full. The keys remain the only way to answer.
 */
export function QuestionsPanel({
  questions,
  answers,
  busy,
  blocked = false,
  onAnswer,
  onContinue,
  memories = [],
  onRemember,
  onAsk,
  sample,
  columns = [],
  finalCosts,
}: Props) {
  const { t, language } = useI18n();
  const pending = usePendingAction<"continue">(busy);
  const [reopened, setReopened] = useState<string | null>(null);
  const [threads, setThreads] = useState<Record<string, AskTurn[]>>({});
  const [asking, setAsking] = useState<Record<string, boolean>>({});
  const [askErrors, setAskErrors] = useState<Record<string, string | null>>({});
  const [chatSuggestions, setChatSuggestions] = useState<Record<string, string | null>>({});

  const open = questions.filter((item) => answers[item.id] === undefined);
  const answered = questions.filter((item) => answers[item.id] !== undefined && item.id !== reopened);
  const current = questions.find((item) => item.id === reopened) ?? open[0] ?? null;

  function answerLabel(item: Question): string {
    const token = answers[item.id];
    const option = item.options.find((candidate) => candidate.token === token);
    return option ? option.label[language] : t("question.custom.chosen", { value: token.replace(/^constant:/, "") });
  }

  function answer(questionId: string, option: string) {
    if (questionId === reopened) setReopened(null);
    onAnswer(questionId, option);
  }

  async function ask(questionId: string, message: string) {
    if (!onAsk) return;
    const history = threads[questionId] ?? [];
    setThreads((all) => ({ ...all, [questionId]: [...history, { role: "user", text: message }] }));
    setAsking((all) => ({ ...all, [questionId]: true }));
    setAskErrors((all) => ({ ...all, [questionId]: null }));
    try {
      // The server reads at most the last six turns of a question's conversation.
      const result = await onAsk(questionId, message, history.slice(-6));
      setThreads((all) => ({ ...all, [questionId]: [...(all[questionId] ?? []), { role: "model", text: result.reply }] }));
      setChatSuggestions((all) => ({ ...all, [questionId]: result.suggested_option }));
    } catch (failure) {
      const text = failure instanceof ApiError && failure.status === 503 ? t("ask.unavailable") : failure instanceof Error ? failure.message : String(failure);
      setAskErrors((all) => ({ ...all, [questionId]: text }));
    } finally {
      setAsking((all) => ({ ...all, [questionId]: false }));
    }
  }

  return (
    <div className="stack">
      {questions.length === 0 && <p className="empty-state">{t("questions.none")}</p>}
      {questions.some((question) => question.suggestion && !question.suggestion.calibrated) && <p className="hint">{t("suggestion.legend")}</p>}
      {answered.length > 0 && (
        <ol className="exchanges" aria-label={t("questions.history")}>
          {answered.map((item) => (
            <li key={item.id} className="exchange">
              <span className="exchange__question">{item.text[language]}</span>
              <span className="exchange__answer">{answerLabel(item)}</span>
              <Button variant="link" className="exchange__change" onClick={() => setReopened(item.id)}>{t("questions.change")}</Button>
              {onRemember && acceptedModelSuggestion(item, answers[item.id]) && (
                <div className="exchange__remember"><RememberSuggestion questionId={item.id} onRemember={onRemember} /></div>
              )}
            </li>
          ))}
        </ol>
      )}
      {current && (
        <div className="exchange-current">
          <QuestionCard
            key={current.id}
            question={current}
            answer={answers[current.id]}
            onAnswer={answer}
            memories={memories}
            onRemember={onRemember}
            chatSuggestion={chatSuggestions[current.id] ?? null}
          />
          {onAsk && (
            <AskGemma
              thread={threads[current.id] ?? []}
              pending={asking[current.id] ?? false}
              error={askErrors[current.id] ?? null}
              onAsk={(message) => void ask(current.id, message)}
            />
          )}
        </div>
      )}
      <div className="actions">
        <Button variant="primary" disabled={busy || blocked || open.length > 0} loading={pending.isLoading("continue")} onClick={() => { pending.mark("continue"); onContinue(); }}>
          {t("questions.continue")}
        </Button>
        {open.length > 0 && <span className="hint">{t("questions.remaining", { count: open.length })}</span>}
      </div>
      {sample && sample.rows.length > 0 && (
        <SamplePreview
          sample={sample}
          columns={columns}
          showFinalCost
          finalCosts={finalCosts}
        />
      )}
    </div>
  );
}
