export type VoteOption = "love" | "neutral" | "pass";

export type ListingStatus =
  | "Interested"
  | "Viewing booked"
  | "Applied"
  | "Not interested";

export type SortOption =
  | "price-false"
  | "price-true"
  | "size_m2-true"
  | "size_m2-false"
  | "eur_per_m2-false";

export type ThemeMode = "dark" | "light";

export interface ApartmentSpecs {
  floor?: number | null;
  total_floors?: number | null;
  floor_str?: string | null;
  has_elevator?: boolean | null;
  water_fee?: string | null;
  water_included?: boolean;
  pets_allowed?: boolean | "Sopimuksen mukaan" | string | null;
  has_balcony?: boolean | null;
  balcony_type?: string | null;
  has_sauna?: boolean | null;
  sauna_type?: string | null;
  condition?: string | null;
  year_built?: number | null;
  has_dishwasher?: boolean | null;
  has_washing_machine_hookup?: boolean | null;
  has_laundry_room?: boolean | null;
  has_walk_in_closet?: boolean | null;
  has_storage?: boolean | null;
  internet_included?: boolean | null;
  low_deposit?: boolean | null;
  free_immediately?: boolean | null;
  pros?: string[];
  cons?: string[];
  district_vibe?: string;
  image_url?: string;
  lat?: number | null;
  lon?: number | null;
}

export interface ApartmentVotes {
  Leo?: VoteOption;
  Ella?: VoteOption;
  [userName: string]: VoteOption | undefined;
}

export interface Apartment {
  id: number;
  url: string;
  title: string;
  asuinalue: string;
  price: number;
  size_m2: number;
  eur_per_m2: number;
  notes?: string;
  status: ListingStatus | string;
  added_by?: string;
  latitude?: number | null;
  longitude?: number | null;
  lat?: number | null;
  lon?: number | null;
  image_url?: string | null;
  votes?: ApartmentVotes;
  is_mutual_match?: boolean;
  specs?: ApartmentSpecs;
}

export type GroupedApartments = Record<string, Apartment[]>;

export interface ManualApartmentPayload {
  id?: number;
  url: string;
  title: string;
  asuinalue: string;
  price: number;
  size_m2: number;
  notes: string;
  status: string;
  image_url?: string;
}

export interface ScrapeApartmentPayload {
  url: string;
  fallback_asuinalue: string;
}

