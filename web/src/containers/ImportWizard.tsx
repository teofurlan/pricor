import { useEffect, useMemo, useRef, useState } from "react";
import type { ApiClient, ApiError, MemoryApiClient } from "../api/client";
import type { ColumnRole, CreateImportInput, Memory, Question, SessionState } from "../api/types";
import { Button } from "../components/atoms/Button";
import { CountsSummary } from "../components/molecules/CountsSummary";
import { NoticeList } from "../components/molecules/NoticeList";
import { type SampleData } from "../components/molecules/SamplePreview";
import { ApprovePanel } from "../components/organisms/ApprovePanel";
import { ColumnsTable } from "../components/organisms/ColumnsTable";
import { ErrorBanner } from "../components/organisms/ErrorBanner";
import { FxPanel } from "../components/organisms/FxPanel";
import { HeaderChoice } from "../components/organisms/HeaderChoice";
import { LanguageToggle } from "../components/organisms/LanguageToggle";
import { PreviewTable } from "../components/organisms/PreviewTable";
import { QuestionsPanel } from "../components/organisms/QuestionsPanel";
import { ReuseBanner } from "../components/organisms/ReuseBanner";
import { RejectedList } from "../components/organisms/RejectedList";
import { Stepper, type StepId, type StepItem } from "../components/organisms/Stepper";
import { UploadForm } from "../components/organisms/UploadForm";
import { useI18n, type TextKey } from "../i18n";
import { PriceChanges } from "./PriceChanges";
import { MemoryPanelContainer } from "./MemoryPanelContainer";
import { toApiError, usePreview } from "./usePreview";

const TITLES: Record<StepId, { title: TextKey; lede: TextKey }> = {
  upload: { title: "title.upload", lede: "lede.upload" },
  header: { title: "title.header", lede: "lede.header" },
  columns: { title: "title.columns", lede: "lede.columns" },
  questions: { title: "title.questions", lede: "lede.questions" },
  preview: { title: "title.preview", lede: "lede.preview" },
  approve: { title: "title.approve", lede: "lede.approve" },
};

function stepAfterColumns(session: SessionState): StepId {
  if (session.status === "role_confirmation_required") return "columns";
  return session.status === "questions_pending" || session.status === "fx_rate_required" ? "questions" : "preview";
}

