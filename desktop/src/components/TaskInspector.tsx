import { Archive, Calendar, Check, Circle, MessageSquarePlus, X } from "lucide-react";
import { useState } from "react";
import type { Task } from "../types";

interface Props {
  task: Task | null;
  onClose: () => void;
  onComment: (task: Task, body: string) => void;
  onArchive: (task: Task) => void;
}

export function TaskInspector({ task, onClose, onComment, onArchive }: Props) {
  const [comment, setComment] = useState("");
  if (!task) return null;
  return (
    <aside className="task-inspector">
      <header><span>{task.identifier}</span><button className="icon-button" onClick={onClose}><X size={17} /></button></header>
      <h2>{task.title}</h2>
      <div className="inspector-pills"><span className={`status ${task.status}`}>{task.status.replace("_", " ")}</span><span>Приоритет {task.priority}</span></div>
      {task.due_at && <p className="due"><Calendar size={15} />{new Date(task.due_at).toLocaleString("ru-RU")}</p>}
      <section><p className="section-label">ОПИСАНИЕ</p><div className="description">{task.description_markdown || "Описание пока не добавлено."}</div></section>
      <section><p className="section-label">ЧЕК-ЛИСТ · {task.checklist.filter((item) => item.is_done).length}/{task.checklist.length}</p>{task.checklist.map((item) => <div className="check-row" key={item.id}>{item.is_done ? <Check size={15} /> : <Circle size={15} />}{item.text}</div>)}</section>
      <section className="comments"><p className="section-label">КОММЕНТАРИИ · {task.comments.length}</p>{task.comments.map((item) => <article key={item.id}><span>{item.source}</span><p>{item.body_markdown}</p></article>)}<form onSubmit={(event) => { event.preventDefault(); if (comment.trim()) { onComment(task, comment.trim()); setComment(""); } }}><MessageSquarePlus size={16} /><input value={comment} onChange={(event) => setComment(event.target.value)} placeholder="Добавить комментарий" /></form></section>
      <button className="danger-quiet" onClick={() => onArchive(task)}><Archive size={16} /> Архивировать задачу</button>
    </aside>
  );
}
