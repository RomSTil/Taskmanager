import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import type { WorkspaceBootstrap } from "./types";

const workspace: WorkspaceBootstrap = {
  server_time: "2026-07-19T09:00:00Z",
  user: {
    id: "user-1",
    username: "owner",
    created_at: "2026-07-19T08:00:00Z",
  },
  users: [
    {
      id: "user-1",
      username: "owner",
      created_at: "2026-07-19T08:00:00Z",
    },
  ],
  projects: [
    {
      id: "project-1",
      parent_id: null,
      name: "Личное пространство",
      key: "HOME",
      description: "",
      color: "#8b5cf6",
      version: 1,
      archived_at: null,
      created_at: "2026-07-19T08:00:00Z",
      updated_at: "2026-07-19T08:00:00Z",
    },
    {
      id: "project-2",
      parent_id: null,
      name: "Работа",
      key: "WORK",
      description: "",
      color: "#22c55e",
      version: 1,
      archived_at: null,
      created_at: "2026-07-19T08:00:00Z",
      updated_at: "2026-07-19T08:00:00Z",
    },
  ],
  tasks: [
    {
      id: "task-1",
      title: "написать task manager",
      description_markdown: "Проверить рабочий интерфейс.",
      project_id: "project-1",
      parent_id: null,
      sequence: 1,
      status: "inbox",
      priority: 1,
      due_at: "2026-10-31T20:59:59Z",
      completed_at: null,
      tags: [],
      source: "manual",
      source_data: {
        deadline_start: "2026-10-20T00:00:00Z",
        assignee_username: "owner",
      },
      version: 1,
      archived_at: null,
      created_at: "2026-07-19T08:00:00Z",
      updated_at: "2026-07-19T08:00:00Z",
      checklist: [],
      comments: [],
      identifier: "HOME-1",
    },
    {
      id: "task-2",
      title: "подготовить отчёт",
      description_markdown: "",
      project_id: "project-2",
      parent_id: null,
      sequence: 1,
      status: "todo",
      priority: 2,
      due_at: "2026-10-27T20:59:59Z",
      completed_at: null,
      tags: [],
      source: "manual",
      source_data: {
        deadline_start: "2026-10-24T00:00:00Z",
        assignee_username: "owner",
      },
      version: 1,
      archived_at: null,
      created_at: "2026-07-19T08:00:00Z",
      updated_at: "2026-07-19T08:00:00Z",
      checklist: [],
      comments: [],
      identifier: "WORK-1",
    },
  ],
  views: [],
  dashboard: {
    inbox: 1,
    todo: 1,
    in_progress: 0,
    blocked: 0,
    done: 0,
    overdue: 0,
  },
};

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("workspace navigation", () => {
  beforeEach(() => {
    localStorage.clear();
    localStorage.setItem(
      "taskman.session",
      JSON.stringify({ access_token: "test-access", refresh_token: "test-refresh" }),
    );
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("/api/v1/auth/setup")) {
          return jsonResponse({ setup_required: false });
        }
        if (url.endsWith("/api/v1/bootstrap")) {
          return jsonResponse(workspace);
        }
        if (url.endsWith("/api/v1/notes")) {
          return jsonResponse([]);
        }
        return jsonResponse({ detail: "Not found" }, 404);
      }),
    );
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("opens every primary clickable workspace surface", async () => {
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Доброе утро, owner" })).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: /Мои задачи/ }));
    expect(screen.getByRole("heading", { name: "Мои задачи" })).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: /Личное пространство/ }));
    expect(screen.getByRole("heading", { name: "Личное пространство" })).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: /написать task manager/ }));
    expect(screen.getByRole("dialog", { name: "Задача" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "×" }));

    fireEvent.click(screen.getByRole("button", { name: /Заметки/ }));
    expect(await screen.findByRole("heading", { name: "Все заметки" })).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: /Обзор/ }));
    expect(screen.queryByRole("button", { name: /Новая задача/ })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Личное пространство/ }));
    fireEvent.click(screen.getByRole("button", { name: /Новая задача/ }));
    expect(screen.getByRole("heading", { name: "Новая задача" })).toBeVisible();
    const createDialog = screen.getByRole("dialog", { name: "Новая задача" });
    expect(within(createDialog).getByLabelText("Начало дедлайна")).toHaveValue("2026-10-20");
    expect(within(createDialog).getByLabelText("Конец дедлайна")).toHaveValue("2026-10-31");
    expect(within(createDialog).getByLabelText("Исполнитель")).toHaveValue("user-1");
    expect(within(createDialog).queryByText("Приоритет")).not.toBeInTheDocument();
    expect(within(createDialog).queryByLabelText("Проект")).not.toBeInTheDocument();
  });

  it("renders the priority board, filters projects, and switches to the timeline", async () => {
    const { container } = render(<App />);
    expect(await screen.findByRole("heading", { name: "Доброе утро, owner" })).toBeVisible();

    const board = container.querySelector(".priority-board");
    expect(board).not.toBeNull();
    expect(board?.querySelectorAll(".priority-column")).toHaveLength(4);
    expect(within(board as HTMLElement).getByRole("button", { name: workspace.tasks[0].title })).toBeVisible();
    expect(within(board as HTMLElement).getByRole("button", { name: workspace.tasks[1].title })).toBeVisible();
    expect(within(board as HTMLElement).getAllByRole("button", { name: /Перетащить задачу/ })).toHaveLength(2);

    fireEvent.change(screen.getByRole("combobox"), {
      target: { value: "project-2" },
    });

    expect(within(board as HTMLElement).queryByRole("button", { name: workspace.tasks[0].title })).not.toBeInTheDocument();
    expect(within(board as HTMLElement).getByRole("button", { name: workspace.tasks[1].title })).toBeVisible();

    const viewSwitch = container.querySelector(".overview-view-switch");
    expect(viewSwitch).not.toBeNull();
    fireEvent.click(within(viewSwitch as HTMLElement).getAllByRole("button")[1]);

    const timeline = screen.getByRole("table");
    expect(within(timeline).getAllByText(workspace.tasks[1].title)).toHaveLength(2);
    expect(within(timeline).queryByText(workspace.tasks[0].title)).not.toBeInTheDocument();
    expect(container.querySelector(".timeline-scroll")).toBeInTheDocument();
    expect(container.querySelectorAll(".timeline-task-bar")).toHaveLength(1);
  });
});
