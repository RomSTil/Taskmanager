import { useCallback, useEffect, useMemo, useState, type FormEvent, type MouseEvent, type PointerEvent } from "react";
import {
  DndContext,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ApiError, clearSession, getSavedApiUrl, getSession, TaskmanApi } from "./api";
import type {
  Dashboard,
  KnowledgeGraph,
  KnowledgeGraphNode,
  Note,
  NoteIndex,
  NoteShare,
  PublicNote,
  Project,
  Task,
  TaskStatus,
  WorkspaceBootstrap,
} from "./types";
import "./App.css";

type Phase = "checking" | "auth" | "workspace";
type ActiveView = "overview" | "tasks" | "notes" | "graph" | `project:${string}`;

const ACTIVE_VIEW_KEY = "taskman.active-view";

function readActiveView(): ActiveView {
  try {
    const saved = localStorage.getItem(ACTIVE_VIEW_KEY);
    if (saved === "overview" || saved === "tasks" || saved === "notes" || saved === "graph" || saved?.startsWith("project:")) {
      return saved as ActiveView;
    }
  } catch {
    // The app still works in browsers where storage is disabled.
  }
  return "overview";
}
type TaskFilter = TaskStatus | "overdue" | null;

const OVERVIEW_ORDER_KEY = "taskman.overviewTaskOrder";
const DEFAULT_DEADLINE_START = "2026-10-20";
const DEFAULT_DEADLINE_END = "2026-10-31";

const statusLabels: Record<TaskStatus, string> = {
  inbox: "Входящие",
  todo: "К выполнению",
  in_progress: "В работе",
  blocked: "Заблокировано",
  done: "Готово",
};

const dashboardCards: Array<{ key: keyof Dashboard; label: string; filter: TaskFilter }> = [
  { key: "inbox", label: "Входящие", filter: "inbox" },
  { key: "todo", label: "К выполнению", filter: "todo" },
  { key: "in_progress", label: "В работе", filter: "in_progress" },
  { key: "overdue", label: "Просрочено", filter: "overdue" },
];

const priorityColumns = [
  { value: 0, label: "Низкий", tone: "low" },
  { value: 1, label: "Обычный", tone: "normal" },
  { value: 2, label: "Высокий", tone: "high" },
  { value: 3, label: "Срочный", tone: "urgent" },
] as const;

function readOverviewOrder(): string[] {
  try {
    const value = JSON.parse(localStorage.getItem(OVERVIEW_ORDER_KEY) ?? "[]");
    return Array.isArray(value) && value.every((item) => typeof item === "string") ? value : [];
  } catch {
    return [];
  }
}

function projectForTask(task: Task, projects: Project[]): Project | undefined {
  return projects.find((project) => project.id === task.project_id);
}

function formatDueDate(value: string | null): string {
  if (!value) return "—";
  return new Intl.DateTimeFormat("ru-RU", { day: "2-digit", month: "short" }).format(
    new Date(value),
  );
}

function dateAtNoon(value: string): Date {
  return new Date(`${value}T12:00:00`);
}

function DeadlineRangePicker({
  start,
  end,
  onStartChange,
  onEndChange,
}: {
  start: string;
  end: string;
  onStartChange: (value: string) => void;
  onEndChange: (value: string) => void;
}) {
  const startDate = dateAtNoon(start);
  const endDate = dateAtNoon(end);
  const valid = !Number.isNaN(startDate.getTime()) && !Number.isNaN(endDate.getTime()) && endDate >= startDate;
  const dayCount = valid ? Math.round((endDate.getTime() - startDate.getTime()) / 86_400_000) + 1 : 0;
  const days = valid
    ? Array.from({ length: Math.min(dayCount, 31) }, (_, index) => {
        const date = new Date(startDate);
        date.setDate(startDate.getDate() + index);
        return date;
      })
    : [];
  const shortDate = new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "short" });
  const weekday = new Intl.DateTimeFormat("ru-RU", { weekday: "short" });

  return (
    <section className="deadline-picker" aria-label="График дедлайна">
      <div className="deadline-heading">
        <div><span className="deadline-icon">◷</span><div><strong>График дедлайна</strong><small>Период выполнения задачи</small></div></div>
        {valid && <span className="deadline-duration">{dayCount} дней</span>}
      </div>
      <div className="deadline-inputs">
        <label>Начало<input aria-label="Начало дедлайна" type="date" value={start} onChange={(event) => onStartChange(event.currentTarget.value)} required /></label>
        <span className="deadline-arrow">→</span>
        <label>Завершение<input aria-label="Конец дедлайна" type="date" value={end} min={start} onChange={(event) => onEndChange(event.currentTarget.value)} required /></label>
      </div>
      {valid ? (
        <div className="deadline-chart">
          <div className="deadline-bar"><span /></div>
          <div className="deadline-days">
            {days.map((date, index) => (
              <div className={index === 0 || index === days.length - 1 ? "edge" : ""} key={date.toISOString()}>
                <span>{date.getDate()}</span><small>{weekday.format(date).replace(".", "")}</small>
              </div>
            ))}
          </div>
          <div className="deadline-summary"><strong>{shortDate.format(startDate)}</strong><span>Рабочее окно задачи</span><strong>{shortDate.format(endDate)}</strong></div>
        </div>
      ) : (
        <div className="deadline-invalid">Дата завершения должна быть позже даты начала.</div>
      )}
    </section>
  );
}

function SortablePriorityCard({
  task,
  projects,
  onSelect,
}: {
  task: Task;
  projects: Project[];
  onSelect: (task: Task) => void;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: task.id,
  });
  const project = projectForTask(task, projects);
  const style = { transform: CSS.Transform.toString(transform), transition };

  return (
    <article ref={setNodeRef} style={style} className={`priority-task-card ${isDragging ? "dragging" : ""}`}>
      <div className="priority-card-topline">
        <span className={`status status-${task.status}`}>{statusLabels[task.status]}</span>
        <button
          className="drag-handle"
          type="button"
          aria-label={`Перетащить задачу ${task.title}`}
          {...attributes}
          {...listeners}
        >
          ⠿
        </button>
      </div>
      <button className="priority-card-title" type="button" onClick={() => onSelect(task)} onContextMenu={(event) => { event.preventDefault(); onSelect(task); }}>
        {task.title}
      </button>
      <div className="priority-card-project">
        <span className="project-dot" style={{ background: project?.color ?? "#aaa59a" }} />
        <span>{project?.name ?? "Без проекта"}</span>
        <small>{task.identifier}</small>
      </div>
      <div className="priority-card-footer">
        <span>{String(task.source_data.assignee_username ?? "Не назначен")}</span>
        <strong className={task.due_at && Date.parse(task.due_at) < Date.now() && task.status !== "done" ? "overdue-date" : ""}>
          {task.due_at ? `до ${formatDueDate(task.due_at)}` : "без срока"}
        </strong>
      </div>
    </article>
  );
}

function PriorityColumn({
  priority,
  tasks,
  projects,
  onSelect,
}: {
  priority: (typeof priorityColumns)[number];
  tasks: Task[];
  projects: Project[];
  onSelect: (task: Task) => void;
}) {
  const containerId = `priority-${priority.value}`;
  const { setNodeRef, isOver } = useDroppable({ id: containerId });

  return (
    <section className={`priority-column priority-${priority.tone} ${isOver ? "drop-target" : ""}`}>
      <header><div><span className="priority-column-dot" /><strong>{priority.label}</strong></div><span>{tasks.length}</span></header>
      <div className="priority-column-body" ref={setNodeRef}>
        <SortableContext items={tasks.map((task) => task.id)} strategy={verticalListSortingStrategy}>
          {tasks.map((task) => <SortablePriorityCard task={task} projects={projects} onSelect={onSelect} key={task.id} />)}
        </SortableContext>
        {tasks.length === 0 && <div className="priority-empty">Перетащите задачу сюда</div>}
      </div>
    </section>
  );
}

