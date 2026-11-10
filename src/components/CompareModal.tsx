import { useState, type ReactNode } from "react";
import type { Apartment } from "../types/apartment";
import { formatVoteEmoji } from "../lib/formatters";

interface CompareModalProps {
  isOpen: boolean;
  apartments: Apartment[];
  onClose: () => void;
}

interface CompareRowSpec {
  label: string;
  render: (apt: Apartment) => ReactNode;
  isDifferent: () => boolean;
}

export function CompareModal({
  isOpen,
  apartments,
  onClose,
}: CompareModalProps) {
  const [showDiffsOnly, setShowDiffsOnly] = useState(false);

  if (!isOpen) return null;

  const prices = apartments.map((a) => a.price);
  const minPrice = prices.length > 0 ? Math.min(...prices) : 0;
  const eurPerM2s = apartments.map((a) => a.eur_per_m2);
  const minEurPerM2 = eurPerM2s.length > 0 ? Math.min(...eurPerM2s) : 0;

  const rows: CompareRowSpec[] = [
    {
      label: "Price (€/kk)",
      render: (a) => {
        const isLowest = a.price === minPrice;
        const delta = a.price - minPrice;
        const deltaPct =
          minPrice > 0 ? ((delta / minPrice) * 100).toFixed(1) : "0";
        return (
          <>
            <strong>{a.price.toLocaleString("fi-FI")} €/kk</strong>
            <br />
            {isLowest ? (
              <span className="delta-tag lowest">Lowest Price</span>
            ) : (
              <span className="delta-tag higher">
                +{delta.toLocaleString("fi-FI")} € (+{deltaPct}%)
              </span>
            )}
          </>
        );
      },
      isDifferent: () => new Set(apartments.map((a) => a.price)).size > 1,
    },
    {
      label: "Price per m²",
      render: (a) => {
        const isLowest = a.eur_per_m2 === minEurPerM2;
        const delta = (a.eur_per_m2 - minEurPerM2).toFixed(1);
        const deltaPct =
          minEurPerM2 > 0
            ? (((a.eur_per_m2 - minEurPerM2) / minEurPerM2) * 100).toFixed(1)
            : "0";
        return (
          <>
            <strong>{a.eur_per_m2} €/m²</strong>
            <br />
            {isLowest ? (
              <span className="delta-tag lowest">Lowest €/m²</span>
            ) : (
              <span className="delta-tag higher">
                +{delta} €/m² (+{deltaPct}%)
              </span>
            )}
          </>
        );
      },
      isDifferent: () => new Set(apartments.map((a) => a.eur_per_m2)).size > 1,
    },
    {
      label: "Size (m²)",
      render: (a) => <strong>{a.size_m2} m²</strong>,
      isDifferent: () => new Set(apartments.map((a) => a.size_m2)).size > 1,
    },
    {
      label: "Floor & Elevator",
      render: (a) => {
        const s = a.specs || {};
        const floorStr = s.floor_str ? `Kerros ${s.floor_str}` : "Kerros -";
        const elStr =
          s.has_elevator === true
            ? "🛗 Hissi"
            : s.has_elevator === false
            ? "Ei hissiä"
            : "";
        return (
          <>
            <div>{floorStr}</div>
            <div>{elStr}</div>
          </>
        );
      },
      isDifferent: () =>
        new Set(
          apartments.map(
            (a) => `${a.specs?.floor_str || ""}-${a.specs?.has_elevator}`
          )
        ).size > 1,
    },
    {
      label: "Water & Utilities",
      render: (a) => {
        const s = a.specs || {};
        if (s.water_included) {
          return (
            <span style={{ color: "#10b981", fontWeight: 700 }}>
              💧 Vesi sisältyy
            </span>
          );
        }
        return s.water_fee ? `💧 ${s.water_fee}` : "💧 Ei tietoa";
      },
      isDifferent: () =>
        new Set(
          apartments.map((a) =>
            a.specs?.water_included ? "inc" : a.specs?.water_fee || ""
          )
        ).size > 1,
    },
    {
      label: "Balcony & Sauna",
      render: (a) => {
        const s = a.specs || {};
        const balcony =
          s.balcony_type || (s.has_balcony ? "Parveke" : "Ei parveketta");
        const sauna = s.sauna_type || (s.has_sauna ? "Oma sauna" : "Ei saunaa");
        return (
          <>
            <div>{balcony}</div>
            <div>{sauna}</div>
          </>
        );
      },
      isDifferent: () =>
        new Set(
          apartments.map(
            (a) => `${a.specs?.balcony_type}-${a.specs?.sauna_type}`
          )
        ).size > 1,
    },
    {
      label: "Pet Policy",
      render: (a) => {
        const s = a.specs || {};
        if (s.pets_allowed === true) return "🐾 Lemmikit sallittu";
        if (s.pets_allowed === false) return "🚫 Ei lemmikkejä";
        return "🐾 Sopimuksen mukaan";
      },
      isDifferent: () =>
        new Set(apartments.map((a) => `${a.specs?.pets_allowed}`)).size > 1,
    },
    {
      label: "Partner Votes",
      render: (a) => {
        const leo = formatVoteEmoji(a.votes?.Leo);
        const ella = formatVoteEmoji(a.votes?.Ella);
        return (
          <>
            <div>
              Leo: <strong>{leo}</strong>
            </div>
            <div>
              Ella: <strong>{ella}</strong>
            </div>
            {a.is_mutual_match && (
              <div
                className="glass-badge mutual-glass-badge"
                style={{ marginTop: "6px", fontSize: "0.72rem" }}
              >
                💚 Mutual Match
              </div>
            )}
          </>
        );
      },
      isDifferent: () =>
        new Set(
          apartments.map(
            (a) => `${a.votes?.Leo || ""}-${a.votes?.Ella || ""}`
          )
        ).size > 1,
    },
    {
      label: "Dossier Pros & Cons",
      render: (a) => {
        const s = a.specs || {};
        const p = (s.pros || []).length;
        const c = (s.cons || []).length;
        return (
          <>
            <div style={{ fontWeight: 700 }}>
              +{p} Pros / -{c} Cons
            </div>
            <div
              style={{
                fontSize: "0.75rem",
                color: "var(--text-muted)",
                marginTop: "4px",
              }}
            >
              {s.district_vibe || ""}
            </div>
          </>
        );
      },
      isDifferent: () =>
        new Set(
          apartments.map(
            (a) =>
              `${(a.specs?.pros || []).length}-${(a.specs?.cons || []).length}`
          )
        ).size > 1,
    },
  ];

  return (
    <div
      className="modal-overlay open"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="modal-card">
        <div className="modal-header">
          <div style={{ display: "flex", alignItems: "center", gap: "14px" }}>
            <h3>Side-by-Side Apartment Comparison</h3>
            <label
              style={{
                display: "flex",
                alignItems: "center",
                gap: "6px",
                fontSize: "0.82rem",
                fontWeight: 700,
                cursor: "pointer",
                color: "var(--text-secondary)",
              }}
            >
              <input
                type="checkbox"
                checked={showDiffsOnly}
                onChange={(e) => setShowDiffsOnly(e.target.checked)}
              />
              Highlight Differences Only
            </label>
          </div>
          <button type="button" className="modal-close-btn" onClick={onClose}>
            &times;
          </button>
        </div>

        <div className="modal-body-scroll">
          {apartments.length < 2 ? (
            <p style={{ textAlign: "center", color: "var(--text-muted)" }}>
              Please select at least 2 apartments to compare.
            </p>
          ) : (
            <table className="comparison-table">
              <thead>
                <tr>
                  <th
                    style={{
                      width: "170px",
                      background: "var(--bg-surface-elevated)",
                    }}
                  >
                    Feature
                  </th>
                  {apartments.map((a) => (
                    <th
                      key={a.id}
                      style={{ background: "var(--bg-surface-elevated)" }}
                    >
                      {a.is_mutual_match && (
                        <div
                          className="glass-badge mutual-glass-badge"
                          style={{ marginBottom: "6px" }}
                        >
                          💚 Mutual Match
                        </div>
                      )}
                      <a
                        href={a.url}
                        target="_blank"
                        rel="noreferrer"
                        style={{
                          fontSize: "1rem",
                          color: "var(--text-primary)",
                          textDecoration: "none",
                          fontWeight: 700,
                          display: "block",
                          marginBottom: "4px",
                        }}
                      >
                        {a.title} ↗
                      </a>
                      <span
                        style={{
                          fontSize: "0.8rem",
                          color: "var(--text-muted)",
                          fontWeight: 600,
                        }}
                      >
                        📍 {a.asuinalue}
                      </span>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows
                  .filter((row) => !showDiffsOnly || row.isDifferent())
                  .map((row) => (
                    <tr key={row.label}>
                      <td
                        style={{
                          fontWeight: 700,
                          background: "var(--modal-header-bg)",
                        }}
                      >
                        {row.label}
                      </td>
                      {apartments.map((a) => (
                        <td key={a.id}>{row.render(a)}</td>
                      ))}
                    </tr>
                  ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}

