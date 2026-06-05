import { NextRequest } from "next/server";

const BACKEND_BASE =
  process.env.VOKK_BACKEND_BASE || "http://127.0.0.1:8777";

async function proxy(req: NextRequest, path: string[]) {
  const url = new URL(`${BACKEND_BASE}/${path.join("/")}`);
  const incoming = new URL(req.url);
  incoming.searchParams.forEach((value, key) => url.searchParams.append(key, value));

  const headers = new Headers();
  const contentType = req.headers.get("content-type");
  const cookie = req.headers.get("cookie");
  if (contentType) headers.set("content-type", contentType);
  if (cookie) headers.set("cookie", cookie);

  const init: RequestInit = {
    method: req.method,
    headers,
    redirect: "manual",
  };

  if (req.method !== "GET" && req.method !== "HEAD") {
    init.body = await req.text();
  }

  const upstream = await fetch(url, init);
  const body = await upstream.arrayBuffer();

  const resHeaders = new Headers();
  const upstreamType = upstream.headers.get("content-type");
  if (upstreamType) resHeaders.set("content-type", upstreamType);
  const setCookie = upstream.headers.get("set-cookie");
  if (setCookie) resHeaders.append("set-cookie", setCookie);

  return new Response(body, {
    status: upstream.status,
    headers: resHeaders,
  });
}

type RouteContext = {
  params: Promise<{ path: string[] }>;
};

export async function GET(req: NextRequest, ctx: RouteContext) {
  return proxy(req, (await ctx.params).path);
}

export async function POST(req: NextRequest, ctx: RouteContext) {
  return proxy(req, (await ctx.params).path);
}