function PriorityBoard({
  tasks,
  projects,
  onSelect,
  onDrop,
}: {
  tasks: Task[];
  projects: Project[];
  onSelect: (task: Task) => void;
  onDrop: (activeId: string, overId: string) => void;
}) {
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  function finishDrag(event: DragEndEvent) {
    if (event.over && event.active.id !== event.over.id) {
      onDrop(String(event.active.id), String(event.over.id));
    }
  }

  return (
    <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={finishDrag}>
      <div className="priority-board">
        {priorityColumns.map((priority) => (
          <PriorityColumn
            priority={priority}
            tasks={tasks.filter((task) => task.priority === priority.value)}
            projects={projects}
            onSelect={onSelect}
            key={priority.value}
          />
        ))}
      </div>
    </DndContext>
  );
}

function taskStart(task: Task): Date {
  const stored = task.source_data.deadline_start;
  const date = new Date(typeof stored === "string" ? stored : task.created_at);
  date.setHours(12, 0, 0, 0);
  return date;
}

function taskEnd(task: Task): Date {
  const date = task.due_at ? new Date(task.due_at) : new Date(taskStart(task).getTime());
  date.setHours(12, 0, 0, 0);
  return date;
}

function TimelineView({ tasks, projects, onSelect }: { tasks: Task[]; projects: Project[]; onSelect: (task: Task) => void }) {
  if (tasks.length === 0) {
    return <div className="empty-state compact-empty"><span>◫</span><h3>Нет задач для графика</h3><p>Добавьте задачу с диапазоном дедлайна.</p></div>;
  }

  const start = new Date(Math.min(...tasks.map((task) => taskStart(task).getTime())));
  const end = new Date(Math.max(...tasks.map((task) => taskEnd(task).getTime())));
  const totalDays = Math.min(730, Math.max(1, Math.round((end.getTime() - start.getTime()) / 86_400_000) + 1));
  const days = Array.from({ length: totalDays }, (_, index) => {
    const day = new Date(start);
    day.setDate(start.getDate() + index);
    return day;
  });
  const months: Array<{ label: string; count: number }> = [];
  const monthFormat = new Intl.DateTimeFormat("ru-RU", { month: "long", year: "numeric" });
  for (const day of days) {
    const label = monthFormat.format(day);
    const current = months[months.length - 1];
    if (current?.label === label) current.count += 1;
    else months.push({ label, count: 1 });
  }
  const weekdayFormat = new Intl.DateTimeFormat("ru-RU", { weekday: "short" });
  const dayWidth = 52;
  const sortedTasks = [...tasks].sort((first, second) => taskStart(first).getTime() - taskStart(second).getTime());

  return (
    <div className="timeline-shell">
      <div className="timeline-scroll">
        <table className="timeline-table" style={{ minWidth: `${260 + days.length * dayWidth}px` }}>
          <colgroup><col style={{ width: "260px" }} />{days.map((day) => <col style={{ width: `${dayWidth}px` }} key={day.toISOString()} />)}</colgroup>
          <thead>
            <tr><th className="timeline-sticky" rowSpan={2}>Задача</th>{months.map((month) => <th className="timeline-month" colSpan={month.count} key={month.label}>{month.label}</th>)}</tr>
            <tr>{days.map((day) => { const weekend = day.getDay() === 0 || day.getDay() === 6; return <th className={weekend ? "timeline-day weekend" : "timeline-day"} key={day.toISOString()}><strong>{day.getDate()}</strong><span>{weekdayFormat.format(day).replace(".", "")}</span></th>; })}</tr>
          </thead>
          <tbody>
            {sortedTasks.map((task) => {
              const rangeStart = Math.max(0, Math.round((taskStart(task).getTime() - start.getTime()) / 86_400_000));
              const rangeEnd = Math.max(rangeStart, Math.round((taskEnd(task).getTime() - start.getTime()) / 86_400_000));
              const project = projectForTask(task, projects);
              return (
                <tr key={task.id}>
                  <th className="timeline-sticky"><button type="button" onClick={() => onSelect(task)}><strong>{task.title}</strong><span><i style={{ background: project?.color ?? "#aaa59a" }} />{project?.name ?? "Без проекта"}</span></button></th>
                  <td className="timeline-track-cell" colSpan={days.length}>
                    <div className="timeline-row-grid" style={{ width: `${days.length * dayWidth}px`, backgroundSize: `${dayWidth}px 100%` }}>
                      <button className={`timeline-task-bar timeline-priority-${task.priority}`} type="button" style={{ left: `${rangeStart * dayWidth + 5}px`, width: `${Math.max(dayWidth - 10, (rangeEnd - rangeStart + 1) * dayWidth - 10)}px` }} onClick={() => onSelect(task)} title={`${task.title}: ${formatDueDate(taskStart(task).toISOString())} — ${formatDueDate(task.due_at)}`}><span>{task.title}</span></button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="timeline-legend"><span>← Горизонтальная шкала: {formatDueDate(start.toISOString())} — {formatDueDate(end.toISOString())} →</span><small>Прокручивайте таблицу по горизонтали</small></div>
    </div>
  );
}

function TaskList({
  tasks,
  onSelect,
  emptyText = "В этом разделе пока нет задач.",
}: {
  tasks: Task[];
  onSelect: (task: Task) => void;
  emptyText?: string;
}) {
  if (tasks.length === 0) {
    return (
      <div className="empty-state">
        <span>✓</span>
        <h3>Здесь пока спокойно</h3>
        <p>{emptyText}</p>
      </div>
    );
  }

  return (
    <div className="task-list">
      {tasks.map((task) => (
        <button className="task-row" type="button" key={task.id} onClick={() => onSelect(task)} onContextMenu={(event) => { event.preventDefault(); onSelect(task); }}>
          <span className={`priority priority-${task.priority}`} />
          <span className="task-main">
            <strong>{task.title}</strong>
            <span>{task.identifier}</span>
          </span>
          <span className={`status status-${task.status}`}>{statusLabels[task.status]}</span>
        </button>
      ))}
    </div>
  );
}

function workspaceIds(projectId: string, projects: Project[]): Set<string> {
  const result = new Set([projectId]);
  let changed = true;
  while (changed) {
    changed = false;
    for (const project of projects) {
      if (project.parent_id && result.has(project.parent_id) && !result.has(project.id)) {
        result.add(project.id);
        changed = true;
      }
    }
  }
  return result;
}

function noteBody(markdown: string): string {
  return markdown.replace(/^---\s*\r?\n[\s\S]*?\r?\n---\s*\r?\n?/, "");
}

function MarkdownContent({ markdown }: { markdown: string }) {
  return <ReactMarkdown remarkPlugins={[remarkGfm]} components={{ a: ({ href, children }) => <a href={href} target="_blank" rel="noreferrer">{children}</a> }}>{noteBody(markdown)}</ReactMarkdown>;
}

function KnowledgeGraphView({
  graph,
  onSelect,
}: {
  graph: KnowledgeGraph;
  onSelect: (node: KnowledgeGraphNode) => void;
}) {
  const [positions, setPositions] = useState<Record<string, { x: number; y: number }>>({});
  const [dragging, setDragging] = useState<string | null>(null);
  const nodeById = new Map(graph.nodes.map((node) => [node.id, node]));
  const positionFor = (node: KnowledgeGraphNode, index: number) => positions[node.id] ?? {
    x: 500 + 330 * Math.cos((index / Math.max(graph.nodes.length, 1)) * Math.PI * 2 - Math.PI / 2),
    y: 325 + 220 * Math.sin((index / Math.max(graph.nodes.length, 1)) * Math.PI * 2 - Math.PI / 2),
  };
  const moveNode = (event: PointerEvent<SVGCircleElement>) => {
    if (!dragging) return;
    const bounds = event.currentTarget.ownerSVGElement?.getBoundingClientRect();
    if (!bounds) return;
    setPositions((current) => ({
      ...current,
      [dragging]: {
        x: Math.max(45, Math.min(955, ((event.clientX - bounds.left) / bounds.width) * 1000)),
        y: Math.max(45, Math.min(605, ((event.clientY - bounds.top) / bounds.height) * 650)),
      },
    }));
  };

  if (!graph.nodes.length) {
    return <div className="empty-state"><span>◌</span><h3>Карта пока пустая</h3><p>Создай задачу и прикрепи к ней заметку — они появятся здесь.</p></div>;
  }

  return (
      <div className="knowledge-graph-shell">
      <div className="graph-hint">Задачи, решения и материалы в одном рабочем пространстве</div>
      <svg className="knowledge-graph" viewBox="0 0 1000 650" role="img" aria-label="Карта задач и заметок">
        <defs>
          <pattern id="graph-grid" width="36" height="36" patternUnits="userSpaceOnUse"><path d="M 36 0 L 0 0 0 36" fill="none" stroke="rgba(255,255,255,.08)" /></pattern>
        </defs>
        <rect width="1000" height="650" fill="url(#graph-grid)" />
        {graph.edges.map((edge, index) => {
          const source = nodeById.get(edge.source);
          const target = nodeById.get(edge.target);
          if (!source || !target) return null;
          const sourcePosition = positionFor(source, graph.nodes.indexOf(source));
          const targetPosition = positionFor(target, graph.nodes.indexOf(target));
          return <line key={`${edge.source}-${edge.target}-${index}`} className={`graph-edge ${edge.kind}`} x1={sourcePosition.x} y1={sourcePosition.y} x2={targetPosition.x} y2={targetPosition.y} />;
        })}
        {graph.nodes.map((node, index) => {
          const position = positionFor(node, index);
          const isTask = node.kind === "task";
          const tagLabel = node.tags.length ? `#${node.tags[0]}${node.tags.length > 1 ? ` +${node.tags.length - 1}` : ""}` : "";
          return (
            <g className="graph-node" key={node.id} transform={`translate(${position.x} ${position.y})`}>
              <circle className={isTask ? `graph-orb task priority-${node.priority ?? 1}` : "graph-orb note"} r={isTask ? 28 : 24} onPointerDown={(event) => { event.currentTarget.setPointerCapture(event.pointerId); setDragging(node.id); }} onPointerMove={moveNode} onPointerUp={(event) => { event.currentTarget.releasePointerCapture(event.pointerId); setDragging(null); }} onClick={() => { if (!dragging) onSelect(node); }} />
              <text className="graph-node-kind" textAnchor="middle" dy="4">{isTask ? "✓" : "◇"}</text>
              <text className="graph-node-title" textAnchor="middle" y={isTask ? 48 : 44}>{node.title.length > 22 ? `${node.title.slice(0, 21)}…` : node.title}</text>
              {tagLabel && <text className="graph-node-tag" textAnchor="middle" y={isTask ? 64 : 60}>{tagLabel}</text>}
            </g>
          );
        })}
      </svg>
    </div>
  );
}

function PublicNotePage({ token }: { token: string }) {
  const [note, setNote] = useState<PublicNote | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const api = new TaskmanApi(getSavedApiUrl());
    void api.publicNote(token).then(setNote).catch(() => setError("Эта ссылка недействительна или заметка больше не доступна."));
  }, [token]);

  return <main className="public-note-page">{error ? <section className="public-note-card"><p className="eyebrow">TASKMAN</p><h1>Заметка недоступна</h1><p>{error}</p></section> : !note ? <div className="loading-line">Открываем заметку…</div> : <article className="public-note-card"><header><p className="eyebrow">ОТКРЫТАЯ ЗАМЕТКА</p><h1>{note.title}</h1><span>{note.path}</span></header><div className="markdown-document"><MarkdownContent markdown={note.content_markdown} /></div><footer>Открыто через Taskman</footer></article>}</main>;
}

function WorkspaceApp() {
  const [phase, setPhase] = useState<Phase>("checking");
  const [apiUrl, setApiUrl] = useState(getSavedApiUrl);
  const [setupRequired, setSetupRequired] = useState(false);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [setupToken, setSetupToken] = useState("");
  const [workspace, setWorkspace] = useState<WorkspaceBootstrap | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [activeView, setActiveView] = useState<ActiveView>(readActiveView);
  const [taskFilter, setTaskFilter] = useState<TaskFilter>(null);
  const [notes, setNotes] = useState<NoteIndex[]>([]);
  const [notesLoaded, setNotesLoaded] = useState(false);
  const [notesLoading, setNotesLoading] = useState(false);
  const [graph, setGraph] = useState<KnowledgeGraph | null>(null);
  const [graphLoading, setGraphLoading] = useState(false);
  const [graphNode, setGraphNode] = useState<KnowledgeGraphNode | null>(null);
  const [graphNote, setGraphNote] = useState<Note | null>(null);
  const [graphDrawerWidth, setGraphDrawerWidth] = useState(520);
  const [resizingGraphDrawer, setResizingGraphDrawer] = useState(false);
  const [linkedNotes, setLinkedNotes] = useState<NoteIndex[]>([]);
  const [noteCreateOpen, setNoteCreateOpen] = useState(false);
  const [newNoteTitle, setNewNoteTitle] = useState("");
  const [newNoteContent, setNewNoteContent] = useState("");
  const [noteEditorOpen, setNoteEditorOpen] = useState(false);
  const [editingNote, setEditingNote] = useState<Note | null>(null);
  const [editorTitle, setEditorTitle] = useState("");
  const [editorContent, setEditorContent] = useState("");
  const [editorTags, setEditorTags] = useState("");
  const [editorError, setEditorError] = useState("");
  const [workspaceCreateOpen, setWorkspaceCreateOpen] = useState(false);
  const [workspaceName, setWorkspaceName] = useState("");
  const [workspaceParent, setWorkspaceParent] = useState("");
  const [workspaceError, setWorkspaceError] = useState("");
  const [workspaceMenu, setWorkspaceMenu] = useState<{ project: Project; x: number; y: number } | null>(null);
  const [pageError, setPageError] = useState("");
  const [selectedTask, setSelectedTask] = useState<Task | null>(null);
  const [taskEditorTitle, setTaskEditorTitle] = useState("");
  const [taskEditorDescription, setTaskEditorDescription] = useState("");
  const [taskEditorStatus, setTaskEditorStatus] = useState<TaskStatus>("inbox");
  const [taskEditorPriority, setTaskEditorPriority] = useState(1);
  const [taskEditorProject, setTaskEditorProject] = useState("");
  const [selectedNote, setSelectedNote] = useState<Note | null>(null);
  const [shareMessage, setShareMessage] = useState("");
  const [shareUrl, setShareUrl] = useState("");
  const [shareDialogNote, setShareDialogNote] = useState<Note | null>(null);
  const [shareInfo, setShareInfo] = useState<NoteShare | null>(null);
  const [shareDuration, setShareDuration] = useState("7");
  const [detailError, setDetailError] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [newTaskTitle, setNewTaskTitle] = useState("");
  const [newTaskStart, setNewTaskStart] = useState(DEFAULT_DEADLINE_START);
  const [newTaskEnd, setNewTaskEnd] = useState(DEFAULT_DEADLINE_END);
  const [newTaskAssignee, setNewTaskAssignee] = useState("");
  const [taskError, setTaskError] = useState("");
  const [overviewMode, setOverviewMode] = useState<"priority" | "timeline">("priority");
  const [overviewProjectFilter, setOverviewProjectFilter] = useState("all");
  const [overviewOrder, setOverviewOrder] = useState<string[]>(readOverviewOrder);

  const api = useMemo(() => new TaskmanApi(apiUrl), [apiUrl]);
  void selectGraphNode;

  const connect = useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      api.saveUrl();
      const setup = await api.setupState();
      setSetupRequired(setup.setup_required);
      if (!setup.setup_required && getSession()) {
        try {
          setWorkspace(await api.bootstrap());
          setPhase("workspace");
          return;
        } catch (reason) {
          if (reason instanceof ApiError && reason.status === 401) clearSession();
          else throw reason;
        }
      }
      setPhase("auth");
    } catch (reason) {
      setPhase("auth");
      setError(reason instanceof Error ? reason.message : "Не удалось подключиться к серверу");
    } finally {
      setBusy(false);
    }
  }, [api]);

  useEffect(() => {
    void connect();
  }, [connect]);

  useEffect(() => {
    try {
      localStorage.setItem(ACTIVE_VIEW_KEY, activeView);
    } catch {
      // Keeping the current section is optional when browser storage is disabled.
    }
  }, [activeView]);

  useEffect(() => {
    if (phase !== "workspace") return;
    if (activeView === "notes") void loadNotes();
    if (activeView === "graph") void showGraph();
  }, [phase]);

  useEffect(() => {
    if (workspace && activeView.startsWith("project:") && !workspace.projects.some((project) => project.id === activeView.slice("project:".length))) {
      setActiveView("overview");
    }
  }, [activeView, workspace]);

  useEffect(() => {
    if (graphNode?.kind !== "note") {
      setGraphNote(null);
      return;
    }
    void api.getNote(graphNode.id).then(setGraphNote).catch(() => setGraphNote(null));
  }, [api, graphNode]);

  useEffect(() => {
    if (!workspace) return;
    setOverviewOrder((current) => {
      const taskIds = new Set(workspace.tasks.map((task) => task.id));
      const next = [
        ...current.filter((id) => taskIds.has(id)),
        ...workspace.tasks.map((task) => task.id).filter((id) => !current.includes(id)),
      ];
      if (next.length === current.length && next.every((id, index) => id === current[index])) {
        return current;
      }
      localStorage.setItem(OVERVIEW_ORDER_KEY, JSON.stringify(next));
      return next;
    });
  }, [workspace]);

  async function refreshWorkspace() {
    const next = await api.bootstrap();
    setWorkspace(next);
    return next;
  }

  async function submitAuth(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      if (setupRequired) await api.setup(username, password, setupToken || undefined);
      else await api.login(username, password);
      await refreshWorkspace();
      setPassword("");
      setPhase("workspace");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Не удалось войти");
    } finally {
      setBusy(false);
    }
  }

  function logout() {
    clearSession();
    setWorkspace(null);
    setSelectedTask(null);
    setSelectedNote(null);
    setPassword("");
    setPhase("auth");
  }

  async function loadNotes(force = false) {
    if (notesLoaded && !force) return;
    setNotesLoading(true);
    setPageError("");
    try {
      setNotes(await api.listNotes());
      setNotesLoaded(true);
    } catch (reason) {
      setPageError(reason instanceof Error ? reason.message : "Не удалось загрузить заметки");
    } finally {
      setNotesLoading(false);
    }
  }

  function showOverview() {
    setActiveView("overview");
    setTaskFilter(null);
  }

  function showTasks(filter: TaskFilter = null) {
    setActiveView("tasks");
    setTaskFilter(filter);
  }

  function showProject(project: Project) {
    setActiveView(`project:${project.id}`);
    setTaskFilter(null);
  }

  function showNotes() {
    setActiveView("notes");
    setTaskFilter(null);
    void loadNotes();
  }

  function openWorkspaceCreator(parentId?: string) {
    setWorkspaceName("");
    setWorkspaceParent(parentId ?? "");
    setWorkspaceError("");
    setWorkspaceCreateOpen(true);
  }

  function openWorkspaceMenu(event: MouseEvent<HTMLButtonElement>, project: Project) {
    event.preventDefault();
    setWorkspaceMenu({ project, x: event.clientX, y: event.clientY });
  }

  async function archiveWorkspace(project: Project) {
    setBusy(true);
    setWorkspaceMenu(null);
    try {
      await api.archiveProject(project);
      if (activeProject?.id === project.id) showTasks();
      await refreshWorkspace();
    } catch (reason) {
      setPageError(reason instanceof Error ? reason.message : "Не удалось удалить пространство");
    } finally {
      setBusy(false);
    }
  }

  async function submitWorkspace(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setWorkspaceError("");
    try {
      const created = await api.createProject({
        name: workspaceName.trim(),
        parent_id: workspaceParent || null,
      });
      await refreshWorkspace();
      setWorkspaceCreateOpen(false);
      showProject(created);
    } catch (reason) {
      setWorkspaceError(reason instanceof Error ? reason.message : "Не удалось создать рабочее пространство");
    } finally {
      setBusy(false);
    }
  }

  async function showGraph() {
    setActiveView("graph");
    setTaskFilter(null);
    setGraphLoading(true);
    setPageError("");
    try {
      setGraph(await api.knowledgeGraph());
    } catch (reason) {
      setPageError(reason instanceof Error ? reason.message : "Не удалось загрузить карту связей");
    } finally {
      setGraphLoading(false);
    }
  }

  async function selectGraphNode(node: KnowledgeGraphNode) {
    setGraphNode(node);
    setGraphNote(null);
    if (node.kind === "note") {
      try {
        setGraphNote(await api.getNote(node.id));
      } catch (reason) {
        setPageError(reason instanceof Error ? reason.message : "Не удалось открыть заметку");
      }
    }
  }

  async function openNote(note: NoteIndex) {
    setBusy(true);
    setDetailError("");
    try {
      setSelectedNote(await api.getNote(note.id));
    } catch (reason) {
      setPageError(reason instanceof Error ? reason.message : "Не удалось открыть заметку");
    } finally {
      setBusy(false);
    }
  }

  async function createPublicLink(note: Note, expiresAt: string | null) {
    const viewer = window.open("about:blank", "_blank");
    if (viewer) viewer.opener = null;
    setShareMessage("");
    setShareUrl("");
    try {
      const share = await api.createNoteShare(note.id, expiresAt);
      const { token } = share;
      const link = `${window.location.origin}/public/notes/${encodeURIComponent(token)}`;
      if (viewer) viewer.location.href = link;
      setShareUrl(link);
      setShareMessage("Публичная ссылка готова.");
      setShareInfo(share);
      return share;
    } catch (reason) {
      viewer?.close();
      setShareMessage(reason instanceof Error ? reason.message : "Не удалось создать ссылку.");
      return null;
    }
  }

  async function openShareDialog(note: Note) {
    setShareDialogNote(note);
    setShareInfo(null);
    setShareDuration("7");
    setShareMessage("");
    setShareUrl("");
    try {
      const existing = await api.getNoteShare(note.id);
      setShareInfo(existing);
      if (existing) setShareUrl(`${window.location.origin}/public/notes/${encodeURIComponent(existing.token)}`);
    } catch (reason) {
      setShareMessage(reason instanceof Error ? reason.message : "Не удалось загрузить ссылку.");
    }
  }

  async function createShareFromDialog() {
    if (!shareDialogNote) return;
    const days = Number(shareDuration);
    const expiresAt = days ? new Date(Date.now() + days * 86_400_000).toISOString() : null;
    await createPublicLink(shareDialogNote, expiresAt);
  }

  async function revokeShareFromDialog() {
    if (!shareDialogNote) return;
    try {
      await api.revokeNoteShare(shareDialogNote.id);
      setShareInfo(null);
      setShareUrl("");
      setShareMessage("Публичная ссылка отозвана.");
    } catch (reason) {
      setShareMessage(reason instanceof Error ? reason.message : "Не удалось отозвать ссылку.");
    }
  }

  function openNoteEditor(note?: Note) {
    setEditingNote(note ?? null);
    setEditorTitle(note?.title ?? "");
    setEditorContent(note?.content_markdown ?? "");
    setEditorTags(note?.tags.join(", ") ?? "");
    setEditorError("");
    setNoteEditorOpen(true);
  }

  async function saveNoteEditor(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const title = editorTitle.trim();
    if (!title) return;
    setBusy(true);
    setEditorError("");
    const tags = editorTags.split(",").map((tag) => tag.trim()).filter(Boolean);
    try {
      const saved = editingNote
        ? await api.updateNote(editingNote, { title, content_markdown: editorContent, tags })
        : await api.createNote({ title, content_markdown: editorContent, tags });
      setNotes((current) => editingNote ? current.map((note) => note.id === saved.id ? saved : note) : [saved, ...current]);
      setNotesLoaded(true);
      if (selectedNote?.id === saved.id) setSelectedNote(saved);
      setNoteEditorOpen(false);
      if (activeView === "graph") setGraph(await api.knowledgeGraph());
    } catch (reason) {
      setEditorError(reason instanceof Error ? reason.message : "Не удалось сохранить заметку");
    } finally {
      setBusy(false);
    }
  }

  async function openTask(task: Task) {
    setSelectedTask(task);
    setTaskEditorTitle(task.title);
    setTaskEditorDescription(task.description_markdown);
    setTaskEditorStatus(task.status);
    setTaskEditorPriority(task.priority);
    setTaskEditorProject(task.project_id ?? "");
    setLinkedNotes([]);
    try {
      setLinkedNotes(await api.listTaskNotes(task.id));
    } catch (reason) {
      setDetailError(reason instanceof Error ? reason.message : "Не удалось загрузить заметки задачи");
    }
  }

  async function saveTaskEditor(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedTask) return;
    setBusy(true);
    setDetailError("");
    try {
      const updated = await api.updateTask(selectedTask, {
        title: taskEditorTitle.trim(),
        description_markdown: taskEditorDescription,
        status: taskEditorStatus,
        priority: taskEditorPriority,
        project_id: taskEditorProject || null,
      });
      setSelectedTask(updated);
      await refreshWorkspace();
    } catch (reason) {
      setDetailError(reason instanceof Error ? reason.message : "Не удалось сохранить задачу");
    } finally {
      setBusy(false);
    }
  }

  async function archiveTaskFromEditor() {
    if (!selectedTask) return;
    setBusy(true);
    setDetailError("");
    try {
      await api.updateTask(selectedTask, { archived: true });
      setSelectedTask(null);
      await refreshWorkspace();
    } catch (reason) {
      setDetailError(reason instanceof Error ? reason.message : "Не удалось архивировать задачу");
    } finally {
      setBusy(false);
    }
  }

  function openNewLinkedNote() {
    setNewNoteTitle("");
    setNewNoteContent("");
    setNoteCreateOpen(true);
  }

  async function submitNewLinkedNote(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedTask) return;
    setBusy(true);
    setDetailError("");
    try {
      const note = await api.createNote({
        title: newNoteTitle.trim(),
        content_markdown: newNoteContent,
        project_id: selectedTask.project_id,
      });
      await api.linkTaskNote(selectedTask.id, note.id);
      setLinkedNotes((current) => [note, ...current]);
      setNotesLoaded(false);
      setNoteCreateOpen(false);
      if (activeView === "graph") setGraph(await api.knowledgeGraph());
    } catch (reason) {
      setDetailError(reason instanceof Error ? reason.message : "Не удалось создать заметку");
    } finally {
      setBusy(false);
    }
  }

  async function changeTaskStatus(status: TaskStatus) {
    if (!selectedTask || selectedTask.status === status) return;
    setBusy(true);
    setDetailError("");
    try {
      const updated = await api.updateTask(selectedTask, { status });
      setSelectedTask(updated);
      await refreshWorkspace();
    } catch (reason) {
      setDetailError(reason instanceof Error ? reason.message : "Не удалось обновить задачу");
    } finally {
      setBusy(false);
    }
  }

  function openCreateTask() {
    if (!activeView.startsWith("project:") || !workspace) return;
    setNewTaskTitle("");
    setNewTaskStart(DEFAULT_DEADLINE_START);
    setNewTaskEnd(DEFAULT_DEADLINE_END);
    setNewTaskAssignee(workspace.user.id);
    setTaskError("");
    setCreateOpen(true);
  }

  async function submitNewTask(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!activeView.startsWith("project:")) {
      setTaskError("Создавать задачу нужно из вкладки конкретного проекта.");
      return;
    }
    if (dateAtNoon(newTaskEnd) < dateAtNoon(newTaskStart)) {
      setTaskError("Дата завершения должна быть позже даты начала.");
      return;
    }
    setBusy(true);
    setTaskError("");
    try {
      await api.createTask({
        title: newTaskTitle.trim(),
        project_id: activeView.slice("project:".length),
        priority: 1,
        due_at: new Date(`${newTaskEnd}T23:59:59`).toISOString(),
        source_data: {
          deadline_start: new Date(`${newTaskStart}T00:00:00`).toISOString(),
          assignee_user_id: newTaskAssignee || workspace?.user.id,
        },
      });
      await refreshWorkspace();
      setCreateOpen(false);
    } catch (reason) {
      setTaskError(reason instanceof Error ? reason.message : "Не удалось создать задачу");
    } finally {
      setBusy(false);
    }
  }

  function dropPriorityTask(activeId: string, overId: string) {
    if (!workspace) return;
    const activeTask = workspace.tasks.find((task) => task.id === activeId);
    const overTask = workspace.tasks.find((task) => task.id === overId);
    const targetPriority = overId.startsWith("priority-")
      ? Number(overId.slice("priority-".length))
      : overTask?.priority;
    if (!activeTask || targetPriority === undefined || targetPriority < 0 || targetPriority > 3) {
      return;
    }
    setOverviewOrder((current) => {
      const taskIds = workspace.tasks.map((task) => task.id);
      const normalized = [
        ...current.filter((id) => taskIds.includes(id)),
        ...taskIds.filter((id) => !current.includes(id)),
      ];
      const next = normalized.filter((id) => id !== activeId);
      let insertionIndex = overTask ? next.indexOf(overId) : -1;
      if (insertionIndex < 0) {
        const taskById = new Map(workspace.tasks.map((task) => [task.id, task]));
        const lastTargetIndex = next.reduce(
          (last, id, index) => taskById.get(id)?.priority === targetPriority ? index : last,
          -1,
        );
        insertionIndex = lastTargetIndex + 1;
      }
      next.splice(insertionIndex, 0, activeId);
      localStorage.setItem(OVERVIEW_ORDER_KEY, JSON.stringify(next));
      return next;
    });
    if (activeTask.priority !== targetPriority) {
      const previousWorkspace = workspace;
      setWorkspace({
        ...workspace,
        tasks: workspace.tasks.map((task) =>
          task.id === activeId ? { ...task, priority: targetPriority } : task,
        ),
      });
      void api
        .updateTask(activeTask, { priority: targetPriority })
        .then(() => refreshWorkspace())
        .catch((reason: unknown) => {
          setWorkspace(previousWorkspace);
          setPageError(reason instanceof Error ? reason.message : "Не удалось изменить приоритет");
        });
    }
  }

  if (phase === "checking") {
    return (
      <main className="center-screen">
        <div className="loader" />
        <p>Подключаемся к Taskman…</p>
      </main>
    );
  }

  if (phase === "auth" || !workspace) {
    return (
      <main className="auth-layout">
        <section className="brand-panel">
          <div className="brand-mark">T</div>
          <p className="eyebrow">TASKMAN</p>
          <h1>Спокойное место для задач и знаний.</h1>
          <p className="brand-copy">
            Проекты, заметки и входящие собраны в одном локальном рабочем пространстве.
          </p>
        </section>

        <section className="auth-panel">
          <form className="auth-card" onSubmit={submitAuth}>
            <div>
              <p className="eyebrow">{setupRequired ? "ПЕРВЫЙ ЗАПУСК" : "С ВОЗВРАЩЕНИЕМ"}</p>
              <h2>{setupRequired ? "Создать владельца" : "Войти в пространство"}</h2>
            </div>
            <label>
              Адрес backend
              <div className="server-field">
                <input type="url" value={apiUrl} onChange={(event) => setApiUrl(event.currentTarget.value)} required />
                <button className="secondary-button" type="button" onClick={() => void connect()}>Проверить</button>
              </div>
            </label>
            <label>
              Имя пользователя
              <input autoComplete="username" value={username} onChange={(event) => setUsername(event.currentTarget.value)} minLength={3} required />
            </label>
            <label>
              Пароль
              <input type="password" autoComplete={setupRequired ? "new-password" : "current-password"} value={password} onChange={(event) => setPassword(event.currentTarget.value)} minLength={setupRequired ? 10 : undefined} required />
            </label>
            {setupRequired && (
              <label>
                Токен установки <span className="muted">необязательно локально</span>
                <input type="password" value={setupToken} onChange={(event) => setSetupToken(event.currentTarget.value)} />
              </label>
            )}
            {error && <div className="error-message">{error}</div>}
            <button className="primary-button" type="submit" disabled={busy}>
              {busy ? "Подождите…" : setupRequired ? "Создать пространство" : "Войти"}
            </button>
          </form>
        </section>
      </main>
    );
  }

  const activeProject = activeView.startsWith("project:")
    ? workspace.projects.find((project) => project.id === activeView.slice("project:".length))
    : undefined;
  const now = Date.now();
  const activeWorkspaceIds = activeProject
    ? activeProject.parent_id ? new Set([activeProject.id]) : workspaceIds(activeProject.id, workspace.projects)
    : null;
  const filteredTasks = workspace.tasks.filter((task) => {
    if (activeWorkspaceIds && (!task.project_id || !activeWorkspaceIds.has(task.project_id))) return false;
    if (!taskFilter) return true;
    if (taskFilter === "overdue") {
      return Boolean(task.due_at && Date.parse(task.due_at) < now && task.status !== "done");
    }
    return task.status === taskFilter;
  });
  const overviewOrderIndex = new Map(overviewOrder.map((id, index) => [id, index]));
  const overviewTasks = [...workspace.tasks]
    .sort(
      (first, second) =>
        (overviewOrderIndex.get(first.id) ?? Number.MAX_SAFE_INTEGER) -
        (overviewOrderIndex.get(second.id) ?? Number.MAX_SAFE_INTEGER),
    )
    .filter(
      (task) => overviewProjectFilter === "all" || task.project_id === overviewProjectFilter,
    );
  const viewTitle = activeProject?.name ?? (activeView === "tasks" ? "Мои задачи" : activeView === "notes" ? "Заметки" : activeView === "graph" ? "Карта знаний" : `Доброе утро, ${workspace.user.username}`);
  const viewEyebrow = activeProject ? activeProject.key : activeView === "notes" ? "БАЗА ЗНАНИЙ" : activeView === "graph" ? "СВЯЗИ" : activeView === "tasks" ? "ВСЕ ЗАДАЧИ" : "РАБОЧЕЕ ПРОСТРАНСТВО";

  return (
    <main className="workspace-layout">
      <aside className="sidebar">
        <button className="sidebar-brand" type="button" onClick={showOverview}>
          <span className="brand-mark small">T</span>
          <strong>Taskman</strong>
        </button>
        <nav>
          <button className={`nav-item ${activeView === "overview" ? "active" : ""}`} type="button" onClick={showOverview}><span>⌂</span> Обзор</button>
          <button className={`nav-item ${activeView === "tasks" ? "active" : ""}`} type="button" onClick={() => showTasks()}><span>✓</span> Мои задачи</button>
          <button className={`nav-item ${activeView === "notes" ? "active" : ""}`} type="button" onClick={showNotes}><span>◇</span> Заметки</button>
          <button className={`nav-item ${activeView === "graph" ? "active" : ""}`} type="button" onClick={() => void showGraph()}><span>◌</span> Карта знаний</button>
        </nav>
        <p className="nav-title">Проекты</p>
        <nav>
          {workspace.projects.filter((project) => !project.parent_id).map((project) => (
            <div className="workspace-tree" key={project.id}>
              <div className={`workspace-root-row ${activeProject?.id === project.id ? "active" : ""}`}>
                <button className="nav-item" type="button" onClick={() => showProject(project)} onContextMenu={(event) => openWorkspaceMenu(event, project)}>
                  <span className="project-dot" style={{ background: project.color }} />
                  {project.name}
                </button>
                <button className="subspace-add-button" type="button" onClick={() => openWorkspaceCreator(project.id)} title="Создать подпространство" aria-label="Создать подпространство">+</button>
              </div>
              {workspace.projects.filter((child) => child.parent_id === project.id).map((child) => (
                <button className={`nav-item subspace ${activeProject?.id === child.id ? "active" : ""}`} type="button" key={child.id} onClick={() => showProject(child)} onContextMenu={(event) => openWorkspaceMenu(event, child)}>
                  <span className="subspace-branch">└</span><span className="project-dot" style={{ background: child.color }} />{child.name}
                </button>
              ))}
            </div>
          ))}
          <button className="new-workspace-button" type="button" onClick={() => openWorkspaceCreator()}>＋ Новое пространство</button>
        </nav>
        <div className="sidebar-footer">
          <div><strong>{workspace.user.username}</strong><span>{api.baseUrl}</span></div>
          <button className="icon-button" type="button" onClick={logout} title="Выйти">↪</button>
        </div>
      </aside>

      <section className={`workspace-content ${activeView === "graph" ? "graph-workspace" : ""}`}>
        {activeView !== "graph" && <header className="workspace-header">
          <div><p className="eyebrow">{viewEyebrow}</p><h1>{viewTitle}</h1></div>
          {activeProject && <button className="primary-button compact" type="button" onClick={openCreateTask}>＋ Новая задача</button>}
        </header>}

        {pageError && <div className="error-message page-error">{pageError}</div>}

        {activeView === "overview" && (
          <>
            <section className="dashboard-grid">
              {dashboardCards.map(({ key, label, filter }) => (
                <button className="metric-card" type="button" key={key} onClick={() => showTasks(filter)}>
                  <span>{label}</span><strong>{workspace.dashboard[key]}</strong>
                </button>
              ))}
            </section>
            <section className="task-section">
              <div className="section-heading overview-table-heading">
                <div><p className="eyebrow">СЕЙЧАС</p><h2>{overviewMode === "priority" ? "Задачи по приоритету" : "График дедлайнов"}</h2></div>
                <div className="overview-controls">
                  <div className="overview-view-switch" aria-label="Вид обзора">
                    <button className={overviewMode === "priority" ? "active" : ""} type="button" onClick={() => setOverviewMode("priority")}>▦ Приоритеты</button>
                    <button className={overviewMode === "timeline" ? "active" : ""} type="button" onClick={() => setOverviewMode("timeline")}>▤ По датам</button>
                  </div>
                  <label className="project-filter-label">
                    Проект
                    <select
                      aria-label="Фильтр проектов"
                      value={overviewProjectFilter}
                      onChange={(event) => setOverviewProjectFilter(event.currentTarget.value)}
                    >
                      <option value="all">Все проекты</option>
                      {workspace.projects.map((project) => <option value={project.id} key={project.id}>{project.name}</option>)}
                    </select>
                  </label>
                  <span className="muted">{overviewTasks.length} задач</span>
                </div>
              </div>
              {overviewMode === "priority" ? (
                <PriorityBoard tasks={overviewTasks} projects={workspace.projects} onSelect={openTask} onDrop={dropPriorityTask} />
              ) : (
                <TimelineView tasks={overviewTasks} projects={workspace.projects} onSelect={openTask} />
              )}
            </section>
          </>
        )}

        {(activeView === "tasks" || activeProject) && (
          <section className="task-section standalone">
            <div className="section-heading">
              <div><p className="eyebrow">{taskFilter ? "ФИЛЬТР" : "СПИСОК"}</p><h2>{taskFilter ? (taskFilter === "overdue" ? "Просроченные" : statusLabels[taskFilter]) : "Все задачи"}</h2></div>
              {taskFilter && <button className="text-button" type="button" onClick={() => setTaskFilter(null)}>Сбросить фильтр</button>}
            </div>
            <TaskList tasks={filteredTasks} onSelect={openTask} />
          </section>
        )}

        {activeView === "notes" && (
          <section className="task-section standalone">
            <div className="notes-actions"><button className="primary-button compact" type="button" onClick={() => openNoteEditor()}>+ Новая заметка</button></div>
            <div className="section-heading"><div><p className="eyebrow">VAULT</p><h2>Все заметки</h2></div><button className="text-button" type="button" onClick={() => void loadNotes(true)}>Обновить</button></div>
            {notesLoading ? <div className="loading-line">Загружаем заметки…</div> : notes.length === 0 ? (
              <div className="empty-state"><span>◇</span><h3>Заметок пока нет</h3><p>Редактор заметок подключим следующим шагом.</p></div>
            ) : (
              <div className="notes-grid">
                {notes.map((note) => (
                  <button className="note-card" type="button" key={note.id} onClick={() => void openNote(note)} onDoubleClick={() => void api.getNote(note.id).then(openNoteEditor)} title="Двойной клик — редактировать">
                    <span className="note-path">{note.path}</span><strong>{note.title}</strong><p>{note.excerpt || "Пустая заметка"}</p>
                  </button>
                ))}
              </div>
            )}
          </section>
        )}

        {activeView === "graph" && (
          <section className="task-section standalone">
            {graphLoading ? <div className="loading-line">Строим карту связей…</div> : graph ? (
              <div className="graph-layout"><KnowledgeGraphView graph={graph} onSelect={setGraphNode} /><aside className="graph-detail-panel">{graphNode ? <><p className="eyebrow">{graphNode.kind === "task" ? "ЗАДАЧА" : "ЗАМЕТКА"}</p><h2>{graphNode.title}</h2><p>{graphNode.subtitle}</p><button className="primary-button compact" type="button" onClick={() => { if (graphNode.kind === "task") { const task = workspace.tasks.find((item) => item.id === graphNode.id); if (task) void openTask(task); } else { void api.getNote(graphNode.id).then(setSelectedNote); } }}>Открыть карточку</button></> : <><p className="eyebrow">НАВИГАЦИЯ</p><h2>Выбери шарик</h2><p>Здесь появится контекст задачи или заметки.</p></>}</aside></div>
            ) : <div className="empty-state"><span>◌</span><h3>Карта ещё не загружена</h3></div>}
          </section>
        )}
      </section>

      {activeView === "graph" && graphNode && (
        <aside className={`graph-detail-drawer ${resizingGraphDrawer ? "resizing" : ""}`} style={{ width: graphDrawerWidth }} aria-label="Карточка элемента карты">
          <div className="drawer-resize-handle" role="separator" aria-orientation="vertical" aria-label="Изменить ширину карточки" onPointerDown={(event) => { event.currentTarget.setPointerCapture(event.pointerId); setResizingGraphDrawer(true); }} onPointerMove={(event) => { if (resizingGraphDrawer) setGraphDrawerWidth(Math.max(360, Math.min(1000, window.innerWidth - event.clientX))); }} onPointerUp={(event) => { event.currentTarget.releasePointerCapture(event.pointerId); setResizingGraphDrawer(false); }} />
          <header><div><p className="eyebrow">{graphNode.kind === "note" ? "ЗАМЕТКА" : "ЗАДАЧА"}</p><h2>{graphNode.title}</h2><p>{graphNode.subtitle}</p></div><button className="icon-button light" type="button" onClick={() => setGraphNode(null)}>×</button></header>
          {graphNode.kind === "note" && graphNote && <div className="graph-share-action"><button className="secondary-button" type="button" onClick={() => openNoteEditor(graphNote)}>✎ Редактировать заметку</button><button className="secondary-button" type="button" onClick={() => void openShareDialog(graphNote)}>↗ Публичный доступ</button>{shareMessage && <p className="share-message">{shareMessage}{shareUrl && <> <a href={shareUrl} target="_blank" rel="noreferrer">Открыть ссылку</a></>}</p>}</div>}
          {graphNode.kind === "note" ? (
            graphNote ? <div className="markdown-document graph-document"><MarkdownContent markdown={graphNote.content_markdown} /></div> : <div className="loading-line">Открываем заметку…</div>
          ) : (
            <div className="graph-task-summary"><span>Статус</span><strong>{statusLabels[graphNode.status ?? "inbox"]}</strong><span>Описание</span><p>{workspace.tasks.find((task) => task.id === graphNode.id)?.description_markdown || "Описание пока не добавлено."}</p></div>
          )}
        </aside>
      )}

      {workspaceMenu && (
        <div className="workspace-context-menu" style={{ left: workspaceMenu.x, top: workspaceMenu.y }} role="menu">
          <p>{workspaceMenu.project.name}</p>
          <button type="button" role="menuitem" onClick={() => void archiveWorkspace(workspaceMenu.project)}>Удалить пространство</button>
          <button type="button" role="menuitem" onClick={() => setWorkspaceMenu(null)}>Отмена</button>
        </div>
      )}

      {selectedTask && (
        <div className="modal-backdrop legacy-task-detail" role="presentation" aria-hidden="true" onMouseDown={(event) => { if (event.target === event.currentTarget) setSelectedTask(null); }}>
          <section className="modal-card detail-card" role="dialog" aria-modal="true" aria-label="Задача">
            <div className="section-heading"><div><p className="eyebrow">{selectedTask.identifier}</p><h2>{selectedTask.title}</h2></div><button className="icon-button light" type="button" onClick={() => setSelectedTask(null)}>×</button></div>
            <div className="detail-meta">
              <label>Статус<select value={selectedTask.status} disabled={busy} onChange={(event) => void changeTaskStatus(event.currentTarget.value as TaskStatus)}>{Object.entries(statusLabels).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>
              <div><span>Исполнитель</span><strong>{String(selectedTask.source_data.assignee_username ?? "Не назначен")}</strong></div>
              <div><span>Создал</span><strong>{String(selectedTask.source_data.created_by_username ?? selectedTask.source)}</strong></div>
              <div><span>Дедлайн</span><strong>{selectedTask.source_data.deadline_start ? `${formatDueDate(String(selectedTask.source_data.deadline_start))} → ${formatDueDate(selectedTask.due_at)}` : formatDueDate(selectedTask.due_at)}</strong></div>
            </div>
            <div className="detail-description"><span>Описание</span><p>{selectedTask.description_markdown || "Описание не добавлено."}</p></div>
            <div className="linked-notes-section">
              <div className="section-heading"><div><p className="eyebrow">КОНТЕКСТ</p><h3>Связанные заметки</h3></div><button className="text-button" type="button" onClick={openNewLinkedNote}>＋ Добавить</button></div>
              {linkedNotes.length ? <div className="linked-note-list">{linkedNotes.map((note) => <button type="button" key={note.id} onClick={() => void openNote(note)}><span>◇</span><div><strong>{note.title}</strong><small>{note.excerpt || note.path}</small></div></button>)}</div> : <p className="muted">Добавь заметку с идеей, решением или материалами по этой задаче.</p>}
            </div>
            {detailError && <div className="error-message">{detailError}</div>}
          </section>
        </div>
      )}

      {selectedNote && (
        <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setSelectedNote(null); }}>
          <section className="modal-card detail-card note-detail" role="dialog" aria-modal="true" aria-label="Заметка">
            <div className="section-heading"><div><p className="eyebrow">{selectedNote.path}</p><h2>{selectedNote.title}</h2></div><button className="icon-button light" type="button" onClick={() => setSelectedNote(null)}>×</button></div>
            <pre>{selectedNote.content_markdown || "Заметка пуста."}</pre>
          </section>
        </div>
      )}

      {createOpen && (
        <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setCreateOpen(false); }}>
          <form className="modal-card task-create-card" role="dialog" aria-modal="true" aria-label="Новая задача" onSubmit={submitNewTask}>
            <div className="section-heading"><div><p className="eyebrow">{activeProject?.key} · {activeProject?.name}</p><h2>Новая задача</h2></div><button className="icon-button light" type="button" onClick={() => setCreateOpen(false)}>×</button></div>
            <label>Что нужно сделать?<input autoFocus value={newTaskTitle} onChange={(event) => setNewTaskTitle(event.currentTarget.value)} maxLength={300} required /></label>
            <DeadlineRangePicker start={newTaskStart} end={newTaskEnd} onStartChange={setNewTaskStart} onEndChange={setNewTaskEnd} />
            <section className="assignment-section">
              <div className="assignment-person"><span className="avatar">{workspace.user.username.slice(0, 1).toUpperCase()}</span><div><small>Создал задачу</small><strong>{workspace.user.username}</strong></div></div>
              <label>
                Исполнитель
                <select aria-label="Исполнитель" value={newTaskAssignee} onChange={(event) => setNewTaskAssignee(event.currentTarget.value)} required>
                  {workspace.users.map((user) => <option value={user.id} key={user.id}>{user.username}</option>)}
                </select>
              </label>
            </section>
            {taskError && <div className="error-message">{taskError}</div>}
            <div className="modal-actions"><button className="secondary-button padded" type="button" onClick={() => setCreateOpen(false)}>Отмена</button><button className="primary-button" type="submit" disabled={busy}>{busy ? "Создаём…" : "Создать задачу"}</button></div>
          </form>
        </div>
      )}

      {noteCreateOpen && selectedTask && (
        <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setNoteCreateOpen(false); }}>
          <form className="modal-card detail-card" role="dialog" aria-modal="true" aria-label="Новая заметка" onSubmit={submitNewLinkedNote}>
            <div className="section-heading"><div><p className="eyebrow">К ЗАДАЧЕ {selectedTask.identifier}</p><h2>Новая заметка</h2></div><button className="icon-button light" type="button" onClick={() => setNoteCreateOpen(false)}>×</button></div>
            <label>Название<input autoFocus value={newNoteTitle} onChange={(event) => setNewNoteTitle(event.currentTarget.value)} maxLength={240} required /></label>
            <label>Содержание<textarea value={newNoteContent} onChange={(event) => setNewNoteContent(event.currentTarget.value)} placeholder="Markdown поддерживается" rows={10} /></label>
            <div className="modal-actions"><button className="secondary-button padded" type="button" onClick={() => setNoteCreateOpen(false)}>Отмена</button><button className="primary-button" type="submit" disabled={busy}>{busy ? "Сохраняем…" : "Создать и связать"}</button></div>
          </form>
        </div>
      )}
      {selectedNote && (
        <div className="modal-backdrop markdown-reader-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setSelectedNote(null); }}>
          <article className="markdown-reader" role="dialog" aria-modal="true" aria-label="Документ">
            <header className="markdown-reader-header"><div><p className="eyebrow">ЗАМЕТКА</p><h1>{selectedNote.title}</h1></div><div className="reader-actions"><button className="icon-button light" type="button" onClick={() => openNoteEditor(selectedNote)} title="Редактировать заметку" aria-label="Редактировать заметку">✎</button><button className="icon-button light" type="button" onClick={() => void openShareDialog(selectedNote)} title="Публичный доступ" aria-label="Публичный доступ">↗</button><button className="icon-button light" type="button" onClick={() => setSelectedNote(null)}>×</button></div></header>
            {shareMessage && <p className="share-message">{shareMessage}{shareUrl && <> <a href={shareUrl} target="_blank" rel="noreferrer">Открыть ссылку</a></>}</p>}
            <div className="markdown-document"><MarkdownContent markdown={selectedNote.content_markdown} /></div>
          </article>
        </div>
      )}

      {noteEditorOpen && (
        <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setNoteEditorOpen(false); }}>
          <form className="modal-card note-editor-card" role="dialog" aria-modal="true" aria-label="Редактор заметки" onSubmit={saveNoteEditor}>
            <div className="section-heading"><div><p className="eyebrow">{editingNote ? "РЕДАКТИРОВАНИЕ" : "НОВАЯ ЗАМЕТКА"}</p><h2>{editingNote ? "Обновить заметку" : "Создать заметку"}</h2></div><button className="icon-button light" type="button" onClick={() => setNoteEditorOpen(false)}>×</button></div>
            <label>Название<input autoFocus value={editorTitle} onChange={(event) => setEditorTitle(event.currentTarget.value)} maxLength={240} placeholder="Например, план запуска" required /></label>
            <label>Теги <span className="field-hint">через запятую</span><input value={editorTags} onChange={(event) => setEditorTags(event.currentTarget.value)} placeholder="идеи, работа, исследование" /></label>
            <label className="editor-field">Текст <span className="field-hint">Markdown: # заголовок, **жирный**, [[ссылка на заметку]]</span><textarea value={editorContent} onChange={(event) => setEditorContent(event.currentTarget.value)} placeholder="# Новая заметка&#10;&#10;Запиши мысль, решение или полезный контекст…" rows={16} /></label>
            {editorError && <div className="error-message">{editorError}</div>}
            <div className="modal-actions"><button className="secondary-button padded" type="button" onClick={() => setNoteEditorOpen(false)}>Отмена</button><button className="primary-button" type="submit" disabled={busy}>{busy ? "Сохраняем…" : "Сохранить заметку"}</button></div>
          </form>
        </div>
      )}
      {selectedTask && (
        <div className="modal-backdrop task-editor-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setSelectedTask(null); }}>
          <form className="modal-card task-editor-card" role="dialog" aria-modal="true" aria-label="Задача" onSubmit={saveTaskEditor}>
            <div className="section-heading"><div><p className="eyebrow">УПРАВЛЕНИЕ ЗАДАЧЕЙ</p><h2>Настройки задачи</h2></div><button className="icon-button light" type="button" onClick={() => setSelectedTask(null)}>×</button></div>
            <label>Название<input autoFocus value={taskEditorTitle} onChange={(event) => setTaskEditorTitle(event.currentTarget.value)} maxLength={300} required /></label>
            <label>Описание<textarea value={taskEditorDescription} onChange={(event) => setTaskEditorDescription(event.currentTarget.value)} placeholder="Что нужно сделать и какой результат ожидается" rows={7} /></label>
            <div className="task-editor-grid">
              <label>Статус<select value={taskEditorStatus} onChange={(event) => setTaskEditorStatus(event.currentTarget.value as TaskStatus)}>{Object.entries(statusLabels).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>
              <label>Приоритет<select value={taskEditorPriority} onChange={(event) => setTaskEditorPriority(Number(event.currentTarget.value))}>{priorityColumns.map((priority) => <option value={priority.value} key={priority.value}>{priority.label}</option>)}</select></label>
            </div>
            <label>Рабочее пространство<select value={taskEditorProject} onChange={(event) => setTaskEditorProject(event.currentTarget.value)}><option value="">Без пространства</option>{workspace.projects.map((project) => <option value={project.id} key={project.id}>{project.parent_id ? `↳ ${project.name}` : project.name}</option>)}</select></label>
            {detailError && <div className="error-message">{detailError}</div>}
            <div className="task-editor-actions"><button className="danger-button" type="button" onClick={() => void archiveTaskFromEditor()} disabled={busy}>Архивировать</button><div className="modal-actions"><button className="secondary-button padded" type="button" onClick={() => setSelectedTask(null)}>Отмена</button><button className="primary-button" type="submit" disabled={busy}>{busy ? "Сохраняем…" : "Сохранить"}</button></div></div>
          </form>
        </div>
      )}

      {workspaceCreateOpen && (
        <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setWorkspaceCreateOpen(false); }}>
          <form className="modal-card workspace-create-card" role="dialog" aria-modal="true" aria-label="Новое рабочее пространство" onSubmit={submitWorkspace}>
            <div className="section-heading"><div><p className="eyebrow">СТРУКТУРА РАБОТЫ</p><h2>{workspaceParent ? "Новое подпространство" : "Новое пространство"}</h2></div><button className="icon-button light" type="button" onClick={() => setWorkspaceCreateOpen(false)}>×</button></div>
            <p className="muted">{workspaceParent ? "Оно будет создано внутри выбранного пространства." : "Верхнее пространство объединяет задачи всех своих подпространств."}</p>
            <label>Название<input autoFocus value={workspaceName} onChange={(event) => setWorkspaceName(event.currentTarget.value)} maxLength={160} placeholder="Например, Маркетинг" required /></label>
            {workspaceError && <div className="error-message">{workspaceError}</div>}
            <div className="modal-actions"><button className="secondary-button padded" type="button" onClick={() => setWorkspaceCreateOpen(false)}>Отмена</button><button className="primary-button" type="submit" disabled={busy}>{busy ? "Создаём…" : "Создать пространство"}</button></div>
          </form>
        </div>
      )}
      {shareDialogNote && (
        <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setShareDialogNote(null); }}>
          <section className="modal-card share-dialog" role="dialog" aria-modal="true" aria-label="Публичный доступ к заметке">
            <div className="section-heading"><div><p className="eyebrow">ПУБЛИЧНЫЙ ДОСТУП</p><h2>Ссылка на заметку</h2></div><button className="icon-button light" type="button" onClick={() => setShareDialogNote(null)}>×</button></div>
            <p className="muted">Любой, у кого есть ссылка, сможет читать «{shareDialogNote.title}» без входа в аккаунт.</p>
            <label>Срок действия
              <select value={shareDuration} onChange={(event) => setShareDuration(event.currentTarget.value)}>
                <option value="1">1 день</option><option value="7">7 дней</option><option value="30">30 дней</option><option value="0">Без срока</option>
              </select>
            </label>
            {shareInfo && shareUrl ? <div className="share-link"><strong>{shareInfo.expires_at ? `Доступ до ${new Date(shareInfo.expires_at).toLocaleString("ru-RU")}` : "Доступ без срока"}</strong><a href={shareUrl} target="_blank" rel="noreferrer">{shareUrl}</a></div> : <p className="muted">Публичная ссылка ещё не создана.</p>}
            {shareMessage && <p className="share-message">{shareMessage}</p>}
            <div className="modal-actions share-actions"><button className="secondary-button padded" type="button" onClick={() => setShareDialogNote(null)}>Готово</button>{shareInfo && <button className="danger-button" type="button" onClick={() => void revokeShareFromDialog()}>Отозвать ссылку</button>}<button className="primary-button" type="button" onClick={() => void createShareFromDialog()}>{shareInfo ? "Обновить срок" : "Создать ссылку"}</button></div>
          </section>
        </div>
      )}
    </main>
  );
}

function App() {
  const match = window.location.pathname.match(/^\/public\/notes\/([^/]+)$/);
  return match ? <PublicNotePage token={decodeURIComponent(match[1])} /> : <WorkspaceApp />;
}

export default App;
