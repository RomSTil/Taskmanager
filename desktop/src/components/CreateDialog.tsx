import { X } from "lucide-react";
import { FormEvent, useEffect, useMemo, useState } from "react";

export type CreateKind = "project" | "task" | "note";

interface Props {
  kind: CreateKind | null;
  onClose: () => void;
  onSubmit: (name: string, projectKey?: string) => Promise<void> | void;
}

const copy: Record<CreateKind, { title: string; label: string; placeholder: string }> = {
  project: { title: "Новый проект", label: "Название проекта", placeholder: "Например, Taskman" },
  task: { title: "Новая задача", label: "Название задачи", placeholder: "Что нужно сделать?" },
  note: { title: "Новая заметка", label: "Название заметки", placeholder: "Название документа" },
};

export function CreateDialog({ kind, onClose, onSubmit }: Props) {
  const [name, setName] = useState("");
  const [projectKey, setProjectKey] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const labels = useMemo(() => kind ? copy[kind] : null, [kind]);

  useEffect(() => {
    setName("");
    setProjectKey("");
    setSubmitting(false);
  }, [kind]);

  if (!kind || !labels) return null;

  const suggestedKey = name.replace(/[^A-Za-zА-Яа-я0-9]/g, "").slice(0, 4).toUpperCase() || "PROJ";

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!name.trim()) return;
    setSubmitting(true);
    try {
      await onSubmit(name.trim(), kind === "project" ? (projectKey.trim() || suggestedKey) : undefined);
      onClose();
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="modal-backdrop" onMouseDown={onClose} role="presentation">
      <form className="create-dialog" onMouseDown={(event) => event.stopPropagation()} onSubmit={submit} aria-labelledby="create-dialog-title">
        <header>
          <div>
            <p className="eyebrow">БЫСТРОЕ СОЗДАНИЕ</p>
            <h2 id="create-dialog-title">{labels.title}</h2>
          </div>
          <button className="icon-button" type="button" aria-label="Закрыть" onClick={onClose}><X size={17} /></button>
        </header>
        <label>{labels.label}
          <input autoFocus value={name} onChange={(event) => setName(event.target.value)} placeholder={labels.placeholder} />
        </label>
        {kind === "project" && <label>Ключ проекта
          <input value={projectKey} onChange={(event) => setProjectKey(event.target.value.toUpperCase())} placeholder={suggestedKey} maxLength={12} />
        </label>}
        <footer>
          <button type="button" className="secondary-button" onClick={onClose}>Отмена</button>
          <button type="submit" className="primary-button" disabled={!name.trim() || submitting}>{submitting ? "Создание…" : "Создать"}</button>
        </footer>
      </form>
    </div>
  );
}
