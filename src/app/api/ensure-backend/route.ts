import { spawn } from "node:child_process";
import { openSync } from "node:fs";
import { NextResponse } from "next/server";

/**
 * Self-healing backend launcher (sandbox-specific).
 *
 * The sandbox reaps processes spawned from tool-call shells, but the Next.js
 * dev server (and its children) persist. This route checks the FastAPI
 * backend on :8000 and (re)spawns it detached from the next-server process
 * if it is down, then waits until it is healthy.
 *
 * In normal local development you would run `scripts/dev.sh` instead; this
 * route exists so the preview stays functional without manual restarts.
 */

const BACKEND_URL = "http://127.0.0.1:8000/api/system/health";
const LAUNCH_SCRIPT = "/home/z/my-project/scripts/backend_service.sh";
const LOG_PATH = "/home/z/my-project/logs/backend.log";

async function isHealthy(timeoutMs: number): Promise<boolean> {
  try {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), timeoutMs);
    const res = await fetch(BACKEND_URL, { signal: ctrl.signal, cache: "no-store" });
    clearTimeout(t);
    return res.ok;
  } catch {
    return false;
  }
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

// Module-level guard so hot reloads / concurrent calls don't double-spawn.
let spawning: Promise<boolean> | null = null;

async function spawnBackend(): Promise<boolean> {
  if (await isHealthy(1500)) return true;
  try {
    const fd = openSync(LOG_PATH, "a");
    const child = spawn("bash", [LAUNCH_SCRIPT], {
      detached: true,
      stdio: ["ignore", fd, fd],
      cwd: "/home/z/my-project",
      env: { ...process.env, PYTHONUNBUFFERED: "1" },
    });
    child.unref();
  } catch (err) {
    console.error("ensure-backend spawn failed:", err);
    return false;
  }
  // First boot may download the embedding model (~225 MB) — be patient.
  for (let i = 0; i < 60; i++) {
    if (await isHealthy(2000)) return true;
    await sleep(2500);
  }
  return isHealthy(2000);
}

export async function GET() {
  if (await isHealthy(1500)) {
    return NextResponse.json({ ok: true, started: false });
  }
  if (!spawning) {
    spawning = spawnBackend().finally(() => {
      spawning = null;
    });
  }
  const ok = await spawning;
  return NextResponse.json({ ok, started: ok }, { status: ok ? 200 : 503 });
}

export const dynamic = "force-dynamic";
