import type { Question } from "../../api/types";
import { useI18n } from "../../i18n";
import { Button } from "../atoms/Button";
import { QuestionCard } from "../molecules/QuestionCard";

interface Props {
  questions: Question[];
  answers: Record<string, string>;
  busy: boolean;
  /** Something other than a question still blocks the preview (a missing exchange rate). */
  blocked?: boolean;
  onAnswer(questionId: string, option: string): void;
  onContinue(): void;
}

export function QuestionsPanel({ questions, answers, busy, blocked = false, onAnswer, onContinue }: Props) {
  const { t } = useI18n();
  const open = questions.filter((item) => answers[item.id] === undefined);
  return (
    <div className="stack">
      {questions.length === 0 && <p className="lede">{t("questions.none")}</p>}
      {questions.map((item) => (
        <QuestionCard key={item.id} question={item} answer={answers[item.id]} onAnswer={onAnswer} disabled={busy} />
      ))}
      <div className="actions">
        <Button variant="primary" disabled={busy || blocked || open.length > 0} onClick={onContinue}>
          {t("questions.continue")}
        </Button>
        {open.length > 0 && <span className="hint">{t("questions.remaining", { count: open.length })}</span>}
      </div>
    </div>
  );
}
