import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ApiClient, ApiError, CombinedExportApiClient, ExportFile, ExportSheet, MemoryApiClient, OutputFormatApiClient, SampleApiClient, WorkspaceApiClient } from "../api/client";
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
import { WorkspacePanel } from "../components/organisms/WorkspacePanel";
import { UploadForm } from "../components/organisms/UploadForm";
import type { QueueDraft } from "../components/organisms/UploadQueue";
import { UploadQueueTray, QueueSummary, type QueueItem } from "../components/organisms/UploadQueueTray";
import { describeError } from "../i18n/serverText";
import { useI18n, type TextKey } from "../i18n";
import { PriceChanges } from "./PriceChanges";
import { MemoryPanelContainer } from "./MemoryPanelContainer";
import { OutputFormatStep } from "./OutputFormatStep";
import { toApiError, usePreview } from "./usePreview";

// Steps that change the plan; the server refuses them once the import is approved.
const PLAN_STEPS: StepId[] = ["header", "columns", "questions", "format"];

const TITLES: Record<StepId, { title: TextKey; lede: TextKey }> = {
  upload: { title: "title.upload", lede: "lede.upload" },
  header: { title: "title.header", lede: "lede.header" },
  columns: { title: "title.columns", lede: "lede.columns" },
  questions: { title: "title.questions", lede: "lede.questions" },
  preview: { title: "title.preview", lede: "lede.preview" },
  format: { title: "title.format", lede: "lede.format" },
  approve: { title: "title.approve", lede: "lede.approve" },
};

function stepAfterColumns(session: SessionState): StepId {
  if (session.status === "role_confirmation_required") return "columns";
  return session.status === "questions_pending" || session.status === "fx_rate_required" ? "questions" : "preview";
}

// React renders a mounting component twice in development; the second pass must still see the token.
let pendingLinkToken: string | null = null;

function takeLinkToken(): string | null {
  if (typeof window === "undefined") return null;
  const match = /^#w=([A-Za-z0-9_-]{43})$/.exec(window.location.hash);
  if (match) {
    pendingLinkToken = match[1];
    window.history.replaceState(window.history.state, "", window.location.pathname + window.location.search);
  }
  return pendingLinkToken;
}

