import { useEffect, useState } from "react";
import type { Apartment, VoteOption } from "../types/apartment";
import {
  formatFloorBadge,
  formatVoteEmoji,
  getDistrictMeshStyle,
} from "../lib/formatters";

interface ApartmentCardProps {
  apartment: Apartment;
  currentDisplayName: string;
  isVisitor: boolean;
  isDossierOpen: boolean;
  isCompared: boolean;
  isHighlighted: boolean;
  onToggleDossier: (id: number) => void;
  onToggleCompare: (id: number, checked: boolean) => void;
  onVote: (id: number, vote: VoteOption) => void;
  onEdit: (apartment: Apartment) => void;
  onDelete: (id: number) => void;
}

const VOTE_BUTTONS: { vote: VoteOption; label: string; activeClass: string }[] =
  [
    { vote: "love", label: "💚 Love", activeClass: "active-love" },
    { vote: "neutral", label: "🟡 Neutral", activeClass: "active-neutral" },
    { vote: "pass", label: "🔴 Pass", activeClass: "active-pass" },
  ];

export function ApartmentCard({
  apartment,
  currentDisplayName,
  isVisitor,
  isDossierOpen,
  isCompared,
  isHighlighted,
  onToggleDossier,
  onToggleCompare,
  onVote,
  onEdit,
  onDelete,
}: ApartmentCardProps) {
  const imageUrl = apartment.image_url || apartment.specs?.image_url || "";
  const [imgFailed, setImgFailed] = useState(false);

  useEffect(() => {
    setImgFailed(false);
  }, [imageUrl]);

  const isMatch = apartment.is_mutual_match === true;
  const author = apartment.added_by || "Leo";
  const authorEmoji = author.toLowerCase() === "ella" ? "🌸" : "⚡";
  const statusPrefix = (apartment.status || "Interested").split(" ")[0];
  const statusClass = `status-${statusPrefix}`;

  const specs = apartment.specs || {};
  const pros = (specs.pros || []).filter(
    (p) => !p.includes("Viihtyisä ja vakiintunut helsinkiläinen asuinalue")
  );
  const cons = (specs.cons || []).filter(
    (c) => !c.toLowerCase().includes("vesimaksu")
  );

  const floorBadge = formatFloorBadge(specs);
  const elevatorBadge =
    specs.has_elevator === true
      ? "🛗 Hissi"
      : specs.has_elevator === false
      ? "Ei hissiä"
      : "🛗 -";
  const waterBadge = specs.water_included
    ? "💧 Vesi sisältyy"
    : specs.water_fee
    ? `💧 ${specs.water_fee}`
    : "💧 Vesi: -";
  const petsBadge =
    specs.pets_allowed === true
      ? "🐾 Lemmikit OK"
      : specs.pets_allowed === false
      ? "🚫 Ei lemmikkejä"
      : specs.pets_allowed
      ? `🐾 ${specs.pets_allowed}`
      : "🐾 -";
  const balconyBadge = specs.balcony_type
    ? `🌅 ${specs.balcony_type}`
    : specs.has_balcony
    ? "🌅 Parveke"
    : "Ei parveketta";
  const saunaBadge = specs.sauna_type
    ? `🧖 ${specs.sauna_type}`
    : specs.has_sauna
    ? "🧖 Oma sauna"
    : "Ei saunaa";

  const userVote = apartment.votes?.[currentDisplayName];
  const leoVote = formatVoteEmoji(apartment.votes?.Leo);
  const ellaVote = formatVoteEmoji(apartment.votes?.Ella);

  return (
    <article
      id={`apt-card-${apartment.id}`}
      className={`apartment-card${isMatch ? " mutual-match" : ""}${
        isHighlighted ? " highlighted-card" : ""
      }`}
    >
      {/* 16:9 Media Header */}
      <div className="card-media-wrapper">
        {imageUrl && !imgFailed ? (
          <img
            src={imageUrl}
            referrerPolicy="no-referrer"
            alt={apartment.title}
            className="card-photo"
            loading="lazy"
            onError={() => setImgFailed(true)}
          />
        ) : (
          <div
            className="media-placeholder"
            style={{ background: getDistrictMeshStyle(apartment.asuinalue) }}
          >
            <svg
              className="placeholder-icon"
              width="46"
              height="46"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <rect width="18" height="18" x="3" y="3" rx="2" />
              <path d="M3 9h18M9 21V9" />
            </svg>
          </div>
        )}

        <div className="media-overlay-top-left">
          {isMatch && (
            <div className="glass-badge mutual-glass-badge">
              <span>💚</span> Mutual Match!
            </div>
          )}
          <div className={`glass-badge status-pill ${statusClass}`}>
            {apartment.status}
          </div>
        </div>

        <div className="media-overlay-top-right">
          <label
            className="glass-badge compare-pill"
            title="Compare side-by-side"
          >
            <input
              type="checkbox"
              checked={isCompared}
              onChange={(e) => onToggleCompare(apartment.id, e.target.checked)}
            />
            <span>Compare</span>
          </label>
          <div className="glass-badge" style={{ fontSize: "0.72rem" }}>
            <span>{authorEmoji}</span> <span>{author}</span>
          </div>
        </div>

        <div className="media-overlay-bottom-left">
          <div
            className="glass-badge"
            style={{
              background: "rgba(0,0,0,0.65)",
              color: "#ffffff",
              borderColor: "rgba(255,255,255,0.2)",
            }}
          >
            📍 {apartment.asuinalue}
          </div>
        </div>
      </div>

      {/* Card Content */}
      <div className="card-body">
        <a
          href={apartment.url}
          target="_blank"
          rel="noreferrer"
          className="card-title-link"
          title={apartment.title}
        >
          {apartment.title} ↗
        </a>

        <div className="metric-bar tabular-nums">
          <div className="metric-item">
            <span className="metric-label">Rent</span>
            <span className="metric-value price">
              {apartment.price.toLocaleString("fi-FI")} €
            </span>
          </div>
          <div className="metric-item">
            <span className="metric-label">Size</span>
            <span className="metric-value">{apartment.size_m2} m²</span>
          </div>
          <div className="metric-item">
            <span className="metric-label">Rate</span>
            <span className="metric-value">{apartment.eur_per_m2} €/m²</span>
          </div>
        </div>

        {apartment.notes && (
          <div className="notes-box">📝 {apartment.notes}</div>
        )}

        {/* Voting Section */}
        {isVisitor ? (
          <div className="vote-section">
            <div className="vote-header">
              <span>Partner Votes</span>
              <div className="vote-status-summary">
                <span>Leo: {leoVote}</span>
                <span>•</span>
                <span>Ella: {ellaVote}</span>
              </div>
            </div>
            <div
              style={{
                fontSize: "0.72rem",
                color: "var(--text-muted)",
                textAlign: "center",
                fontStyle: "italic",
              }}
            >
              Voting reserved for Leo & Ella
            </div>
          </div>
        ) : (
          <div className="vote-section">
            <div className="vote-header">
              <span>Your Vote:</span>
              <div className="vote-status-summary">
                <span>Leo: {leoVote}</span>
                <span>•</span>
                <span>Ella: {ellaVote}</span>
              </div>
            </div>
            <div className="vote-btn-row">
              {VOTE_BUTTONS.map(({ vote, label, activeClass }) => (
                <button
                  key={vote}
                  type="button"
                  className={`vote-btn btn-vote-${vote}${
                    userVote === vote ? ` ${activeClass}` : ""
                  }`}
                  onClick={() => onVote(apartment.id, vote)}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Dossier & Evaluation Accordion */}
        <div className="dossier-box">
          <button
            type="button"
            className="dossier-header-btn"
            onClick={() => onToggleDossier(apartment.id)}
          >
            <span>🧠 Dossier &amp; Evaluation</span>
            <div className="dossier-counts">
              <span className="dossier-badge-pro">+{pros.length}</span>
              <span className="dossier-badge-con">-{cons.length}</span>
              <span
                className={`dossier-arrow${isDossierOpen ? " open" : ""}`}
              >
                ▼
              </span>
            </div>
          </button>

          <div className={`dossier-body${isDossierOpen ? " open" : ""}`}>
            {specs.district_vibe && (
              <div className="dossier-vibe">📍 {specs.district_vibe}</div>
            )}

            <div className="spec-pills-grid">
              <span className="spec-pill">{floorBadge}</span>
              <span className="spec-pill">{elevatorBadge}</span>
              <span className="spec-pill">{waterBadge}</span>
              <span className="spec-pill">{petsBadge}</span>
              <span className="spec-pill">{balconyBadge}</span>
              <span className="spec-pill">{saunaBadge}</span>
              {specs.year_built && (
                <span className="spec-pill">🏗️ {specs.year_built}</span>
              )}
              {specs.condition && (
                <span className="spec-pill">✨ {specs.condition}</span>
              )}
              {specs.has_dishwasher === true && (
                <span className="spec-pill">🍽️ Astianpesukone</span>
              )}
              {specs.has_washing_machine_hookup === true && (
                <span className="spec-pill">🧺 Pesukoneliitäntä</span>
              )}
              {specs.has_walk_in_closet === true && (
                <span className="spec-pill">👗 Vaatehuone</span>
              )}
              {specs.internet_included === true && (
                <span className="spec-pill">🌐 Laajakaista</span>
              )}
            </div>

            {pros.length > 0 && (
              <div style={{ marginBottom: "8px" }}>
                <div
                  style={{
                    fontSize: "0.72rem",
                    fontWeight: 800,
                    color: "#10b981",
                    marginBottom: "4px",
                  }}
                >
                  PROS ({pros.length})
                </div>
                <ul className="eval-list">
                  {pros.map((pro, idx) => (
                    <li key={idx} className="eval-item pro">
                      <span>+</span>
                      <span>{pro}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {cons.length > 0 && (
              <div>
                <div
                  style={{
                    fontSize: "0.72rem",
                    fontWeight: 800,
                    color: "#f43f5e",
                    marginBottom: "4px",
                  }}
                >
                  CONS &amp; CONSIDERATIONS ({cons.length})
                </div>
                <ul className="eval-list">
                  {cons.map((con, idx) => (
                    <li key={idx} className="eval-item con">
                      <span>-</span>
                      <span>{con}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </div>

        {/* Action Buttons */}
        {!isVisitor && (
          <div className="card-actions-row">
            <button
              type="button"
              className="btn-card-action"
              onClick={() => onEdit(apartment)}
            >
              ✏️ Edit
            </button>
            <button
              type="button"
              className="btn-card-action danger"
              onClick={() => onDelete(apartment.id)}
            >
              🗑️ Delete
            </button>
          </div>
        )}
      </div>
    </article>
  );
}
