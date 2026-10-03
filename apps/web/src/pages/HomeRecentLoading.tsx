export function HomeRecentLoading() {
  return (
    <div className="recent-strip recent__loading" role="status" aria-label="Loading recent projects">
      <span className="recent__loading__label">Loading recent projects...</span>
      {[0, 1, 2, 3].map((index) => <div key={index} className="recent recent--skeleton" aria-hidden="true" />)}
    </div>
  );
}
