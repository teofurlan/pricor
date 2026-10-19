import type { ColumnState, Memory, Question } from "../../api/types";
import { useI18n } from "../../i18n";
import { Button } from "../atoms/Button";
import { QuestionCard } from "../molecules/QuestionCard";
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
  sample?: SampleData | null;
  columns?: ColumnState[];
  finalCosts?: Array<string | null>;
}

export function QuestionsPanel({
  questions,
  answers,
  busy,
  blocked = false,
  onAnswer,
  onContinue,
  memories = [],
  onRemember,
  sample,
  columns = [],
  finalCosts,
}: Props) {
  const { t } = useI18n();
  const open = questions.filter((item) => answers[item.id] === undefined);
  return (
    <div className="stack">
      {questions.length === 0 && <p className="empty-state">{t("questions.none")}</p>}
      {questions.some((question) => question.suggestion && !question.suggestion.calibrated) && <p className="hint">{t("suggestion.legend")}</p>}
      {questions.map((item) => (
        <QuestionCard key={item.id} question={item} answer={answers[item.id]} onAnswer={onAnswer} memories={memories} onRemember={onRemember} />
      ))}
      <div className="actions">
        <Button variant="primary" disabled={busy || blocked || open.length > 0} onClick={onContinue}>
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
