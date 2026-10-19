export async function apiRequest<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const response = await fetch(path, {
    ...options,
    cache: "no-store",
    headers: {
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...options.headers,
    },
  });

  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const body: { detail?: string } = await response.json();
      if (body.detail) detail = body.detail;
    } catch {
      // Keep the HTTP status as the visible error when the response isn't JSON.
    }
    throw new Error(detail);
  }

  return response.json() as Promise<T>;
}
