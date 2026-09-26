export function currency(n: number, cents = false): string {
  return n.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: cents ? 2 : 0,
  });
}

export function percent(rate: number): string {
  return `${Math.round(rate * 100)}%`;
}
