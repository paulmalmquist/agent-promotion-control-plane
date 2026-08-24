import Link from "next/link";

export default function NotFound() {
  return (
    <main className="pcp-app-message">
      <span>CONTROL PLANE / NOT FOUND</span>
      <h1>This promotion view does not exist</h1>
      <p>Return to the overview and select a governed control-plane destination.</p>
      <Link href="/">Return to overview</Link>
    </main>
  );
}
