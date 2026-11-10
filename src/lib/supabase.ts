import { createClient } from "@supabase/supabase-js";

export const SUPABASE_PROJECT_URL =
  import.meta.env.VITE_SUPABASE_URL || "https://fyrwiytzuxsebluygtjb.supabase.co";

export const SUPABASE_ANON_PUBLIC_KEY =
  import.meta.env.VITE_SUPABASE_ANON_KEY ||
  "sb_publishable_EyvpHQRMoLrGmstxquNbfw_txuKKrex";

export const sb = createClient(SUPABASE_PROJECT_URL, SUPABASE_ANON_PUBLIC_KEY);

