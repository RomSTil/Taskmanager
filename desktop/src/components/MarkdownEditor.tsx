import { useEffect, useMemo } from "react";
import { EditorContent, useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import Image from "@tiptap/extension-image";
import Link from "@tiptap/extension-link";
import { Table } from "@tiptap/extension-table";
import { TableCell } from "@tiptap/extension-table-cell";
import { TableHeader } from "@tiptap/extension-table-header";
import { TableRow } from "@tiptap/extension-table-row";
import DOMPurify from "dompurify";
import { marked } from "marked";
import TurndownService from "turndown";
import { gfm } from "turndown-plugin-gfm";
import { Bold, Code2, Heading1, Heading2, ImagePlus, Italic, Link2, List, ListOrdered, Quote, Table2 } from "lucide-react";
import { stripFrontmatter } from "../lib/markdown";

interface Props {
  value: string;
  onChange: (value: string) => void;
}

export function MarkdownEditor({ value, onChange }: Props) {
  const turndown = useMemo(() => {
    const service = new TurndownService({ headingStyle: "atx", bulletListMarker: "-", codeBlockStyle: "fenced" });
    service.use(gfm);
    return service;
  }, []);
  const editor = useEditor({
    extensions: [
      StarterKit,
      Link.configure({ openOnClick: false, autolink: true }),
      Image,
      Table.configure({ resizable: true }),
      TableRow,
      TableHeader,
      TableCell,
    ],
    content: DOMPurify.sanitize(marked.parse(stripFrontmatter(value)) as string),
    editorProps: { attributes: { class: "rich-editor-content" } },
    onUpdate: ({ editor: current }) => onChange(turndown.turndown(current.getHTML())),
  });

  useEffect(() => {
    if (!editor || editor.isFocused) return;
    const incoming = turndown.turndown(editor.getHTML()).trim();
    if (incoming !== stripFrontmatter(value).trim()) {
      editor.commands.setContent(DOMPurify.sanitize(marked.parse(stripFrontmatter(value)) as string), { emitUpdate: false });
    }
  }, [editor, turndown, value]);

  if (!editor) return null;
  const link = () => {
    const href = window.prompt("URL ссылки", editor.getAttributes("link").href || "https://");
    if (href) editor.chain().focus().extendMarkRange("link").setLink({ href }).run();
  };
  const image = () => {
    const src = window.prompt("URL изображения");
    if (src) editor.chain().focus().setImage({ src }).run();
  };
  const buttons = [
    { label: "H1", icon: Heading1, action: () => editor.chain().focus().toggleHeading({ level: 1 }).run(), active: editor.isActive("heading", { level: 1 }) },
    { label: "H2", icon: Heading2, action: () => editor.chain().focus().toggleHeading({ level: 2 }).run(), active: editor.isActive("heading", { level: 2 }) },
    { label: "Жирный", icon: Bold, action: () => editor.chain().focus().toggleBold().run(), active: editor.isActive("bold") },
    { label: "Курсив", icon: Italic, action: () => editor.chain().focus().toggleItalic().run(), active: editor.isActive("italic") },
    { label: "Список", icon: List, action: () => editor.chain().focus().toggleBulletList().run(), active: editor.isActive("bulletList") },
    { label: "Нумерация", icon: ListOrdered, action: () => editor.chain().focus().toggleOrderedList().run(), active: editor.isActive("orderedList") },
    { label: "Цитата", icon: Quote, action: () => editor.chain().focus().toggleBlockquote().run(), active: editor.isActive("blockquote") },
    { label: "Код", icon: Code2, action: () => editor.chain().focus().toggleCodeBlock().run(), active: editor.isActive("codeBlock") },
  ];
  return (
    <div className="rich-editor">
      <div className="editor-toolbar">
        {buttons.map(({ label, icon: Icon, action, active }) => <button key={label} title={label} className={active ? "active" : ""} onClick={action}><Icon size={16} /></button>)}
        <span />
        <button title="Ссылка" onClick={link}><Link2 size={16} /></button>
        <button title="Изображение" onClick={image}><ImagePlus size={16} /></button>
        <button title="Таблица" onClick={() => editor.chain().focus().insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run()}><Table2 size={16} /></button>
      </div>
      <EditorContent editor={editor} />
    </div>
  );
}
