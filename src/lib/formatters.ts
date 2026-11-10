import type { Apartment, ApartmentSpecs, VoteOption } from "../types/apartment";

const MESH_GRADIENTS = [
  "radial-gradient(circle at 85% 15%, #4338ca 0%, transparent 60%), radial-gradient(circle at 15% 85%, #06b6d4 0%, transparent 60%), #1e1b4b",
  "radial-gradient(circle at 85% 15%, #065f46 0%, transparent 60%), radial-gradient(circle at 15% 85%, #10b981 0%, transparent 60%), #022c22",
  "radial-gradient(circle at 85% 15%, #6b21a8 0%, transparent 60%), radial-gradient(circle at 15% 85%, #ec4899 0%, transparent 60%), #3b0764",
  "radial-gradient(circle at 85% 15%, #9a3412 0%, transparent 60%), radial-gradient(circle at 15% 85%, #f59e0b 0%, transparent 60%), #451a03",
  "radial-gradient(circle at 85% 15%, #1e40af 0%, transparent 60%), radial-gradient(circle at 15% 85%, #3b82f6 0%, transparent 60%), #0f172a",
];

export function getDistrictMeshStyle(district: string): string {
  let hash = 0;
  for (let i = 0; i < (district || "").length; i++) {
    hash = district.charCodeAt(i) + ((hash << 5) - hash);
  }
  return MESH_GRADIENTS[Math.abs(hash) % MESH_GRADIENTS.length];
}

export function formatVoteEmoji(vote?: VoteOption | string): string {
  if (vote === "love") return "💚 Love";
  if (vote === "neutral") return "🟡 Neutral";
  if (vote === "pass") return "🔴 Pass";
  return "⏳ None";
}

export function formatFloorBadge(specs?: ApartmentSpecs): string {
  if (!specs) return "🏢 Kerros: -";
  if (specs.floor_str) {
    if (specs.floor && (specs.floor > 50 || specs.floor < 1)) {
      return "🏢 Kerros: -";
    }
    if (/^\d{3,}/.test(specs.floor_str)) {
      return "🏢 Kerros: -";
    }
    return `🏢 ${specs.floor_str} krs`;
  }
  if (specs.floor && specs.floor >= 1 && specs.floor <= 50) {
    return specs.total_floors
      ? `🏢 ${specs.floor}/${specs.total_floors} krs`
      : `🏢 ${specs.floor}. krs`;
  }
  return "🏢 Kerros: -";
}

export function resolveCoordinates(
  apt: Apartment
): { lat: number; lon: number } | null {
  const rawLat = apt.latitude ?? apt.specs?.lat ?? apt.lat;
  const rawLon = apt.longitude ?? apt.specs?.lon ?? apt.lon;
  if (rawLat == null || rawLon == null) return null;
  const lat = Number(rawLat);
  const lon = Number(rawLon);
  if (Number.isNaN(lat) || Number.isNaN(lon) || lat === 0 || lon === 0) {
    return null;
  }
  return { lat, lon };
}

export function escapeHtml(str: unknown): string {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}
