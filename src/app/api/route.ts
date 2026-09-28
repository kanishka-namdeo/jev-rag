import { NextResponse } from "next/server";

/** Tiny frontend liveness/info endpoint (the Python backend lives under /backend-api/*). */
export async function GET() {
  return NextResponse.json({
    app: "jev-rag",
    frontend: "ok",
    backendProxy: "/backend-api/*",
    docs: "/api/ensure-backend",
  });
}
