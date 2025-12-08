import { fail } from "@sveltejs/kit";
import type { Actions } from "./$types";
import { env } from "$env/dynamic/private";

export const config = {
  bodySizeLimit: "500mb",
};

const API_BASE = env.API_URL || "http://localhost:8100";

export const actions = {
  default: async ({ request, locals, fetch }) => {
    const formData = await request.formData();
    const file = formData.get("file");
    const source = formData.get("source") as string;

    if (!file || !(file instanceof File) || file.size === 0) {
      return fail(400, { error: "No valid file uploaded" });
    }

    if (!locals.backendToken) {
      return fail(401, { error: "Unauthorized: No backend token available" });
    }

    try {
      // Construct FormData for the backend request
      const backendFormData = new FormData();
      backendFormData.append("file", file);
      backendFormData.append("source", source || "auto");

      // Send to FastAPI backend
      // Note: We use the event.fetch wrapper which could handle auth,
      // but we pass headers explicitly to be safe regarding boundaries/content-type.
      // Actually, letting fetch handle content-type for FormData is usually best.
      const res = await fetch(`${API_BASE}/ingest/upload`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${locals.backendToken}`,
        },
        body: backendFormData,
      });

      if (!res.ok) {
        const errorText = await res.text();
        let errorDetail = errorText;
        try {
          const json = JSON.parse(errorText);
          if (json.detail) errorDetail = json.detail;
        } catch {
          // ignore json parse error
        }
        return fail(res.status, { error: `Ingestion failed: ${errorDetail}` });
      }

      const result = await res.json();
      return {
        success: true,
        message: result.message ?? "Ingestion started successfully.",
      };
    } catch (err) {
      console.error("Upload action error:", err);
      return fail(500, {
        error: "Internal server error while contacting ingestion service.",
      });
    }
  },
} satisfies Actions;
