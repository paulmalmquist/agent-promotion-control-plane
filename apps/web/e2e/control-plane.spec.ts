import { expect, test } from "@playwright/test";

test("renders the evidence-led overview without horizontal overflow", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Promotion control plane" })).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
});

test("keeps automation ownership and disconnected behavior explicit", async ({ page }) => {
  await page.goto("/automation");
  await expect(page.getByRole("heading", { name: "Trigger ownership" })).toBeVisible();
  await expect(page.getByText("This control plane does not execute cron.")).toBeVisible();
  await expect(page.getByText(/external schedulers/i).first()).toBeVisible();
});

test("supports keyboard navigation and visible focus", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Promotion control plane" })).toBeVisible();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Skip to promotion content" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator("#promotion-main")).toBeFocused();
  await page.keyboard.press("Tab");
  const focused = page.locator(":focus");
  await expect(focused).toBeVisible();
});

test("remains legible with reduced motion and mobile layout", async ({ page, isMobile }) => {
  test.skip(!isMobile, "Mobile project covers the compact layout.");
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/candidates");
  await expect(page.getByRole("heading", { name: "Candidate inventory" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Promotion sections" })).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
});

test("shows hard-gate precedence and the autonomous cycle through worker activation", async ({
  page,
  request,
  isMobile
}) => {
  test.skip(Boolean(isMobile), "The desktop project covers the stateful demo flow once.");
  const liveApiEnabled = Boolean(process.env.PROMOTION_E2E_API_URL || process.env.PLAYWRIGHT_BASE_URL);
  test.skip(!liveApiEnabled, "The local fixture server has no live API or worker.");
  const reset = await request.post("/api/control/api/v1/demo/reset", {
    headers: { "Idempotency-Key": `playwright-reset-${Date.now()}` },
    data: { actor: "playwright-reviewer" }
  });
  const resetBody = await reset.text();
  expect(reset.ok(), `Demo reset failed: ${resetBody}`).toBe(true);

  const resetEvents = await request.get("/api/control/api/v1/events?limit=500");
  expect(resetEvents.ok()).toBe(true);
  const resetEventBody = await resetEvents.json() as { next_after: number };
  const cycleAfter = resetEventBody.next_after;

  const candidateResponse = await request.get("/api/control/api/v1/candidates");
  expect(candidateResponse.ok()).toBe(true);
  const candidateBody = await candidateResponse.json() as { items: Array<{ id: string; slug: string }> };
  const hardGateCandidate = candidateBody.items.find((candidate) => candidate.slug === "deployment-advisor");
  expect(hardGateCandidate).toBeTruthy();
  await page.goto(`/candidates/${hardGateCandidate!.id}`);
  await expect(page.getByRole("heading", { name: "Deployment Advisor" })).toBeVisible();
  await expect(page.getByRole("heading", { name: /Latency hard gate failed/i })).toBeVisible();
  const readinessCard = page.locator(".pcp-metric-card").filter({ hasText: "Evaluation readiness" });
  await expect(readinessCard).toBeVisible();
  const readinessText = await readinessCard.locator("strong").innerText();
  expect(Number.parseFloat(readinessText)).toBeGreaterThan(75);
  await expect(page.getByText("Not eligible", { exact: true })).toBeVisible();

  await page.goto("/automation");
  await page.getByRole("button", { name: "Run autonomous cycle" }).click();
  await expect(page.getByRole("status")).toContainText("Dispatched the demo cycle");
  const liveCycle = page.getByRole("region", { name: "Live autonomous cycle" });
  await expect(liveCycle).toBeVisible({ timeout: 45_000 });

  let discoveredId = "";
  await expect.poll(async () => {
    const response = await request.get("/api/control/api/v1/candidates");
    const body = await response.json() as {
      items: Array<{ id: string; slug: string; stage: string }>;
    };
    const discovered = body.items.find((candidate) => candidate.slug === "change-risk-coordinator");
    discoveredId = discovered?.id ?? "";
    return discoveredId;
  }, { timeout: 45_000, intervals: [100, 300, 600] }).not.toBe("");

  const intermediateLineage = [
    "CANDIDATE_DISCOVERED",
    "EVALUATION_PLANNED",
    "EVALUATION_STARTED",
    "EVALUATION_COMPLETED",
    "ELIGIBILITY_DECIDED",
    "PROMOTION_REGISTRY_QUEUED"
  ];
  await expect.poll(async () => {
    const response = await request.get(
      `/api/control/api/v1/events?candidate_id=${encodeURIComponent(discoveredId)}&after=${cycleAfter}&limit=100`
    );
    expect(response.ok()).toBe(true);
    const body = await response.json() as { items: Array<{ event_type: string }> };
    return intermediateLineage.every((type) => body.items.some((event) => event.event_type === type));
  }, { timeout: 45_000, intervals: [100, 300, 600] }).toBe(true);

  await expect(liveCycle.getByText(/Candidate discovered/i).first()).toBeVisible();
  await expect(liveCycle.getByText(/Evaluation planned/i).first()).toBeVisible();
  await expect(liveCycle.getByText(/Evaluation started/i).first()).toBeVisible();
  await expect(liveCycle.getByText(/Evaluation completed/i).first()).toBeVisible();
  await expect(liveCycle.getByText(/Eligibility decided/i).first()).toBeVisible();
  await expect(liveCycle.getByText(/Promotion registry queued/i).first()).toBeVisible();

  await expect.poll(async () => {
    const response = await request.get("/api/control/api/v1/candidates");
    const body = await response.json() as { items: Array<{ id: string; stage: string }> };
    return body.items.find((candidate) => candidate.id === discoveredId)?.stage ?? "MISSING";
  }, { timeout: 45_000, intervals: [100, 300, 600] }).toBe("MONITORED");

  const eventsResponse = await request.get(
    `/api/control/api/v1/events?candidate_id=${encodeURIComponent(discoveredId)}&after=${cycleAfter}&limit=100`
  );
  expect(eventsResponse.ok()).toBe(true);
  const eventsBody = await eventsResponse.json() as {
    items: Array<{
      sequence: number;
      event_type: string;
      correlation_id: string;
      causation_id: string | null;
    }>;
  };
  const requiredLineage = [
    "CANDIDATE_DISCOVERED",
    "EVALUATION_PLANNED",
    "EVALUATION_STARTED",
    "EVALUATION_COMPLETED",
    "ELIGIBILITY_DECIDED",
    "PROMOTION_APPROVED",
    "PROMOTION_REGISTRY_QUEUED",
    "PROMOTED",
    "POST_PROMOTION_MONITORING_OBSERVED"
  ];
  const positions = requiredLineage.map((eventType) =>
    eventsBody.items.findIndex((event) => event.event_type === eventType)
  );
  expect(positions.every((position) => position >= 0)).toBe(true);
  expect([...positions].sort((left, right) => left - right)).toEqual(positions);
  const sequences = eventsBody.items.map((event) => event.sequence);
  expect([...sequences].sort((left, right) => left - right)).toEqual(sequences);
  expect(new Set(eventsBody.items.map((event) => event.correlation_id)).size).toBe(1);
  expect(eventsBody.items.slice(1).some((event) => event.causation_id)).toBe(true);
  await expect(liveCycle.getByText("Promoted", { exact: true }).first()).toBeVisible();
  await expect(liveCycle.getByText(/Post promotion monitoring observed/i).first()).toBeVisible();

  await page.goto(`/candidates/${discoveredId}`);
  await expect(page.getByRole("heading", { name: "Change Risk Coordinator" })).toBeVisible();
  await expect(page.getByText("Succeeded", { exact: true })).toBeVisible();
  await expect(page.getByText("Monitored", { exact: true }).last()).toBeVisible();
});
