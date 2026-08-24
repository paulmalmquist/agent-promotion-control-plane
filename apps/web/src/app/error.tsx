"use client";

export default function ErrorBoundary({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <main className="pcp-app-message">
      <span>CONTROL PLANE / UNAVAILABLE</span>
      <h1>The promotion snapshot failed to load</h1>
      <p>Check FastAPI health, then retry without changing any candidate state.</p>
      <button type="button" onClick={reset}>Retry snapshot load</button>
    </main>
  );
}
