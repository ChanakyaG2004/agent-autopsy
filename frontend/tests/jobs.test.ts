import test, { type TestContext } from "node:test";
import assert from "node:assert/strict";
import { isJob, jobActive, submissionBody, submitJob, type Job } from "../src/lib/jobs";

const id = "00000000-0000-4000-8000-000000000001";
const second = "00000000-0000-4000-8000-000000000002";
const queued: Job = { job_version: "durable-jobs-v1", id, request_id: second, kind: "run", status: "queued",
  experiment_id: id, run_id: second, benchmark_id: null, attempts: 0, worker_id: null, lease_expires_at: null,
  error: null, created_at: "2026-10-23T12:00:00Z", started_at: null, finished_at: null };

test("job lifecycle preserves terminal timestamps, lease state, and target identity", () => {
  assert.ok(isJob(queued) && jobActive(queued));
  assert.ok(isJob({ ...queued, status: "running", lease_expires_at: queued.created_at, started_at: queued.created_at, attempts: 1 }));
  assert.ok(!isJob({ ...queued, status: "running" }));
  assert.ok(!isJob({ ...queued, finished_at: queued.created_at }));
  assert.ok(!isJob({ ...queued, benchmark_id: id }));
  assert.ok(!isJob({ ...queued, status: "succeeded" }));
  const interrupted = { ...queued, status: "interrupted", finished_at: queued.created_at };
  assert.ok(isJob(interrupted));
  assert.equal(jobActive(interrupted as Job), false);
  assert.ok(!isJob({ ...queued, attempts: 4 }));
});

test("a persisted submission retains identity and cannot silently change driver", () => {
  const previous = submissionBody(null, { mode: "demo" }, id);
  assert.deepEqual(submissionBody(previous, { mode: "demo" }, second), previous);
  assert.throws(() => submissionBody(previous, { mode: "ollama" }, second));
  assert.throws(() => submissionBody({ ...previous, request_id: "corrupt" }, { mode: "demo" }, second));
});

function storage(t: TestContext) {
  const values = new Map<string, string>();
  const original = Object.getOwnPropertyDescriptor(globalThis, "localStorage");
  Object.defineProperty(globalThis, "localStorage", { configurable: true, value: {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => values.set(key, value), removeItem: (key: string) => values.delete(key),
  } });
  t.after(() => { if (original) Object.defineProperty(globalThis, "localStorage", original); else Reflect.deleteProperty(globalThis, "localStorage"); });
  return values;
}

test("a lost acceptance response keeps the same request across an explicit retry", async t => {
  const values = storage(t);
  const bodies: Record<string, unknown>[] = [];
  t.mock.method(globalThis, "fetch", async (_url: Parameters<typeof fetch>[0], options?: Parameters<typeof fetch>[1]) => {
    const body = JSON.parse(String(options?.body)); bodies.push(body);
    if (bodies.length === 1) throw new TypeError("network lost");
    return new Response(JSON.stringify({ ...queued, request_id: body.request_id }), { status: 202 });
  });
  await assert.rejects(submitJob(`/experiments/${id}/jobs`, { mode: "demo" }, "pending"));
  assert.ok(values.has("pending"));
  await submitJob(`/experiments/${id}/jobs`, { mode: "demo" }, "pending");
  assert.equal(bodies[0].request_id, bodies[1].request_id);
  assert.equal(values.has("pending"), false);
});

test("malformed acceptance retains tracking while a definitive rejection clears it", async t => {
  const values = storage(t);
  const mock = t.mock.method(globalThis, "fetch", async () => new Response(JSON.stringify({ ...queued, id: "corrupt" }), { status: 202 }));
  await assert.rejects(submitJob(`/experiments/${id}/jobs`, { mode: "demo" }, "pending"));
  assert.ok(values.has("pending"));
  mock.mock.mockImplementation(async () => new Response(JSON.stringify({ detail: "Experiment has active work" }), { status: 409 }));
  await assert.rejects(submitJob(`/experiments/${id}/jobs`, { mode: "demo" }, "pending"));
  assert.equal(values.has("pending"), false);
});
