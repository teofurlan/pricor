import { useEffect, useMemo, useRef, useState } from "react";
import type { ApiClient, ApiError, ExportFile, ExportSheet, MemoryApiClient, OutputFormatApiClient } from "../api/client";
import { useServerConfig } from "../api/serverConfig";
import type { ColumnRole, CreateImportInput, Memory, Question, SessionState } from "../api/types";
import { Button } from "../components/atoms/Button";
import { TapeLoader } from "../components/atoms/TapeLoader";
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
import { OutputFormatContainer } from "./OutputFormatContainer";
import { toApiError, usePreview } from "./usePreview";

// Steps that change the plan; the server refuses them once the import is approved.
const PLAN_STEPS: StepId[] = ["header", "columns", "questions"];

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
  const { hosted } = useServerConfig();
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
  const formatApi = "getOutputFormat" in api ? (api as ApiClient & OutputFormatApiClient) : null;

  // Optimistic answers & serialized request queue
  const [localAnswers, setLocalAnswers] = useState<Record<string, string>>({});
  const answerQueueRef = useRef<Promise<void>>(Promise.resolve());
  const pendingAnswersRef = useRef<Record<string, string>>({});
  const [answeringCount, setAnsweringCount] = useState(0);
  // Bumped for every new import, so a late reply about the previous one is ignored.
  const generationRef = useRef(0);
  const sessionRef = useRef<SessionState | null>(null);
  const [sample, setSample] = useState<SampleData | null>(null);
  const [sheets, setSheets] = useState<Partial<Record<ExportFile, ExportSheet>>>({});
  // A rate changed on the preview step reloads it; say so, since the figures move under the user.
  const [rateChanged, setRateChanged] = useState(false);
  useEffect(() => setRateChanged(false), [step]);
  const approvedId = session?.approved ? session.id : null;

  // The file preview reads the exported file itself, so it can only exist once the user signed.
  useEffect(() => {
    setSheets({});
    if (!approvedId) return;
    let active = true;
    for (const file of ["products", "rejected"] as const) {
      api.exportSheet(approvedId, file)
        .then((loaded) => { if (active) setSheets((current) => ({ ...current, [file]: loaded })); })
        // The downloads stay available; a preview is a convenience and is simply left out.
        .catch(() => undefined);
    }
    return () => { active = false; };
  }, [api, approvedId]);

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
    sessionRef.current = next;
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
  // Everything the server uses to compute the preview; when it changes, the preview is stale.
  const planRevision = session
    ? JSON.stringify([session.header.row_index, session.columns.map((item) => item.role), session.answers, session.fx?.snapshot])
    : "";
  const preview = usePreview(api, session?.id ?? null, previewEnabled, planRevision);

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

  /** Drop answers not yet confirmed; the server's answers are the truth from now on. */
  function forgetLocalAnswers() {
    setLocalAnswers({});
    pendingAnswersRef.current = {};
  }

  /** Start over: no answer still in flight may touch the next import. */
  function resetAnswerQueue() {
    generationRef.current += 1;
    answerQueueRef.current = Promise.resolve();
    setAnsweringCount(0);
    forgetLocalAnswers();
  }

  const upload = (input: CreateImportInput) =>
    run(async () => {
      resetAnswerQueue();
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
      // The server clears every answer when the header changes.
      forgetLocalAnswers();
      setStep("columns");
    });

  const confirmColumns = (edits: Record<number, ColumnRole>) =>
    run(async () => {
      if (!session) return;
      const next = Object.keys(edits).length > 0 ? await api.setRoles(session.id, edits) : session;
      remember(next);
      if (next !== session) forgetLocalAnswers();
      setStep(stepAfterColumns(next));
    });

  const answer = (questionId: string, option: string) => {
    if (!session) return;
    const sessionId = session.id;
    const generation = generationRef.current;
    // Show the selection immediately
    setLocalAnswers((prev) => ({ ...prev, [questionId]: option }));
    pendingAnswersRef.current[questionId] = option;
    setAnsweringCount((count) => count + 1);

    // Chain onto the queue to send answers to the server in order
    answerQueueRef.current = answerQueueRef.current
      .then(async () => {
        if (generation !== generationRef.current) return; // a new import started meanwhile
        try {
          const next = await api.answer(sessionId, questionId, option);
          if (generation !== generationRef.current) return;
          if (pendingAnswersRef.current[questionId] === option) {
            delete pendingAnswersRef.current[questionId];
          }
          remember(next);
          setLocalAnswers(() => ({ ...next.answers, ...pendingAnswersRef.current }));
        } catch (failure) {
          if (generation !== generationRef.current) return;
          // A refused answer must not stay on screen as chosen; fall back to the server's answer.
          if (pendingAnswersRef.current[questionId] === option) {
            delete pendingAnswersRef.current[questionId];
            setLocalAnswers(({ [questionId]: _refused, ...rest }) => rest);
          }
          setError(toApiError(failure));
        } finally {
          if (generation === generationRef.current) setAnsweringCount((count) => Math.max(0, count - 1));
        }
      });
  };

  const changeRate = (call: (sessionId: string) => Promise<SessionState>) =>
    run(async () => {
      if (!session) return;
      const next = await call(session.id);
      remember(next);
      if (step === "preview" && JSON.stringify(next.fx?.snapshot) !== JSON.stringify(session.fx?.snapshot)) {
        setRateChanged(true);
      }
    });
  const setManualRate = (rate: string) => changeRate((sessionId) => api.setManualRate(sessionId, rate));
  const refreshRate = () => changeRate((sessionId) => api.refreshRate(sessionId));

  const approve = () =>
    run(async () => {
      if (!session) return;
      const approved = await api.approve(session.id);
      sessionRef.current = approved;
      setSession(approved);
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
      sessionRef.current = null;
      setHeaderNeeded(false);
      resetAnswerQueue();
      setSample(null);
    }
    setStep(id);
  }

  const order: StepId[] = ["upload", ...(headerNeeded ? (["header"] as const) : []), "columns", "questions", "preview", "approve"];
  const current = order.indexOf(step);
  const steps: StepItem[] = order.map((id, position) => ({
    id,
    state: position < current ? "done" : position === current ? "current" : "upcoming",
    locked: session?.approved === true && PLAN_STEPS.includes(id),
  }));

  const links = (id: string) => ({
    products: { csv: api.exportUrl(id, "csv"), xlsx: api.exportUrl(id, "xlsx") },
    rejected: { csv: api.rejectedUrl(id, "csv"), xlsx: api.rejectedUrl(id, "xlsx") },
  });

  const loadingPreview = <div className="stack"><TapeLoader text={t("common.loading")} /><div className="loading-rules" aria-hidden="true"><span /><span /><span /></div></div>;

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
          <p className="stage__lede">{t(step === "upload" && hosted ? "lede.upload.hosted" : TITLES[step].lede)}</p>
          {session && <NoticeList notices={session.notices} compact={step !== "columns"} />}
          <ErrorBanner error={error ?? preview.error} />
          {busy && <div className="working"><TapeLoader size="small" text={t(hosted ? "common.working.hosted" : "common.working")} /></div>}

          {step === "upload" && (
            <div className="upload-step">
              <UploadForm busy={busy} onSubmit={upload} onInspectSheets={(file) => api.listSheets(file)} />
              {formatApi && <OutputFormatContainer api={formatApi} />}
            </div>
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
                  // The last answer may have reopened something; go where the server says.
                  const latest = sessionRef.current;
                  if (latest) setStep(stepAfterColumns(latest));
                }}
                memories={memories}
                onRemember={memoryApi ? rememberSuggestion : undefined}
                onAsk={(questionId, message, history) => api.askQuestion(session.id, questionId, message, history)}
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
                  <FxPanel fx={session.fx} busy={busy} onManual={setManualRate} onRefresh={refreshRate} readOnly={session.approved} />
                )}
                {rateChanged && !preview.loading && (
                  <p role="status" className="fx__updated">{t("preview.rateUpdated")}</p>
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
                  sheets={sheets}
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
