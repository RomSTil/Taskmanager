import { beforeEach, describe, expect, it } from "vitest";
import { getQueue, queueMutation, readCache, saveCache } from "./offline";

describe("offline persistence", () => {
  beforeEach(() => localStorage.clear());

  it("keeps idempotent mutations across application restarts", () => {
    const queued = queueMutation("POST", "/tasks", { title: "Offline task" });
    expect(queued.id).toHaveLength(36);
    expect(getQueue()).toEqual([queued]);
  });

  it("stores the last readable server snapshot", () => {
    saveCache("tasks", [{ id: "one" }]);
    expect(readCache("tasks", [])).toEqual([{ id: "one" }]);
  });
});
