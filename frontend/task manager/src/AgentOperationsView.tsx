import { useCallback, useEffect, useState } from "react";
import type { TaskmanApi } from "./api";
import type { AgentEvent, AgentRun, AgentRunner, AgentRunStatus } from "./types";

const statusLabel: Record<AgentRunStatus, string> = {
  queued: "В очереди", planning: "Планирование", running: "Идёт работа", internal_review: "Внутренняя проверка",
  waiting_approval: "Нужно решение", waiting_owner_review: "На вашей оценке", revision: "Доработка",
  accepted: "Принято", completed: "Готово", cancelled: "Остановлено", failed: "Ошибка", blocked: "Заблокировано",
};

const roleLabel = {
  coordinator: "Координатор", researcher_developer: "Исследователь / разработчик", tester: "Тестировщик",
  visual_reviewer: "Визуальный ревьюер", deploy: "Деплой-агент",
};

const eventIcon: Record<string, string> = {
  role: "👤", plan: "🗺", analysis: "🔎", action: "⚙", action_complete: "✓", mcp: "🔗", mcp_complete: "✓", report: "✦",
};

function eventRole(event: AgentEvent) {
  const role = event.payload.role;
  return typeof role === "string" && role in roleLabel ? roleLabel[role as keyof typeof roleLabel] : "Система";
}

export default function AgentOperationsView({ api }: { api: TaskmanApi }) {
  const [runs, setRuns] = useState<AgentRun[]>([]);
  const [runners, setRunners] = useState<AgentRunner[]>([]);
  const [selected, setSelected] = useState<AgentRun | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [feedback, setFeedback] = useState("");

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const [next, nextRunners] = await Promise.all([api.listAgentRuns(), api.listAgentRunners()]);
      setRuns(next);
      setRunners(nextRunners);
      setSelected((current) => current ? next.find((run) => run.id === current.id) ?? null : null);
      setError("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Не удалось загрузить запуски");
    } finally {
      if (!silent) setLoading(false);
    }
  }, [api]);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    if (!runs.some((run) => ["queued", "planning", "running", "internal_review", "revision"].includes(run.status))) return;
    const timer = window.setInterval(() => void load(true), 4_000);
    return () => window.clearInterval(timer);
  }, [load, runs]);

  async function update(action: () => Promise<AgentRun>) {
    try {
      const updated = await action();
      setRuns((current) => current.map((run) => run.id === updated.id ? updated : run));
      setSelected(updated);
      setError("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Не удалось обновить запуск");
    }
  }

  return <section className="agent-operations">
    <div className="section-heading"><div><p className="eyebrow">АВТОНОМНАЯ КОМАНДА</p><h2>Работа агентов</h2></div><button className="text-button" type="button" onClick={() => void load()}>Обновить</button></div>
    {error && <div className="error-message">{error}</div>}
    {!loading && <div className="agent-runner-strip">{runners.length ? runners.map((runner) => <div key={runner.id}><span className={runner.online ? "runner-online" : "runner-offline"} /> <strong>{runner.name}</strong><small>{runner.online ? "online" : "offline"} · {runner.max_concurrency} запуск</small>{runner.last_error && <em>Последняя ошибка: {runner.last_error}</em>}</div>) : <p>Локальный runner ещё не подключён.</p>}</div>}
    {loading ? <div className="loading-line">Загружаем запуски…</div> : runs.length === 0 ? <div className="empty-state"><span>🤖</span><h3>Запусков пока нет</h3><p>Откройте задачу и нажмите «Поручить Codex».</p></div> : <div className="agent-run-list">
      {runs.map((run) => <button className={`agent-run-card ${selected?.id === run.id ? "selected" : ""}`} type="button" key={run.id} onClick={() => setSelected(run)}>
        <span className={`agent-status agent-status-${run.status}`}>{statusLabel[run.status]}</span><strong>{run.goal}</strong><small>{roleLabel[run.role]} · {new Date(run.created_at).toLocaleString("ru-RU")}</small>
      </button>)}
    </div>}
    {selected && <article className="agent-run-detail">
      <div className="section-heading"><div><p className="eyebrow">{statusLabel[selected.status]}</p><h3>{selected.goal}</h3></div><button className="icon-button light" type="button" onClick={() => setSelected(null)}>×</button></div>
      <p className="agent-current-role">Сейчас: <strong>{roleLabel[selected.role]}</strong></p>
      {selected.result_summary && <div className="agent-result"><strong>Результат</strong><p>{selected.result_summary}</p>{selected.preview_url && <a href={selected.preview_url} target="_blank" rel="noreferrer">Открыть preview</a>}</div>}
      {selected.error_message && <div className="error-message">{selected.error_message}</div>}
      {selected.approvals.filter((approval) => approval.status === "pending").map((approval) => <div className="agent-approval" key={approval.id}><strong>Нужно решение: {approval.action}</strong><p>{approval.explanation}</p><div><button className="secondary-button" type="button" onClick={() => void update(() => api.decideAgentApproval(selected.id, approval.id, "rejected"))}>Отклонить</button><button className="primary-button compact" type="button" onClick={() => void update(() => api.decideAgentApproval(selected.id, approval.id, "approved"))}>Разрешить</button></div></div>)}
      {selected.status === "waiting_owner_review" && <div className="agent-owner-actions"><textarea aria-label="Замечание владельца" value={feedback} onChange={(event) => setFeedback(event.currentTarget.value)} placeholder="Опишите, что переделать — без технического ТЗ" rows={3} /><div><button className="secondary-button" type="button" disabled={!feedback.trim()} onClick={() => void update(async () => { const result = await api.feedbackAgentRun(selected.id, feedback, []); setFeedback(""); return result; })}>Переделать</button><button className="primary-button compact" type="button" onClick={() => void update(() => api.acceptAgentRun(selected.id))}>Принять</button></div></div>}
      {["queued", "planning", "running", "internal_review", "revision"].includes(selected.status) && <button className="danger-button" type="button" onClick={() => void update(() => api.cancelAgentRun(selected.id))}>Остановить</button>}
      <section className="agent-trace"><div><p className="eyebrow">ПРОЗРАЧНЫЙ СЛЕД РАБОТЫ</p><h4>Что делают агенты</h4><span>Обновляется автоматически, пока идёт работа.</span></div><ol>{selected.events.map((event) => <li key={event.id} className={`agent-trace-${String(event.payload.kind || "system")}`}><div className="agent-trace-meta"><span>{eventIcon[String(event.payload.kind || "")] || "•"}</span><strong>{eventRole(event)}</strong><time>{new Date(event.created_at).toLocaleTimeString("ru-RU")}</time></div><p>{event.summary || event.event_type}</p>{typeof event.payload.text === "string" && <blockquote>{event.payload.text}</blockquote>}</li>)}</ol></section>
    </article>}
  </section>;
}