/** Owns the import session and the calls to the API; the steps themselves are presentational. */
export function ImportWizard({ api }: { api: ApiClient }) {
  const { t } = useI18n();
  const [session, setSession] = useState<SessionState | null>(null);
  const [step, setStep] = useState<StepId>("upload");
  const [headerNeeded, setHeaderNeeded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  // The server only lists open questions; answered ones are remembered here so they stay changeable.
  const [askedQuestions, setAskedQuestions] = useState<Question[]>([]);
  const [memories, setMemories] = useState<Memory[]>([]);
  const [memoryOpen, setMemoryOpen] = useState(false);
  const memoryApi = "listMemories" in api ? (api as ApiClient & MemoryApiClient) : null;

  // Optimistic answers & serialized request queue
  const [localAnswers, setLocalAnswers] = useState<Record<string, string>>({});
  const answerQueueRef = useRef<Promise<void>>(Promise.resolve());
  const pendingAnswersRef = useRef<Record<string, string>>({});
  const [answeringCount, setAnsweringCount] = useState(0);
  const [sample, setSample] = useState<SampleData | null>(null);

  useEffect(() => {
    if (session?.id) {
      api.getSample(session.id, 5)
        .then(setSample)
        .catch(() => setSample(null));
    } else {
      setSample(null);
    }
  }, [session?.id, session?.header?.row_index]);

  const effectiveAnswers = useMemo(
    () => ({ ...(session?.answers ?? {}), ...localAnswers }),
    [session?.answers, localAnswers],
  );

  const remember = (next: SessionState) => {
    setSession(next);
    setAskedQuestions((known) => {
      const fresh = next.questions.filter((item) => !known.some((old) => old.id === item.id));
      const updated = known.map((old) => next.questions.find((item) => item.id === old.id) ?? old);
      return [...updated, ...fresh];
    });
  };
  const visibleQuestions = session
    ? askedQuestions.filter(
        (item) => session.questions.some((open) => open.id === item.id) || item.id in effectiveAnswers,
      )
    : [];

  const previewEnabled =
    session !== null &&
    (step === "preview" || step === "approve" || (step === "questions" && session.status === "ready_for_preview"));
  const preview = usePreview(api, session?.id ?? null, previewEnabled);

  const finalCosts = preview.page?.items
    ? preview.page.items
        .slice(0, 5)
        .map((item) =>
          item.record?.unit_cost_net ? `${item.record.unit_cost_net} ${item.record.currency ?? ""}`.trim() : null,
        )
    : undefined;

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (failure) {
      setError(toApiError(failure));
    } finally {
      setBusy(false);
    }
  }

  const upload = (input: CreateImportInput) =>
    run(async () => {
      const created = await api.createImport(input);
      setAskedQuestions([]);
      remember(created);
      const needsHeader = created.status === "header_choice_required";
      setHeaderNeeded(needsHeader);
      setStep(needsHeader ? "header" : "columns");
    });

  const chooseHeader = (rowIndex: number | null) =>
    run(async () => {
      if (!session) return;
      remember(await api.chooseHeader(session.id, rowIndex));
      setStep("columns");
    });

  const confirmColumns = (edits: Record<number, ColumnRole>) =>
    run(async () => {
      if (!session) return;
      const next = Object.keys(edits).length > 0 ? await api.setRoles(session.id, edits) : session;
      remember(next);
      setStep(stepAfterColumns(next));
    });

  const answer = (questionId: string, option: string) => {
    if (!session) return;
    const sessionId = session.id;
    // Show the selection immediately
    setLocalAnswers((prev) => ({ ...prev, [questionId]: option }));
    pendingAnswersRef.current[questionId] = option;
    setAnsweringCount((count) => count + 1);

    // Chain onto the queue to send answers to the server in order
    answerQueueRef.current = answerQueueRef.current
      .then(async () => {
        try {
          const next = await api.answer(sessionId, questionId, option);
          if (pendingAnswersRef.current[questionId] === option) {
            delete pendingAnswersRef.current[questionId];
          }
          remember(next);
          setLocalAnswers(() => ({ ...next.answers, ...pendingAnswersRef.current }));
        } catch (failure) {
          setError(toApiError(failure));
        } finally {
          setAnsweringCount((count) => Math.max(0, count - 1));
        }
      });
  };

  const setManualRate = (rate: string) =>
    run(async () => {
      if (!session) return;
      remember(await api.setManualRate(session.id, rate));
    });

  const refreshRate = () =>
    run(async () => {
      if (!session) return;
      remember(await api.refreshRate(session.id));
    });

  const approve = () =>
    run(async () => {
      if (!session) return;
      setSession(await api.approve(session.id));
    });

  async function rememberSuggestion(questionId: string): Promise<string | null> {
    if (!session || !memoryApi) return null;
    try {
      const created = await memoryApi.rememberSuggestion(session.id, questionId);
      setMemories((known) => known.some((item) => item.id === created.id) ? known : [...known, created]);
      return null;
    } catch (failure) {
      return failure instanceof Error ? failure.message : String(failure);
    }
  }

  function select(id: StepId) {
    setError(null);
    if (id === "upload") {
      setSession(null);
      setHeaderNeeded(false);
      setLocalAnswers({});
      pendingAnswersRef.current = {};
      setSample(null);
    }
    setStep(id);
  }

  const order: StepId[] = ["upload", ...(headerNeeded ? (["header"] as const) : []), "columns", "questions", "preview", "approve"];
  const current = order.indexOf(step);
  const steps: StepItem[] = order.map((id, position) => ({
    id,
    state: position < current ? "done" : position === current ? "current" : "upcoming",
  }));

  const links = (id: string) => ({
    products: { csv: api.exportUrl(id, "csv"), xlsx: api.exportUrl(id, "xlsx") },
    rejected: { csv: api.rejectedUrl(id, "csv"), xlsx: api.rejectedUrl(id, "xlsx") },
  });

  const loadingPreview = <div className="stack" role="status" aria-live="polite"><p className="lede">{t("common.loading")}</p><div className="loading-rules" aria-hidden="true"><span /><span /><span /></div></div>;

  return (
    <div className="shell">
      <header className="masthead">
        <div className="masthead__brand">
          <span className="masthead__name">{t("app.name")}</span>
          <span className="masthead__promise">{t("app.promise")}</span>
        </div>
        <div className="masthead__tools">
          {memoryApi && <Button variant="quiet" onClick={() => setMemoryOpen(true)}>{t("memory.open")}</Button>}
          <LanguageToggle />
        </div>
      </header>
      {memoryApi && (
        <MemoryPanelContainer
          api={memoryApi}
          open={memoryOpen}
          onClose={() => setMemoryOpen(false)}
          onMemoriesChange={setMemories}
        />
      )}
      <div className="layout">
        <aside className="rail">
          <Stepper steps={steps} onSelect={select} />
          {session && (
            <dl className="rail__session">
              <dt>{t("session.supplier")}</dt>
              <dd>{session.supplier_name}</dd>
              <dt>{t("session.file")}</dt>
              <dd>{session.file_name}</dd>
            </dl>
          )}
        </aside>
        <main className="stage">
          <h1 className="stage__title">{t(TITLES[step].title)}</h1>
          <p className="stage__lede">{t(TITLES[step].lede)}</p>
          {session && <NoticeList notices={session.notices} />}
          <ErrorBanner error={error ?? preview.error} />
          {busy && <p className="working" aria-live="polite">{t("common.working")}</p>}

          {step === "upload" && (
            <UploadForm
              busy={busy}
              onSubmit={upload}
              onInspectSheets={(file) => api.listSheets(file)}
            />
          )}
          {step === "header" && session && (
            <HeaderChoice candidates={session.header.candidates} busy={busy} onChoose={chooseHeader} />
          )}
          {step === "columns" && session?.mode === "reuse" && session.based_on_plan_version !== null && (
            <ReuseBanner
              version={session.based_on_plan_version}
              supplier={session.supplier_name}
              changes={session.changes}
            />
          )}
          {step === "columns" && session && (
            <ColumnsTable
              key={session.columns.map((item) => `${item.role}:${item.decided_by}`).join(",")}
              columns={session.columns}
              issues={session.role_issues}
              busy={busy}
              sample={sample}
              onConfirm={confirmColumns}
            />
          )}
          {step === "questions" && session && (
            <>
              <QuestionsPanel
                questions={visibleQuestions}
                answers={effectiveAnswers}
                busy={busy || answeringCount > 0}
                blocked={session.status === "fx_rate_required"}
                onAnswer={answer}
                onContinue={async () => {
                  await answerQueueRef.current;
                  setStep("preview");
                }}
                memories={memories}
                onRemember={memoryApi ? rememberSuggestion : undefined}
                sample={sample}
                columns={session.columns}
                finalCosts={finalCosts}
              />
              {session.fx && (
                <FxPanel fx={session.fx} busy={busy} onManual={setManualRate} onRefresh={refreshRate} />
              )}
            </>
          )}
          {step === "preview" &&
            (preview.page ? (
              <div className="stack">
                <CountsSummary totals={preview.page.totals} />
                {session?.fx && (
                  <FxPanel fx={session.fx} busy={busy} onManual={setManualRate} onRefresh={refreshRate} />
                )}
                <PreviewTable
                  page={preview.page}
                  busy={preview.loading}
                  onPage={(offset) => void preview.load(offset)}
                  fx={session?.fx ?? null}
                />
                <section className="stack">
                  <h2 className="subtitle">{t("rejected.title", { count: preview.page.totals.rejected })}</h2>
                  <RejectedList rows={preview.page.totals.rejected_rows} />
                </section>
                <div className="actions">
                  <Button variant="primary" onClick={() => setStep("approve")}>
                    {t("preview.continue")}
                  </Button>
                </div>
              </div>
            ) : (
              loadingPreview
            ))}
          {step === "approve" &&
            session &&
            (preview.page ? (
              <div className="stack">
                <ApprovePanel
                  totals={preview.page.totals}
                  approved={session.approved}
                  busy={busy}
                  links={links(session.id)}
                  supplier={session.supplier_name}
                  file={session.file_name}
                  onApprove={approve}
                />
                {session.approved && (
                  <PriceChanges api={api} sessionId={session.id} supplierName={session.supplier_name} />
                )}
              </div>
            ) : (
              loadingPreview
            ))}
        </main>
      </div>
    </div>
  );
}
