import { DndContext, DragEndEvent, PointerSensor, useDraggable, useDroppable, useSensor, useSensors } from "@dnd-kit/core";
import { CSS } from "@dnd-kit/utilities";
import { CalendarDays, CircleDot, MessageSquare, Plus, Tag } from "lucide-react";
import { useState } from "react";
import type { Project, Task, TaskStatus } from "../types";

const columns: { id: TaskStatus; title: string; accent: string }[] = [
  { id: "inbox", title: "Входящие", accent: "#8c8a84" },
  { id: "todo", title: "К выполнению", accent: "#60a5fa" },
  { id: "in_progress", title: "В работе", accent: "#f5a623" },
  { id: "blocked", title: "Блокер", accent: "#ef6a67" },
  { id: "done", title: "Готово", accent: "#58b894" },
];

function TaskCard({ task, onSelect }: { task: Task; onSelect: (task: Task) => void }) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({ id: task.id });
  return (
    <article
      ref={setNodeRef}
      style={{ transform: CSS.Translate.toString(transform), opacity: isDragging ? 0.55 : 1 }}
      className="task-card"
      onClick={() => onSelect(task)}
      {...listeners}
      {...attributes}
    >
      <div className="task-card-top"><span>{task.identifier}</span><i className={`priority p${task.priority}`} /></div>
      <h3>{task.title}</h3>
      {task.description_markdown && <p>{task.description_markdown.replace(/[#*_`]/g, "").slice(0, 110)}</p>}
      <div className="task-meta">
        {task.due_at && <span><CalendarDays size={13} />{new Date(task.due_at).toLocaleDateString("ru-RU", { day: "2-digit", month: "short" })}</span>}
        {task.tags.length > 0 && <span><Tag size={13} />{task.tags[0]}</span>}
        {task.comments.length > 0 && <span><MessageSquare size={13} />{task.comments.length}</span>}
        {task.checklist.length > 0 && <span><CircleDot size={13} />{task.checklist.filter((item) => item.is_done).length}/{task.checklist.length}</span>}
      </div>
    </article>
  );
}

function Column({ id, title, accent, tasks, onSelect }: (typeof columns)[number] & { tasks: Task[]; onSelect: (task: Task) => void }) {
  const { setNodeRef, isOver } = useDroppable({ id });
  return (
    <section className={isOver ? "kanban-column over" : "kanban-column"} ref={setNodeRef}>
      <header><span className="status-pin" style={{ background: accent }} /><h2>{title}</h2><b>{tasks.length}</b></header>
      <div className="column-cards">{tasks.map((task) => <TaskCard key={task.id} task={task} onSelect={onSelect} />)}</div>
    </section>
  );
}

interface Props {
  tasks: Task[];
  projects: Project[];
  selectedProject: string | null;
  onMove: (task: Task, status: TaskStatus) => void;
  onCreate: (title: string, projectId: string | null) => void;
  onSelect: (task: Task) => void;
}

export function Kanban({ tasks, projects, selectedProject, onMove, onCreate, onSelect }: Props) {
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 7 } }));
  const [title, setTitle] = useState("");
  const project = projects.find((item) => item.id === selectedProject);
  function dragEnd(event: DragEndEvent) {
    const task = tasks.find((item) => item.id === event.active.id);
    const status = event.over?.id as TaskStatus | undefined;
    if (task && status && columns.some((column) => column.id === status) && task.status !== status) onMove(task, status);
  }
  function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!title.trim()) return;
    onCreate(title.trim(), selectedProject);
    setTitle("");
  }
  return (
    <div className="workspace-view board-view">
      <header className="page-header">
        <div><p className="eyebrow">{project?.key || "WORKSPACE"}</p><h1>{project?.name || "Все задачи"}</h1></div>
        <form className="quick-add" onSubmit={submit}><button type="submit" aria-label="Создать задачу"><Plus size={17} /></button><input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Быстро добавить задачу…" /><kbd>Enter</kbd></form>
      </header>
      <DndContext sensors={sensors} onDragEnd={dragEnd}>
        <div className="kanban-board">
          {columns.map((column) => <Column key={column.id} {...column} tasks={tasks.filter((task) => task.status === column.id)} onSelect={onSelect} />)}
        </div>
      </DndContext>
    </div>
  );
}
