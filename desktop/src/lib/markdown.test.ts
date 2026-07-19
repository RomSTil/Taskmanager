import { describe, expect, it } from "vitest";
import { findWikilinks, stripFrontmatter } from "./markdown";

describe("Markdown helpers", () => {
  it("keeps the document body when Taskman frontmatter is present", () => {
    const source = "---\ntaskman_id: abc\ntags:\n  - dev\n---\n# Title\nBody";
    expect(stripFrontmatter(source)).toBe("# Title\nBody");
  });

  it("extracts Obsidian wikilinks without aliases and headings", () => {
    expect(findWikilinks("[[Architecture]] [[Architecture#API|API]] [[Runbook|prod]]")).toEqual([
      "Architecture",
      "Runbook",
    ]);
  });
});
