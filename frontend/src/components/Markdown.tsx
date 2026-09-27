import type { ReactNode } from "react";

const BULLET = /^\s*[-*•]\s+/;
const HEADING = /^\s*#{1,6}\s+/;

const EMPHASIS = /(\*\*[^*]+\*\*|\*[^*\s][^*]*\*)/g;

function inline(text: string): ReactNode[] {
  return text.split(EMPHASIS).map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**") && part.length > 4) {
      return <strong key={i}>{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith("*") && part.endsWith("*") && part.length > 2) {
      return <em key={i}>{part.slice(1, -1)}</em>;
    }
    return part;
  });
}

/**
 * Renders the small markdown subset Gemini is asked to use (paragraphs, bullets,
 * bold) as React elements, so model output is never injected as raw HTML.
 */
export function Markdown({ text }: { text: string }) {
  const blocks: ReactNode[] = [];
  let bullets: string[] = [];

  const flushBullets = () => {
    if (bullets.length === 0) return;
    blocks.push(
      <ul key={blocks.length}>
        {bullets.map((b, i) => (
          <li key={i}>{inline(b)}</li>
        ))}
      </ul>,
    );
    bullets = [];
  };

  for (const line of text.split("\n")) {
    if (BULLET.test(line)) {
      bullets.push(line.replace(BULLET, ""));
      continue;
    }
    flushBullets();
    if (!line.trim()) continue;
    const content = line.replace(HEADING, "");
    blocks.push(
      HEADING.test(line) ? (
        <p key={blocks.length}>
          <strong>{inline(content)}</strong>
        </p>
      ) : (
        <p key={blocks.length}>{inline(content)}</p>
      ),
    );
  }
  flushBullets();

  return <div className="markdown">{blocks}</div>;
}
