import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import type { User } from "@supabase/supabase-js";
import { sb } from "./lib/supabase";
import {
  castApartmentVote,
  deleteApartment,
  fetchApartments,
  saveManualApartment,
  scrapeApartment,
  UnauthorizedError,
} from "./lib/api";
import type {
  Apartment,
  ListingStatus,
  ManualApartmentPayload,
  SortOption,
  ThemeMode,
  VoteOption,
} from "./types/apartment";
import { DistrictRow } from "./components/DistrictRow";
import { MapView } from "./components/MapView";
import { CompareModal } from "./components/CompareModal";

interface ManualFormState {
  id?: number;
  url: string;
  imageUrl: string;
  title: string;
  asuinalue: string;
  status: ListingStatus | string;
  price: string;
  sizeM2: string;
  notes: string;
}

const EMPTY_MANUAL_FORM: ManualFormState = {
  url: "",
  imageUrl: "",
  title: "",
  asuinalue: "",
  status: "Interested",
  price: "",
  sizeM2: "",
  notes: "",
};

function getInitialTheme(): ThemeMode {
  const saved = localStorage.getItem("hat_theme");
  if (saved === "dark" || saved === "light") return saved;
  if (
    typeof window !== "undefined" &&
    window.matchMedia?.("(prefers-color-scheme: dark)").matches
  ) {
    return "dark";
  }
  return "light";
}

function parseUserIdentity(user: User | { email?: string; is_anonymous?: boolean } | null): {
  displayName: string;
  isVisitor: boolean;
} {
  const email = (user?.email || "").toLowerCase();
  if (email.includes("visitor") || user?.is_anonymous) {
    return { displayName: "Visitor", isVisitor: true };
  }
  if (email.includes("ella")) {
    return { displayName: "Ella", isVisitor: false };
  }
  return { displayName: "Leo", isVisitor: false };
}

