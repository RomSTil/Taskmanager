export function stripFrontmatter(markdown: string): string {
  return markdown.replace(/^---\r?\n[\s\S]*?\r?\n---\r?\n?/, "");
}

export function findWikilinks(markdown: string): string[] {
  const matches = markdown.matchAll(/\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]/g);
  return [...new Set(Array.from(matches, (match) => match[1].trim()).filter(Boolean))];
}
