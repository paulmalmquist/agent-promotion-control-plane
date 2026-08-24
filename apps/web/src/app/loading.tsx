export default function Loading() {
  return (
    <div className="pcp-app-message" role="status">
      <span>CONTROL PLANE / LOADING</span>
      <h1>Loading durable promotion state</h1>
      <p>The interface will render after the latest PostgreSQL snapshot arrives.</p>
    </div>
  );
}
