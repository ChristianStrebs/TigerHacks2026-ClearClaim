import { Fragment } from "react";

// The backend asks for **bold** and - bullets, but models also write *italics*,
// "* " or "• " bullets and # headings. React escapes all other content;
// policy text is never inserted as HTML.
const BULLET = /^\s*[-*•]\s+/;
const HEADING = /^\s*#{1,6}\s+/;

function inline(text: string) {
  return text
    .split(/(\*\*[^*]+\*\*|\*[^*\s][^*]*\*)/g)
    .map((part, index) =>
      part.startsWith("**") && part.endsWith("**") ? (
        <strong key={index}>{part.slice(2, -2)}</strong>
      ) : part.length > 2 && part.startsWith("*") && part.endsWith("*") ? (
        <em key={index}>{part.slice(1, -1)}</em>
      ) : (
        <Fragment key={index}>{part}</Fragment>
      ),
    );
}

export function PolicyText({ text }: { text: string }) {
  const groups: { bullets: boolean; lines: string[] }[] = [];
  for (const line of text.split(/\r?\n/).filter((line) => line.trim())) {
    const bullets = BULLET.test(line);
    const content = bullets
      ? line.replace(BULLET, "")
      : HEADING.test(line)
        ? `**${line.replace(HEADING, "").replace(/\*\*/g, "")}**`
        : line;
    const last = groups[groups.length - 1];
    if (bullets && last?.bullets) last.lines.push(content);
    else groups.push({ bullets, lines: [content] });
  }
  return (
    <div className="policy-text">
      {groups.map((group, index) =>
        group.bullets ? (
          <ul key={index}>
            {group.lines.map((line, i) => (
              <li key={i}>{inline(line)}</li>
            ))}
          </ul>
        ) : (
          <p key={index}>{inline(group.lines[0])}</p>
        ),
      )}
    </div>
  );
}