export function App() {
  // Theme state
  const [theme, setTheme] = useState<ThemeMode>(getInitialTheme);

  // Auth state
  const [isAuthenticated, setIsAuthenticated] = useState<boolean>(false);
  const [authTab, setAuthTab] = useState<"login" | "visitor">("login");
  const [usernameInput, setUsernameInput] = useState("");
  const [passwordInput, setPasswordInput] = useState("");
  const [authMsg, setAuthMsg] = useState<{ text: string; color: string }>({
    text: "",
    color: "#f43f5e",
  });
  const [isSigningIn, setIsSigningIn] = useState(false);
  const [currentDisplayName, setCurrentDisplayName] = useState("Partner");
  const [isVisitor, setIsVisitor] = useState(false);

  // Apartments & UI state
  const [allApartments, setAllApartments] = useState<Apartment[]>([]);
  const [districtCounts, setDistrictCounts] = useState<Record<string, number>>(
    {}
  );
  const [activeDistrict, setActiveDistrict] = useState<string>("ALL");
  const [sortOption, setSortOption] = useState<SortOption>("price-false");
  const [openedDossiers, setOpenedDossiers] = useState<Set<number>>(
    () => new Set()
  );
  const [selectedForComparison, setSelectedForComparison] = useState<
    Set<number>
  >(() => new Set());
  const [isMapVisible, setIsMapVisible] = useState(false);
  const [highlightedApartmentId, setHighlightedApartmentId] = useState<
    number | null
  >(null);

  // Scrape quick-add state
  const [scrapeUrl, setScrapeUrl] = useState("");
  const [scrapeArea, setScrapeArea] = useState("");
  const [isScraping, setIsScraping] = useState(false);
  const [scrapeStatus, setScrapeStatus] = useState<{
    text: string;
    color: string;
  }>({ text: "", color: "var(--text-muted)" });

  // Modals state
  const [isCompareOpen, setIsCompareOpen] = useState(false);
  const [isManualModalOpen, setIsManualModalOpen] = useState(false);
  const [manualForm, setManualForm] =
    useState<ManualFormState>(EMPTY_MANUAL_FORM);
  const [manualStatusMsg, setManualStatusMsg] = useState("");

  // Sync theme to <html data-theme="..."> and localStorage
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("hat_theme", theme);
  }, [theme]);

  const loadApartments = useCallback(async () => {
    const [sortBy, descStr] = sortOption.split("-");
    try {
      const grouped = await fetchApartments(sortBy, descStr === "true");
      const flattened: Apartment[] = [];
      const counts: Record<string, number> = {};

      for (const [area, items] of Object.entries(grouped)) {
        counts[area] = items.length;
        flattened.push(...items);
      }

      setAllApartments(flattened);
      setDistrictCounts(counts);
    } catch (err) {
      if (err instanceof UnauthorizedError) {
        setIsAuthenticated(false);
      } else {
        console.error("Failed to load apartments:", err);
      }
    }
  }, [sortOption]);

  // Initial session check
  useEffect(() => {
    let active = true;
    sb.auth.getSession().then(({ data: { session } }) => {
      if (!active) return;
      if (session) {
        const identity = parseUserIdentity(session.user);
        setCurrentDisplayName(identity.displayName);
        setIsVisitor(identity.isVisitor);
        setIsAuthenticated(true);
      } else {
        setIsAuthenticated(false);
      }
    });

    const {
      data: { subscription },
    } = sb.auth.onAuthStateChange((_event, session) => {
      if (!active) return;
      if (session) {
        const identity = parseUserIdentity(session.user);
        setCurrentDisplayName(identity.displayName);
        setIsVisitor(identity.isVisitor);
        setIsAuthenticated(true);
      } else {
        setIsAuthenticated(false);
      }
    });

    return () => {
      active = false;
      subscription.unsubscribe();
    };
  }, []);

  // Load apartments and subscribe to Supabase Realtime when authenticated
  useEffect(() => {
    if (!isAuthenticated) return;

    loadApartments();

    const channel = sb
      .channel("apartments_realtime")
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "apartments" },
        () => loadApartments()
      )
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "apartment_votes" },
        () => loadApartments()
      )
      .subscribe();

    return () => {
      sb.removeChannel(channel);
    };
  }, [isAuthenticated, loadApartments]);

  // Global Escape key listener for modals
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setIsCompareOpen(false);
        setIsManualModalOpen(false);
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, []);

  // Computed Bento stats
  const bentoStats = useMemo(() => {
    const totalCount = allApartments.length;
    const districtCount = Object.keys(districtCounts).length;
    if (totalCount === 0) {
      return {
        totalCount: 0,
        districtCount: 0,
        avgRate: "0",
        diffText: "No data yet",
      };
    }

    const sumPrice = allApartments.reduce((acc, a) => acc + (a.price || 0), 0);
    const sumSize = allApartments.reduce(
      (acc, a) => acc + (a.size_m2 || 0),
      0
    );
    const avgVal = sumSize > 0 ? sumPrice / sumSize : 0;
    const avgRate = avgVal.toFixed(1);
    const diff = avgVal - 23.5;
    const diffText =
      diff <= 0
        ? `${Math.abs(diff).toFixed(1)} € below Hki avg`
        : `${diff.toFixed(1)} € above Hki avg`;

    return { totalCount, districtCount, avgRate, diffText };
  }, [allApartments, districtCounts]);

  const apartmentsById = useMemo(() => {
    const map = new Map<number, Apartment>();
    allApartments.forEach((a) => map.set(a.id, a));
    return map;
  }, [allApartments]);

  const comparedApartments = useMemo(
    () =>
      Array.from(selectedForComparison)
        .map((id) => apartmentsById.get(id))
        .filter((a): a is Apartment => Boolean(a)),
    [selectedForComparison, apartmentsById]
  );

  // Auth Handlers
  const handlePartnerSignIn = async (e?: FormEvent) => {
    e?.preventDefault();
    const raw = usernameInput.trim();
    if (!raw || !passwordInput) {
      setAuthMsg({
        text: "Please fill in email/username and password.",
        color: "#f43f5e",
      });
      return;
    }

    const email = raw.includes("@") ? raw : `${raw}@tracker.local`;
    setIsSigningIn(true);
    setAuthMsg({ text: "", color: "#f43f5e" });

    try {
      const { data, error } = await sb.auth.signInWithPassword({
        email,
        password: passwordInput,
      });
      if (error) {
        setAuthMsg({ text: error.message, color: "#f43f5e" });
        return;
      }
      const identity = parseUserIdentity(data.user);
      setCurrentDisplayName(identity.displayName);
      setIsVisitor(identity.isVisitor);
      setIsAuthenticated(true);
    } catch (err) {
      setAuthMsg({
        text:
          err instanceof Error
            ? err.message
            : "Failed to sign in. Please try again.",
        color: "#f43f5e",
      });
    } finally {
      setIsSigningIn(false);
    }
  };

  const handleVisitorAccess = async () => {
    setAuthMsg({
      text: "Connecting visitor session...",
      color: "var(--text-muted)",
    });

    try {
      const { error } = await sb.auth.signInWithPassword({
        email: "visitor@helsinki.local",
        password: "VisitorPassword123!",
      });

      if (error) {
        const { error: anonErr } = await sb.auth.signInAnonymously();
        if (anonErr) {
          setAuthMsg({
            text: `Visitor login error: ${error.message}`,
            color: "#f43f5e",
          });
          return;
        }
      }

      const { data: sessionData } = await sb.auth.getSession();
      const identity = parseUserIdentity(
        sessionData.session?.user ?? { email: "visitor@helsinki.local" }
      );
      setCurrentDisplayName(identity.displayName);
      setIsVisitor(identity.isVisitor);
      setIsAuthenticated(true);
    } catch (err) {
      setAuthMsg({
        text: `Visitor login error: ${
          err instanceof Error ? err.message : "Connection failed."
        }`,
        color: "#f43f5e",
      });
    }
  };

  const handleLogout = async () => {
    await sb.auth.signOut();
    setAllApartments([]);
    setDistrictCounts({});
    setIsAuthenticated(false);
  };

  // Apartment Actions
  const handleScrapeSubmit = async () => {
    if (isVisitor) {
      alert("Visitor account is read-only. Auto-fetching is disabled.");
      return;
    }
    const cleanUrl = scrapeUrl.trim();
    if (!cleanUrl) {
      setScrapeStatus({
        text: "Please paste a Vuokraovi link first.",
        color: "#f43f5e",
      });
      return;
    }

    setIsScraping(true);
    setScrapeStatus({
      text: "Scraping photos, extracting specs & geocoding via HSL...",
      color: "var(--text-muted)",
    });

    try {
      const data = await scrapeApartment({
        url: cleanUrl,
        fallback_asuinalue: scrapeArea.trim(),
      });
      setScrapeStatus({
        text: `Saved to ${data.asuinalue}! Plotted with image on map.`,
        color: "#10b981",
      });
      setScrapeUrl("");
      setScrapeArea("");
      await loadApartments();
    } catch (err) {
      setScrapeStatus({
        text:
          err instanceof Error ? err.message : "Scrape failed—use Manual.",
        color: "#f43f5e",
      });
    } finally {
      setIsScraping(false);
    }
  };

  const openNewManualModal = () => {
    if (isVisitor) {
      alert("Visitor account is read-only. Adding listings is disabled.");
      return;
    }
    setManualForm(EMPTY_MANUAL_FORM);
    setManualStatusMsg("");
    setIsManualModalOpen(true);
  };

  const openEditModal = (apt: Apartment) => {
    if (isVisitor) {
      alert("Visitor account is read-only. Editing is disabled.");
      return;
    }
    setManualForm({
      id: apt.id,
      url: apt.url || "",
      imageUrl: apt.image_url || apt.specs?.image_url || "",
      title: apt.title || "",
      asuinalue: apt.asuinalue || "",
      status: apt.status || "Interested",
      price: String(apt.price ?? ""),
      sizeM2: String(apt.size_m2 ?? ""),
      notes: apt.notes || "",
    });
    setManualStatusMsg("");
    setIsManualModalOpen(true);
  };

  const handleManualSubmit = async () => {
    if (isVisitor) {
      alert("Visitor account is read-only.");
      return;
    }

    const priceNum = parseFloat(manualForm.price);
    const sizeNum = parseFloat(manualForm.sizeM2);

    if (
      !manualForm.url.trim() ||
      !manualForm.title.trim() ||
      !manualForm.asuinalue.trim() ||
      Number.isNaN(priceNum) ||
      priceNum <= 0 ||
      Number.isNaN(sizeNum) ||
      sizeNum <= 0
    ) {
      setManualStatusMsg(
        "URL, Title, Area, Price, and Size are required (> 0)."
      );
      return;
    }

    const payload: ManualApartmentPayload = {
      url: manualForm.url.trim(),
      title: manualForm.title.trim(),
      asuinalue: manualForm.asuinalue.trim(),
      price: priceNum,
      size_m2: sizeNum,
      status: manualForm.status,
      notes: manualForm.notes.trim(),
      image_url: manualForm.imageUrl.trim(),
    };
    if (manualForm.id !== undefined) {
      payload.id = manualForm.id;
    }

    try {
      await saveManualApartment(payload);
      setIsManualModalOpen(false);
      await loadApartments();
    } catch (err) {
      setManualStatusMsg(
        err instanceof Error ? err.message : "Submission failed."
      );
    }
  };

  const handleVote = async (aptId: number, vote: VoteOption) => {
    if (isVisitor) {
      alert("Visitor account is read-only. Voting is reserved for Leo & Ella.");
      return;
    }
    await castApartmentVote(aptId, vote);
    await loadApartments();
  };

  const handleDelete = async (aptId: number) => {
    if (isVisitor) {
      alert("Visitor account is read-only. Deleting is disabled.");
      return;
    }
    if (!window.confirm("Are you sure you want to delete this apartment?")) {
      return;
    }
    await deleteApartment(aptId);
    setSelectedForComparison((prev) => {
      const next = new Set(prev);
      next.delete(aptId);
      return next;
    });
    setOpenedDossiers((prev) => {
      const next = new Set(prev);
      next.delete(aptId);
      return next;
    });
    await loadApartments();
  };

  const handleToggleDossier = (aptId: number) => {
    setOpenedDossiers((prev) => {
      const next = new Set(prev);
      if (next.has(aptId)) next.delete(aptId);
      else next.add(aptId);
      return next;
    });
  };

  const handleToggleCompare = (aptId: number, checked: boolean) => {
    setSelectedForComparison((prev) => {
      const next = new Set(prev);
      if (checked) {
        if (next.size >= 3) {
          alert(
            "You can select up to 3 apartments for side-by-side comparison."
          );
          return prev;
        }
        next.add(aptId);
      } else {
        next.delete(aptId);
      }
      return next;
    });
  };

  const handleClearComparison = () => {
    setSelectedForComparison(new Set());
    setIsCompareOpen(false);
  };

  const handleJumpToApartment = useCallback((aptId: number) => {
    const el = document.getElementById(`apt-card-${aptId}`);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "center" });
      setHighlightedApartmentId(aptId);
      window.setTimeout(() => {
        setHighlightedApartmentId((curr) => (curr === aptId ? null : curr));
      }, 2200);
    }
  }, []);

  return (
    <>
      <div className="container">
        {/* Top Navigation Bar */}
        <header className="navbar">
          <a href="#" className="nav-brand" onClick={(e) => e.preventDefault()}>
            <div className="brand-logo-icon">🏠</div>
            <div>
              <h1 className="brand-title">Helsinki Apartment Tracker</h1>
              <p className="brand-subtitle">
                Leo &amp; Ella&apos;s curated home search
              </p>
            </div>
          </a>

          <div className="nav-controls">
            <button
              type="button"
              id="map-toggle-btn"
              className={`btn-nav-action${isMapVisible ? " active" : ""}`}
              onClick={() => setIsMapVisible((v) => !v)}
            >
              🗺️ <span>{isMapVisible ? "Hide Map" : "Map View"}</span>
            </button>
            <button
              type="button"
              className="btn-nav-action"
              onClick={openNewManualModal}
            >
              ✏️ <span>Add Manual</span>
            </button>
            <div className="user-pill">
              <span className="user-dot" />
              <span>
                {isVisitor ? "Visitor (Read Only)" : currentDisplayName}
              </span>
            </div>
            <button
              type="button"
              className="theme-toggle-btn"
              onClick={() =>
                setTheme((t) => (t === "dark" ? "light" : "dark"))
              }
              title="Switch Light/Dark Mode"
            >
              {theme === "dark" ? "☀️" : "🌙"}
            </button>
            <button
              type="button"
              className="btn-nav-action"
              onClick={handleLogout}
              style={{ padding: "8px 12px", color: "var(--text-muted)" }}
            >
              Log out
            </button>
          </div>
        </header>

        {/* Bento-Style Hero Dashboard */}
        <section className="bento-hero">
          <div className="bento-card bento-card-main">
            <div>
              <h2 className="bento-hero-title">
                <span>✨</span> Track Any Vuokraovi Listing
              </h2>
              <p className="bento-hero-desc">
                Paste a link to automatically scrape photos, extract specs,
                geocode coordinates with HSL, and generate pros/cons.
              </p>
            </div>

            <div>
              <div className="quick-add-group">
                <div className="quick-input-wrap">
                  <span className="input-icon">🔗</span>
                  <input
                    type="url"
                    placeholder="https://www.vuokraovi.com/vuokra-asunto/..."
                    autoComplete="off"
                    value={scrapeUrl}
                    onChange={(e) => setScrapeUrl(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") handleScrapeSubmit();
                    }}
                  />
                </div>
                <input
                  type="text"
                  className="quick-area-input"
                  placeholder="Fallback district"
                  value={scrapeArea}
                  onChange={(e) => setScrapeArea(e.target.value)}
                />
                <button
                  type="button"
                  className="btn-glow-primary"
                  disabled={isScraping}
                  onClick={handleScrapeSubmit}
                >
                  {isScraping ? (
                    <span>Fetching...</span>
                  ) : (
                    <>
                      <span>Fetch Listing</span> <span>↗</span>
                    </>
                  )}
                </button>
                <button
                  type="button"
                  className="btn-manual-shortcut"
                  onClick={openNewManualModal}
                >
                  + Manual
                </button>
              </div>
              <div
                className="status-msg-banner"
                style={{ color: scrapeStatus.color }}
              >
                {scrapeStatus.text}
              </div>
            </div>
          </div>

          <div className="bento-card">
            <div className="stat-header">
              <span className="stat-label">Saved Listings</span>
              <div className="stat-icon">🏢</div>
            </div>
            <div>
              <p className="stat-value tabular-nums">{bentoStats.totalCount}</p>
              <div className="stat-footnote">
                Across {bentoStats.districtCount} Helsinki districts
              </div>
            </div>
          </div>

          <div className="bento-card">
            <div className="stat-header">
              <span className="stat-label">Average Rent</span>
              <div className="stat-icon">📈</div>
            </div>
            <div>
              <p className="stat-value tabular-nums">
                {bentoStats.avgRate}{" "}
                <span
                  style={{
                    fontSize: "1.1rem",
                    fontWeight: 600,
                    color: "var(--text-muted)",
                  }}
                >
                  €/m²
                </span>
              </p>
              <div className="stat-footnote">{bentoStats.diffText}</div>
            </div>
          </div>
        </section>

        {/* Interactive Leaflet Map */}
        <MapView
          isVisible={isMapVisible}
          theme={theme}
          apartments={allApartments}
          onJumpToApartment={handleJumpToApartment}
        />

        {/* District Filter Toolbar & 3-Column Card Grid */}
        <DistrictRow
          allApartments={allApartments}
          districtCounts={districtCounts}
          activeDistrict={activeDistrict}
          onSelectDistrict={setActiveDistrict}
          sortOption={sortOption}
          onChangeSort={setSortOption}
          currentDisplayName={currentDisplayName}
          isVisitor={isVisitor}
          openedDossiers={openedDossiers}
          selectedForComparison={selectedForComparison}
          highlightedApartmentId={highlightedApartmentId}
          onToggleDossier={handleToggleDossier}
          onToggleCompare={handleToggleCompare}
          onVote={handleVote}
          onEdit={openEditModal}
          onDelete={handleDelete}
        />
      </div>

      {/* Floating Comparison Dock */}
      <div
        className={`compare-dock${
          selectedForComparison.size >= 2 ? " visible" : ""
        }`}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <span className="dock-badge">
            {selectedForComparison.size} / 3
          </span>
          <span style={{ fontSize: "0.88rem", fontWeight: 700 }}>
            Apartments Selected
          </span>
        </div>
        <button
          type="button"
          className="btn-dock-compare"
          onClick={() => setIsCompareOpen(true)}
        >
          Compare Side-by-Side ↗
        </button>
        <button
          type="button"
          className="btn-dock-clear"
          onClick={handleClearComparison}
        >
          Clear
        </button>
      </div>

      {/* Side-by-Side Comparison Modal */}
      <CompareModal
        isOpen={isCompareOpen}
        apartments={comparedApartments}
        onClose={() => setIsCompareOpen(false)}
      />

      {/* Manual Entry / Edit Modal */}
      {isManualModalOpen && (
        <div
          className="modal-overlay open"
          onClick={(e) => {
            if (e.target === e.currentTarget) setIsManualModalOpen(false);
          }}
        >
          <div className="modal-card" style={{ maxWidth: "580px" }}>
            <div className="modal-header">
              <h3>
                {manualForm.id
                  ? `Edit: ${manualForm.title}`
                  : "Add Apartment Manually"}
              </h3>
              <button
                type="button"
                className="modal-close-btn"
                onClick={() => setIsManualModalOpen(false)}
              >
                &times;
              </button>
            </div>
            <div className="modal-body-scroll">
              <label className="modal-field-label">LISTING URL</label>
              <input
                type="url"
                className="modal-input"
                placeholder="https://www.vuokraovi.com/vuokra-asunto/..."
                value={manualForm.url}
                onChange={(e) =>
                  setManualForm((f) => ({ ...f, url: e.target.value }))
                }
              />

              <label className="modal-field-label">IMAGE URL (PHOTO)</label>
              <input
                type="url"
                className="modal-input"
                placeholder="https://images.vuokraovi.com/..."
                value={manualForm.imageUrl}
                onChange={(e) =>
                  setManualForm((f) => ({ ...f, imageUrl: e.target.value }))
                }
              />

              <label className="modal-field-label">
                TITLE / STREET ADDRESS
              </label>
              <input
                type="text"
                className="modal-input"
                placeholder="e.g. Taidemaalarinkatu 3"
                value={manualForm.title}
                onChange={(e) =>
                  setManualForm((f) => ({ ...f, title: e.target.value }))
                }
              />

              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "1fr 1fr",
                  gap: "10px",
                }}
              >
                <div>
                  <label className="modal-field-label">
                    DISTRICT (ASUINALUE)
                  </label>
                  <input
                    type="text"
                    className="modal-input"
                    placeholder="e.g. Kuninkaantammi"
                    value={manualForm.asuinalue}
                    onChange={(e) =>
                      setManualForm((f) => ({
                        ...f,
                        asuinalue: e.target.value,
                      }))
                    }
                  />
                </div>
                <div>
                  <label className="modal-field-label">STATUS</label>
                  <select
                    className="modal-input"
                    value={manualForm.status}
                    onChange={(e) =>
                      setManualForm((f) => ({ ...f, status: e.target.value }))
                    }
                  >
                    <option value="Interested">Interested</option>
                    <option value="Viewing booked">Viewing booked</option>
                    <option value="Applied">Applied</option>
                    <option value="Not interested">Not interested</option>
                  </select>
                </div>
              </div>

              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "1fr 1fr",
                  gap: "10px",
                }}
              >
                <div>
                  <label className="modal-field-label">PRICE (€/KK)</label>
                  <input
                    type="number"
                    className="modal-input"
                    placeholder="950"
                    value={manualForm.price}
                    onChange={(e) =>
                      setManualForm((f) => ({ ...f, price: e.target.value }))
                    }
                  />
                </div>
                <div>
                  <label className="modal-field-label">SIZE (M²)</label>
                  <input
                    type="number"
                    step="0.5"
                    className="modal-input"
                    placeholder="48.5"
                    value={manualForm.sizeM2}
                    onChange={(e) =>
                      setManualForm((f) => ({ ...f, sizeM2: e.target.value }))
                    }
                  />
                </div>
              </div>

              <label className="modal-field-label">NOTES / OBSERVATIONS</label>
              <textarea
                className="modal-input"
                style={{ minHeight: "80px", marginBottom: "16px" }}
                placeholder="Sunny top-floor balcony, looking to move in Dec..."
                value={manualForm.notes}
                onChange={(e) =>
                  setManualForm((f) => ({ ...f, notes: e.target.value }))
                }
              />

              <div style={{ display: "flex", gap: "10px" }}>
                <button
                  type="button"
                  className="btn-glow-primary"
                  style={{ flex: 1 }}
                  onClick={handleManualSubmit}
                >
                  {manualForm.id ? "Update Listing" : "Save Listing"}
                </button>
                <button
                  type="button"
                  className="btn-card-action"
                  onClick={() => setIsManualModalOpen(false)}
                >
                  Cancel
                </button>
              </div>
              {manualStatusMsg && (
                <div
                  style={{
                    fontSize: "0.85rem",
                    fontWeight: 600,
                    marginTop: "10px",
                    color: "#f43f5e",
                  }}
                >
                  {manualStatusMsg}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Auth Overlay */}
      {!isAuthenticated && (
        <div id="auth-overlay">
          <div className="auth-card">
            <div
              className="brand-logo-icon"
              style={{ margin: "0 auto 14px auto" }}
            >
              🏠
            </div>
            <h2>Helsinki Apartment Tracker</h2>
            <p>Log in to view and evaluate apartments with Leo &amp; Ella</p>

            <div className="auth-tabs">
              <button
                type="button"
                className={`auth-tab${authTab === "login" ? " active" : ""}`}
                onClick={() => {
                  setAuthTab("login");
                  setAuthMsg({ text: "", color: "#f43f5e" });
                }}
              >
                Partner Sign In
              </button>
              <button
                type="button"
                className={`auth-tab${authTab === "visitor" ? " active" : ""}`}
                onClick={() => {
                  setAuthTab("visitor");
                  setAuthMsg({ text: "", color: "#f43f5e" });
                }}
              >
                Visitor Access
              </button>
            </div>

            {authTab === "login" ? (
              <form onSubmit={handlePartnerSignIn}>
                <input
                  type="text"
                  placeholder="Username or email (leo / ella)"
                  autoComplete="username"
                  value={usernameInput}
                  onChange={(e) => setUsernameInput(e.target.value)}
                />
                <input
                  type="password"
                  placeholder="Password"
                  autoComplete="current-password"
                  value={passwordInput}
                  onChange={(e) => setPasswordInput(e.target.value)}
                />
                <button
                  type="submit"
                  className="btn-auth-submit"
                  disabled={isSigningIn}
                >
                  {isSigningIn ? "Signing in..." : "Sign In"}
                </button>
              </form>
            ) : (
              <div>
                <p
                  style={{
                    fontSize: "0.85rem",
                    color: "var(--text-secondary)",
                    marginBottom: "14px",
                  }}
                >
                  Explore all tracked Helsinki listings, view maps, and evaluate
                  district dossiers in read-only mode.
                </p>
                <button
                  type="button"
                  className="btn-auth-submit"
                  style={{
                    background: "#10b981",
                    boxShadow: "0 4px 14px rgba(16, 185, 129, 0.4)",
                  }}
                  onClick={handleVisitorAccess}
                >
                  Continue as Visitor 👁️
                </button>
                <div className="visitor-notice-pill">
                  🔒 Editing, adding, voting, and deleting listings are disabled
                  for visitor accounts.
                </div>
              </div>
            )}

            {authMsg.text && (
              <div
                style={{
                  marginTop: "14px",
                  fontSize: "0.85rem",
                  fontWeight: 600,
                  color: authMsg.color,
                }}
              >
                {authMsg.text}
              </div>
            )}
          </div>
        </div>
      )}
    </>
  );
}

export default App;
