import { Fragment } from "react";

// The backend emits **bold** and - bullets. React escapes all other content;
// policy text is never inserted as HTML.
function inline(text: string) {
  return text
    .split(/(\*\*[^*]+\*\*)/g)
    .map((part, index) =>
      part.startsWith("**") && part.endsWith("**") ? (
        <strong key={index}>{part.slice(2, -2)}</strong>
      ) : (
        <Fragment key={index}>{part}</Fragment>
      ),
    );
}

export function PolicyText({ text }: { text: string }) {
  const groups: { bullets: boolean; lines: string[] }[] = [];
  for (const line of text.split(/\r?\n/).filter((line) => line.trim())) {
    const bullets = /^\s*-\s/.test(line);
    const content = bullets ? line.replace(/^\s*-\s+/, "") : line;
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