/** Owns the import session and the calls to the API; the steps themselves are presentational. */
export function ImportWizard({ api }: { api: ApiClient }) {
  const { t, language } = useI18n();
  const { hosted, config, loaded } = useServerConfig();
  // In workspace mode the cookie from GET /workspace must exist before any other data call.
  const workspaceApi = typeof (api as Partial<WorkspaceApiClient>).workspace === "function" ? (api as ApiClient & WorkspaceApiClient) : null;
  const workspaceOn = config?.workspaces === true;
  const [workspaceLink, setWorkspaceLink] = useState<string | null>(null);
  const [workspaceSettled, setWorkspaceSettled] = useState(false);
  const workspaceRequested = useRef(false);
  // The token of a personal link (`/#w=<token>`), read once and removed from the URL at once.
  const [linkToken] = useState(takeLinkToken);
  useEffect(() => { pendingLinkToken = null; }, []);
  const [switchPrompt, setSwitchPrompt] = useState(false);
  const continueWithWorkspace = useCallback(() => {
    if (!workspaceApi) {
      setWorkspaceSettled(true);
      return;
    }
    workspaceApi.workspace()
      .then((result) => setWorkspaceLink(result.link))
      .catch(() => {})
      .finally(() => setWorkspaceSettled(true));
  }, [workspaceApi]);
  const claimThenContinue = useCallback(async () => {
    const token = linkToken;
    if (token && workspaceApi) {
      try {
        await workspaceApi.claimWorkspace(token);
      } catch {
        // A refused link leaves the cookie untouched; the normal flow below still gives a workspace.
      }
    }
    continueWithWorkspace();
  }, [workspaceApi, continueWithWorkspace, linkToken]);
  useEffect(() => {
    if (!workspaceOn || workspaceRequested.current) return;
    workspaceRequested.current = true;
    const token = linkToken;
    if (!token || !workspaceApi) {
      continueWithWorkspace();
      return;
    }
    workspaceApi.currentWorkspace()
      .then((current) => {
        if (current === null || current.link.endsWith(`#w=${token}`)) return claimThenContinue();
        setSwitchPrompt(true);
      })
      .catch(() => claimThenContinue());
  }, [workspaceOn, workspaceApi, linkToken, continueWithWorkspace, claimThenContinue]);
  const dataReady = loaded && (!workspaceOn || workspaceSettled);
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
  const sampleApi = typeof (api as Partial<SampleApiClient>).listSamples === "function" ? (api as ApiClient & SampleApiClient) : null;
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
    (step === "preview" || step === "format" || step === "approve" || (step === "questions" && session.status === "ready_for_preview"));
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

  /** Take a freshly created import as the one under review. */
  const open = (created: SessionState) => {
    setAskedQuestions([]);
    remember(created);
    const needsHeader = created.status === "header_choice_required";
    setHeaderNeeded(needsHeader);
    setStep(needsHeader ? "header" : "columns");
  };

  const upload = (input: CreateImportInput) =>
    run(async () => {
      resetAnswerQueue();
      open(await api.createImport(input));
    });

  // Several files: each one stays its own import; the queue only lives here in the client.
  const combinedApi = typeof (api as Partial<CombinedExportApiClient>).downloadCombined === "function" ? (api as ApiClient & CombinedExportApiClient) : null;
  const [queue, setQueue] = useState<QueueItem[] | null>(null);
  const [queueIndex, setQueueIndex] = useState(0);
  const [queueDone, setQueueDone] = useState(false);

  /** Import the first pending file from `from` on; a file that cannot be read is marked failed and the next one is tried. */
  const importFrom = (items: QueueItem[], from: number) =>
    run(async () => {
      let list = items;
      for (let index = from; index < list.length; index += 1) {
        if (list[index].status !== "pending") continue;
        list = list.map((item, position) => (position === index ? { ...item, status: "reviewing" } : item));
        setQueue(list);
        setQueueIndex(index);
        resetAnswerQueue();
        try {
          open(await api.createImport({ file: list[index].file, supplierName: list[index].supplierName, sheet: list[index].sheet, language }));
          return;
        } catch (failure) {
          const reason = failure && typeof (failure as ApiError).code === "string" ? describeError(failure as ApiError, language) : failure instanceof Error ? failure.message : String(failure);
          list = list.map((item, position) => (position === index ? { ...item, status: "failed", error: reason } : item));
        }
      }
      setQueue(list);
      sessionRef.current = null;
      setSession(null);
      setHeaderNeeded(false);
      setSample(null);
      setQueueDone(true);
    });

  const startQueue = (drafts: QueueDraft[]) =>
    void importFrom(drafts.map((draft) => ({ ...draft, sessionId: null, accepted: 0, status: "pending", error: null })), 0);

  const markCurrent = (change: Partial<QueueItem>) =>
    setQueue((items) => items && items.map((item, position) => (position === queueIndex ? { ...item, ...change } : item)));
  const skipCurrent = () => {
    if (!queue) return;
    void importFrom(queue.map((item, position) => (position === queueIndex ? { ...item, status: "skipped" } : item)), queueIndex + 1);
  };

  const downloadCombined = (format: "csv" | "xlsx", kind: ExportFile) =>
    run(async () => {
      if (!combinedApi || !queue) return;
      const ids = queue.filter((item) => item.status === "approved" && item.sessionId).map((item) => item.sessionId as string);
      const { blob, fileName } = await combinedApi.downloadCombined(ids, format, kind);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = fileName;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    });

  function resetQueue() {
    setQueue(null);
    setQueueIndex(0);
    setQueueDone(false);
  }

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
      markCurrent({ status: "approved", sessionId: approved.id, accepted: preview.page?.totals.accepted ?? 0 });
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
      resetQueue();
      setSession(null);
      sessionRef.current = null;
      setHeaderNeeded(false);
      resetAnswerQueue();
      setSample(null);
    }
    setStep(id);
  }

  const order: StepId[] = ["upload", ...(headerNeeded ? (["header"] as const) : []), "columns", "questions", "preview", ...(formatApi ? (["format"] as const) : []), "approve"];
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
      {memoryApi && dataReady && (
        <MemoryPanelContainer
          api={memoryApi}
          open={memoryOpen}
          onClose={() => setMemoryOpen(false)}
          onMemoriesChange={setMemories}
        />
      )}
      <div className="layout">
        <aside className="rail">
          {queue && <UploadQueueTray items={queue} />}
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
          <h1 className="stage__title">{queueDone ? t("queue.title.done") : t(TITLES[step].title)}</h1>
          <p className="stage__lede">{queueDone ? t("queue.lede.done") : t(step === "upload" && hosted ? "lede.upload.hosted" : TITLES[step].lede)}</p>
          {session && <NoticeList notices={session.notices} compact={step !== "columns"} />}
          <ErrorBanner error={error ?? preview.error} />
          {queue && !queueDone && session && !session.approved && (
            <div className="actions"><Button variant="quiet" disabled={busy} onClick={skipCurrent}>{t("queue.skip")}</Button></div>
          )}
          {busy && <div className="working"><TapeLoader size="small" text={t(hosted ? "common.working.hosted" : "common.working")} /></div>}

          {switchPrompt && (
            <div className="workspace-switch" role="alertdialog" aria-labelledby="workspace-switch-body">
              <p id="workspace-switch-body">{t("workspace.switch.body")}</p>
              <div className="workspace-switch__actions">
                <Button variant="primary" onClick={() => { setSwitchPrompt(false); void claimThenContinue(); }}>{t("workspace.switch.confirm")}</Button>
                <Button variant="quiet" onClick={() => { setSwitchPrompt(false); continueWithWorkspace(); }}>{t("workspace.switch.keep")}</Button>
              </div>
            </div>
          )}
          {step === "upload" && workspaceLink && <WorkspacePanel link={workspaceLink} />}
          {queueDone && queue && (
            <QueueSummary
              items={queue}
              busy={busy}
              onDownload={combinedApi ? downloadCombined : undefined}
              onRestart={() => select("upload")}
            />
          )}
          {step === "upload" && !queueDone && (
            <div className="upload-step">
              <UploadForm
                busy={busy}
                onSubmit={upload}
                {...(combinedApi && { onSubmitMany: startQueue })}
                onInspectSheets={(file) => api.listSheets(file)}
                {...(sampleApi && {
                  onListSamples: () => sampleApi.listSamples(),
                  onLoadSample: (sample) => sampleApi.downloadSample(sample),
                })}
              />
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
                  <Button variant="primary" onClick={() => setStep(formatApi ? "format" : "approve")}>
                    {t("preview.continue")}
                  </Button>
                </div>
              </div>
            ) : (
              loadingPreview
            ))}
          {step === "format" && session && formatApi && (
            <OutputFormatStep api={formatApi} onContinue={() => setStep("approve")} />
          )}
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
                {session.approved && queue && (
                  <div className="actions">
                    {queue.some((item) => item.status === "pending") ? (
                      <Button variant="primary" disabled={busy} onClick={() => void importFrom(queue, queueIndex + 1)}>
                        {t("queue.next", { next: queue.findIndex((item, position) => position > queueIndex && item.status === "pending") + 1, total: queue.length })}
                      </Button>
                    ) : (
                      <Button variant="primary" onClick={() => importFrom(queue, queue.length)}>{t("queue.summaryButton")}</Button>
                    )}
                  </div>
                )}
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
