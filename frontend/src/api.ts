export type InstrumentDescription = {
  category: string;
  brand: string;
  model: string;
  year: string | null;
  condition: string;
  materials: string[];
  features: string[];
  notes: string;
};

export type ValuationResult = {
  price_jpy: number;
  range_jpy: [number, number];
  confidence: number;
  rationale: string;
  evidence: string[];
};

export type StreamPhase = "vision" | "rag";

export type StreamEvent =
  | {
      type: "step";
      phase: StreamPhase;
      index: number;
      status: "start" | "done";
    }
  | {
      type: "log";
      code: string;
      meta?: Record<string, number | string>;
    }
  | {
      type: "result";
      phase: StreamPhase;
      payload: InstrumentDescription | ValuationResult;
    }
  | {
      type: "error";
      message: string;
    };

async function handleJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || "API error");
  }
  return response.json() as Promise<T>;
}

export async function describeInstrument(file: File): Promise<InstrumentDescription> {
  const form = new FormData();
  form.append("image", file);

  const response = await fetch("/api/describe", {
    method: "POST",
    body: form,
  });

  return handleJson<InstrumentDescription>(response);
}

export async function estimateValue(
  description: InstrumentDescription,
): Promise<ValuationResult> {
  const response = await fetch("/api/estimate", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(description),
  });

  return handleJson<ValuationResult>(response);
}

function parseSseChunk(
  chunk: string,
  onEvent: (event: StreamEvent) => void,
) {
  const lines = chunk.split("\n");
  let eventName = "message";
  const dataLines: string[] = [];

  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) {
      continue;
    }
    if (trimmed.startsWith("event:")) {
      eventName = trimmed.slice(6).trim();
      continue;
    }
    if (trimmed.startsWith("data:")) {
      dataLines.push(trimmed.slice(5).trim());
    }
  }

  if (!dataLines.length) {
    return;
  }

  let data: unknown = null;
  try {
    data = JSON.parse(dataLines.join("\n"));
  } catch {
    return;
  }

  if (!data || typeof data !== "object") {
    return;
  }

  if (eventName === "step") {
    const payload = data as {
      phase: StreamPhase;
      index: number;
      status: "start" | "done";
    };
    onEvent({ type: "step", ...payload });
    return;
  }

  if (eventName === "log") {
    const payload = data as { code: string; meta?: Record<string, number | string> };
    onEvent({ type: "log", ...payload });
    return;
  }

  if (eventName === "result") {
    const payload = data as {
      phase: StreamPhase;
      payload: InstrumentDescription | ValuationResult;
    };
    onEvent({ type: "result", ...payload });
    return;
  }

  if (eventName === "error") {
    const message =
      typeof (data as { message?: unknown }).message === "string"
        ? (data as { message: string }).message
        : "Stream error";
    onEvent({ type: "error", message });
  }
}

async function streamSse(
  url: string,
  init: RequestInit,
  onEvent: (event: StreamEvent) => void,
) {
  const response = await fetch(url, {
    ...init,
    headers: {
      Accept: "text/event-stream",
      ...(init.headers ?? {}),
    },
  });

  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || "Stream request failed");
  }

  const reader = response.body?.getReader();
  if (!reader) {
    throw new Error("Stream is not available");
  }

  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) {
      break;
    }
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() ?? "";
    for (const part of parts) {
      parseSseChunk(part, onEvent);
    }
  }

  if (buffer.trim()) {
    parseSseChunk(buffer, onEvent);
  }
}

export async function streamDescribe(
  file: File,
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const form = new FormData();
  form.append("image", file);

  await streamSse(
    "/api/describe/stream",
    {
      method: "POST",
      body: form,
      signal,
    },
    onEvent,
  );
}

export async function streamEstimate(
  description: InstrumentDescription,
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  await streamSse(
    "/api/estimate/stream",
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(description),
      signal,
    },
    onEvent,
  );
}
