import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, TaskmanApi, validateBackendUrl } from "./api";
import type { Note } from "./types";

describe("backend URL validation", () => {
  afterEach(() => {
    localStorage.clear();
    vi.unstubAllGlobals();
  });

  it("allows HTTPS and local development HTTP", () => {
    expect(validateBackendUrl("https://tasks.example.com/")).toBe("https://tasks.example.com");
    expect(validateBackendUrl("http://127.0.0.1:8765/")).toBe("http://127.0.0.1:8765");
  });

  it("rejects credentials and remote cleartext HTTP", () => {
    expect(() => validateBackendUrl("http://tasks.example.com")).toThrow(ApiError);
    expect(() => validateBackendUrl("https://owner:secret@tasks.example.com")).toThrow(ApiError);
  });

  it("archives a note with its current revision", async () => {
    localStorage.setItem("taskman.session", JSON.stringify({ access_token: "access", refresh_token: "refresh" }));
    const fetchMock = vi.fn(async () => new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    await new TaskmanApi("http://127.0.0.1:8765").archiveNote({ id: "note-1", revision: 3 } as Note);

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8765/api/v1/notes/note-1?base_revision=3",
      expect.objectContaining({ method: "DELETE" }),
    );
  });
});
