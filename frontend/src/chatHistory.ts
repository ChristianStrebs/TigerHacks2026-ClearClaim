import type { ChatTurn } from "./types";

interface CompletedExchange {
  question: string;
  response?: { answer: string };
}

/** Only successful Q/A text, oldest first; never bill cards, errors or plan summaries. */
export function chatHistory(exchanges: CompletedExchange[]): ChatTurn[] {
  return exchanges
    .filter((exchange) => exchange.response)
    .flatMap((exchange): ChatTurn[] => [
      { role: "user", text: exchange.question },
      { role: "assistant", text: exchange.response!.answer },
    ])
    .map((turn) => ({
      ...turn,
      text: Array.from(turn.text).slice(0, 4000).join(""),
    }))
    .filter((turn) => turn.text.trim())
    .slice(-20);
}
