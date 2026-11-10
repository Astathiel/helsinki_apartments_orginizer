import { sb } from "./supabase";
import type {
  GroupedApartments,
  ManualApartmentPayload,
  ScrapeApartmentPayload,
  VoteOption,
} from "../types/apartment";

export class UnauthorizedError extends Error {
  constructor(message = "Session expired or unauthorized.") {
    super(message);
    this.name = "UnauthorizedError";
  }
}

async function getAuthHeaders(): Promise<Record<string, string>> {
  const {
    data: { session },
  } = await sb.auth.getSession();
  const token = session?.access_token ?? "";
  return {
    "Content-Type": "application/json",
    Authorization: `Bearer ${token}`,
  };
}

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const headers = await getAuthHeaders();
  const res = await fetch(url, {
    ...init,
    headers: {
      ...headers,
      ...(init?.headers as Record<string, string> | undefined),
    },
  });

  if (res.status === 401) {
    throw new UnauthorizedError();
  }

  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = Array.isArray(data?.detail)
      ? data.detail[0]?.msg
      : data?.detail;
    throw new Error(detail || `Request failed with status ${res.status}`);
  }

  return data as T;
}

export function fetchApartments(
  sortBy: string,
  desc: boolean
): Promise<GroupedApartments> {
  return requestJson<GroupedApartments>(
    `/api/apartments?sort_by=${encodeURIComponent(sortBy)}&desc=${desc}`
  );
}

export function scrapeApartment(
  payload: ScrapeApartmentPayload
): Promise<{ status: string; asuinalue: string }> {
  return requestJson("/api/apartments/scrape", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function saveManualApartment(
  payload: ManualApartmentPayload
): Promise<{ status: string }> {
  return requestJson("/api/apartments/manual", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function castApartmentVote(
  apartmentId: number,
  vote: VoteOption
): Promise<unknown> {
  return requestJson("/api/apartments/vote", {
    method: "POST",
    body: JSON.stringify({ apartment_id: apartmentId, vote }),
  });
}

export function deleteApartment(apartmentId: number): Promise<unknown> {
  return requestJson(`/api/apartments/${apartmentId}`, {
    method: "DELETE",
  });
}
