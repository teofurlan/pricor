import { useEffect, useState } from "react";
import { ApiError } from "../../api/client";
import type { AskReply, AskTurn, ColumnState, Memory, Question } from "../../api/types";
import { useI18n } from "../../i18n";
import { formatTypedValue } from "../../i18n/serverText";
import { Button } from "../atoms/Button";
import { TapeFigure } from "../atoms/TapeFigure";
import { usePendingAction } from "../atoms/usePendingAction";
import { AskGemma } from "../molecules/AskGemma";
import { QuestionCard } from "../molecules/QuestionCard";
import { acceptedModelSuggestion, RememberSuggestion } from "../molecules/RememberSuggestion";
import { SamplePreview, type SampleData } from "../molecules/SamplePreview";

/** Parses a plain decimal string from a sample cell for an illustrative live preview only. */
function parseSampleNumber(raw: string): number | null {
  const cleaned = raw.replace(/[^0-9.,-]/g, "").trim();
  if (!cleaned) return null;
  const lastComma = cleaned.lastIndexOf(",");
  const lastDot = cleaned.lastIndexOf(".");
  let normalized = cleaned;
  if (lastComma > lastDot) {
    normalized = cleaned.replace(/\./g, "").replace(",", ".");
  } else if (lastDot > lastComma) {
    normalized = cleaned.replace(/,/g, "");
  }
  const value = Number(normalized);
  return Number.isFinite(value) ? value : null;
}

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

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if ((event.ctrlKey || event.metaKey) && event.key === "Enter" && !busy && !blocked && open.length === 0) {
        const tag = (event.target as HTMLElement | null)?.tagName;
        if (tag === "TEXTAREA" || tag === "INPUT") return;
        event.preventDefault();
        pending.mark("continue");
        onContinue();
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [busy, blocked, open.length, onContinue, pending]);

  const firstRow = sample && sample.rows.length > 0 ? sample.rows[0] : null;
  const findCol = (role: string) => columns.find((col) => col.role === role);
  const codeCol = findCol("code");
  const descCol = findCol("description");
  const priceCol = findCol("cost_price");
  const rawPrice = firstRow && priceCol ? (firstRow[priceCol.index] ?? "") : "";
  const liveFinal = finalCosts?.[0] ?? null;

  // Build an illustrative live estimate as the merchant answers VAT, pack, or currency rules.
  const liveSteps: Array<{ op: string; label: string; value: string }> = [];
  let estimatedTotal: string | null = liveFinal;
  if (rawPrice && !liveFinal) {
    const parsed = parseSampleNumber(rawPrice);
    if (parsed !== null) {
      let running = parsed;
      const vatIncluded = answers["price_includes_vat"];
      const vatRateToken = answers["vat_rate"];
      if (vatIncluded === "yes" || vatIncluded === "yes_strip") {
        const rate = vatRateToken?.startsWith("constant:") ? Number(vatRateToken.slice("constant:".length)) : 21;
        if (Number.isFinite(rate) && rate > 0) {
          running = running / (1 + rate / 100);
          liveSteps.push({ op: "÷", label: t("trace.strip_vat"), value: running.toFixed(2) });
        }
      }
      const perPack = answers["price_is_per_pack"];
      const packToken = answers["units_per_pack"];
      if (perPack === "yes" && packToken?.startsWith("constant:")) {
        const units = Number(packToken.slice("constant:".length));
        if (Number.isFinite(units) && units > 0) {
          running = running / units;
          liveSteps.push({ op: "÷", label: t("trace.per_unit"), value: running.toFixed(2) });
        }
      }
      const currency = answers["currency"] && !answers["currency"].startsWith("constant:") ? ` ${answers["currency"]}` : "";
      if (liveSteps.length > 0 || currency) {
        estimatedTotal = `${running.toFixed(2)}${currency}`;
      }
    }
  }
  const showLiveTape = Boolean(firstRow && priceCol && rawPrice.trim() !== "");

  function answerLabel(item: Question): string {
    const token = answers[item.id];
    const option = item.options.find((candidate) => candidate.token === token);
    return option ? option.label[language] : t("question.custom.chosen", { value: formatTypedValue(item.id, token, language) });
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

  const questionColumn = (
    <div className="stack">
      {questions.length === 0 && <p className="empty-state">{t("questions.none")}</p>}
      {questions.some((question) => question.suggestion && !question.suggestion.calibrated) && <p className="hint">{t("suggestion.legend")}</p>}
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
      <div className="actions">
        <Button variant="primary" disabled={busy || blocked || open.length > 0} loading={pending.isLoading("continue")} onClick={() => { pending.mark("continue"); onContinue(); }}>
          {t("questions.continue")}
        </Button>
        {open.length > 0 && (
          <span className="hint">
            {t(open.length === 1 ? "questions.remaining.one" : "questions.remaining.other", { count: open.length })}
          </span>
        )}
      </div>
    </div>
  );

  return (
    <div className="stack">
      {showLiveTape ? (
        <div className="workbench workbench--questions">
          {questionColumn}
          <section className="tape tape--sticky tape--live-sample" aria-label={t("questions.liveTitle")}>
            <h2 className="tape__heading">{t("questions.liveTitle")}</h2>
            {codeCol && firstRow?.[codeCol.index] && <p className="tape__reference"># {firstRow[codeCol.index]}</p>}
            {descCol && firstRow?.[descCol.index] && <p className="tape__description">{firstRow[descCol.index]}</p>}
            <ol className="trace">
              <li className="trace__step">
                <span className="trace__operator" aria-hidden="true">#</span>
                <span className="trace__label">{t("questions.liveOriginal")}</span>
                <TapeFigure className="trace__value" language={language} value={rawPrice} fracWidth={3} />
                <span className="trace__mark" aria-hidden="true" />
              </li>
              {liveSteps.map((step) => (
                <li key={step.label} className="trace__step">
                  <span className="trace__operator" aria-hidden="true">{step.op}</span>
                  <span className="trace__label">{step.label}</span>
                  <TapeFigure className="trace__value" language={language} value={step.value} fracWidth={3} />
                  <span className="trace__mark" aria-hidden="true" />
                </li>
              ))}
              {estimatedTotal ? (
                <li className="trace__step trace__step--final">
                  <span className="trace__operator" aria-hidden="true">=</span>
                  <span className="trace__label">{t(liveFinal ? "questions.liveExact" : "questions.liveEstimate")}</span>
                  <TapeFigure className="trace__value" language={language} value={estimatedTotal} fracWidth={3} />
                  <span className="trace__mark" aria-hidden="true">✱</span>
                </li>
              ) : (
                <li className="trace__step">
                  <span className="trace__operator" aria-hidden="true">=</span>
                  <span className="trace__label">{t("questions.livePending")}</span>
                  <span className="trace__value">—</span>
                  <span className="trace__mark" aria-hidden="true" />
                </li>
              )}
            </ol>
            <div className="tape__tear" aria-hidden="true" />
          </section>
        </div>
      ) : (
        questionColumn
      )}
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
