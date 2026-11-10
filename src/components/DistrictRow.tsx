import type { Apartment, SortOption, VoteOption } from "../types/apartment";
import { ApartmentCard } from "./ApartmentCard";

interface DistrictRowProps {
  allApartments: Apartment[];
  districtCounts: Record<string, number>;
  activeDistrict: string;
  onSelectDistrict: (district: string) => void;
  sortOption: SortOption;
  onChangeSort: (option: SortOption) => void;
  currentDisplayName: string;
  isVisitor: boolean;
  openedDossiers: Set<number>;
  selectedForComparison: Set<number>;
  highlightedApartmentId: number | null;
  onToggleDossier: (id: number) => void;
  onToggleCompare: (id: number, checked: boolean) => void;
  onVote: (id: number, vote: VoteOption) => void;
  onEdit: (apartment: Apartment) => void;
  onDelete: (id: number) => void;
}

export function DistrictRow({
  allApartments,
  districtCounts,
  activeDistrict,
  onSelectDistrict,
  sortOption,
  onChangeSort,
  currentDisplayName,
  isVisitor,
  openedDossiers,
  selectedForComparison,
  highlightedApartmentId,
  onToggleDossier,
  onToggleCompare,
  onVote,
  onEdit,
  onDelete,
}: DistrictRowProps) {
  const filteredApartments =
    activeDistrict === "ALL"
      ? allApartments
      : allApartments.filter((apt) => apt.asuinalue === activeDistrict);

  return (
    <>
      {/* District Filter & Sorting Toolbar */}
      <div className="toolbar-wrapper">
        <div className="district-filter-bar">
          <button
            type="button"
            className={`filter-pill${activeDistrict === "ALL" ? " active" : ""}`}
            onClick={() => onSelectDistrict("ALL")}
          >
            All Districts ({allApartments.length})
          </button>

          {Object.entries(districtCounts).map(([area, count]) => (
            <button
              key={area}
              type="button"
              className={`filter-pill${activeDistrict === area ? " active" : ""}`}
              onClick={() => onSelectDistrict(area)}
            >
              {area} ({count})
            </button>
          ))}
        </div>

        <div className="toolbar-bottom">
          <span className="toolbar-stats-text">
            Showing {filteredApartments.length} of {allApartments.length} saved
            apartments
          </span>
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <label
              htmlFor="sort-select"
              style={{
                fontSize: "0.82rem",
                fontWeight: 700,
                color: "var(--text-muted)",
              }}
            >
              SORT BY:
            </label>
            <select
              id="sort-select"
              className="sort-select"
              value={sortOption}
              onChange={(e) => onChangeSort(e.target.value as SortOption)}
            >
              <option value="price-false">Price (Lowest first)</option>
              <option value="price-true">Price (Highest first)</option>
              <option value="size_m2-true">Size (Largest first)</option>
              <option value="size_m2-false">Size (Smallest first)</option>
              <option value="eur_per_m2-false">€/m² (Lowest first)</option>
            </select>
          </div>
        </div>
      </div>

      {/* Responsive 3-Column Card Grid */}
      <main className="cards-3col-grid">
        {filteredApartments.length === 0 ? (
          <div
            style={{
              gridColumn: "1 / -1",
              textAlign: "center",
              padding: "60px 20px",
              color: "var(--text-muted)",
            }}
          >
            <div style={{ fontSize: "2.5rem", marginBottom: "12px" }}>🏡</div>
            <h3 style={{ margin: "0 0 8px 0", color: "var(--text-primary)" }}>
              No apartments in this district
            </h3>
            <p style={{ margin: 0 }}>
              Paste a Vuokraovi link above to add your first apartment here.
            </p>
          </div>
        ) : (
          filteredApartments.map((apt) => (
            <ApartmentCard
              key={apt.id}
              apartment={apt}
              currentDisplayName={currentDisplayName}
              isVisitor={isVisitor}
              isDossierOpen={openedDossiers.has(apt.id)}
              isCompared={selectedForComparison.has(apt.id)}
              isHighlighted={highlightedApartmentId === apt.id}
              onToggleDossier={onToggleDossier}
              onToggleCompare={onToggleCompare}
              onVote={onVote}
              onEdit={onEdit}
              onDelete={onDelete}
            />
          ))
        )}
      </main>
    </>
  );
}

