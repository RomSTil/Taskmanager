import { describe, expect, it } from "vitest";

import { ApiError, validateBackendUrl } from "./api";

describe("backend URL validation", () => {
  it("allows HTTPS and local development HTTP", () => {
    expect(validateBackendUrl("https://tasks.example.com/")).toBe("https://tasks.example.com");
    expect(validateBackendUrl("http://127.0.0.1:8765/")).toBe("http://127.0.0.1:8765");
  });

  it("rejects credentials and remote cleartext HTTP", () => {
    expect(() => validateBackendUrl("http://tasks.example.com")).toThrow(ApiError);
    expect(() => validateBackendUrl("https://owner:secret@tasks.example.com")).toThrow(ApiError);
  });
});
