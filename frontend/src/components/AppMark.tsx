// The icon file has a white margin around its tile; .app-mark crops to the tile
// so it sits cleanly on dark backgrounds too. Size comes from CSS (--s).
export function AppMark({ alt = "" }: { alt?: string }) {
  return (
    <span className="app-mark">
      <img src="./app-icon.png" alt={alt} />
    </span>
  );
}
