import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet.markercluster";
import type { Apartment, ThemeMode } from "../types/apartment";
import {
  escapeHtml,
  formatVoteEmoji,
  resolveCoordinates,
} from "../lib/formatters";

interface MapViewProps {
  isVisible: boolean;
  theme: ThemeMode;
  apartments: Apartment[];
  onJumpToApartment: (aptId: number) => void;
}

const CARTO_KEY = "cb1_51x1_1_2bcf3364a1a5671df78c167b";
const OSM_FALLBACK_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";

export function MapView({
  isVisible,
  theme,
  apartments,
  onJumpToApartment,
}: MapViewProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<L.Map | null>(null);
  const clusterRef = useRef<L.MarkerClusterGroup | null>(null);
  const tileLayerRef = useRef<L.TileLayer | null>(null);
  const jumpCallbackRef = useRef(onJumpToApartment);

  useEffect(() => {
    jumpCallbackRef.current = onJumpToApartment;
  }, [onJumpToApartment]);

  // Initialize Leaflet map and MarkerClusterGroup
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    const map = L.map(containerRef.current, {
      center: [60.19, 24.94],
      zoom: 12,
      zoomControl: true,
    });

    const cluster = L.markerClusterGroup({
      maxClusterRadius: 40,
      disableClusteringAtZoom: 15,
      spiderfyOnMaxZoom: true,
      showCoverageOnHover: false,
      zoomToBoundsOnClick: true,
    });

    map.addLayer(cluster);

    // Handle popup "Jump to Listing Card" button clicks safely in React
    const handlePopupOpen = (e: L.PopupEvent) => {
      const popupEl = e.popup.getElement();
      const btn = popupEl?.querySelector<HTMLButtonElement>(".popup-jump-btn");
      if (btn) {
        btn.onclick = () => {
          const aptId = Number(btn.dataset.aptId);
          if (!Number.isNaN(aptId)) {
            jumpCallbackRef.current(aptId);
          }
        };
      }
    };

    map.on("popupopen", handlePopupOpen);

    mapRef.current = map;
    clusterRef.current = cluster;

    return () => {
      map.off("popupopen", handlePopupOpen);
      map.remove();
      mapRef.current = null;
      clusterRef.current = null;
      tileLayerRef.current = null;
    };
  }, []);

  // Update CARTO basemap tiles on theme change with OSM fallback
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    if (tileLayerRef.current) {
      map.removeLayer(tileLayerRef.current);
    }

    const cartoUrl =
      theme === "dark"
        ? `https://basemaps.cartocdn.com/rastertiles/dark_all/{z}/{x}/{y}.png?key=${CARTO_KEY}`
        : `https://basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png?key=${CARTO_KEY}`;

    const layer = L.tileLayer(cartoUrl, {
      maxZoom: 20,
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
    });

    let hasFallenBack = false;
    layer.on("tileerror", () => {
      if (!hasFallenBack && mapRef.current && tileLayerRef.current) {
        hasFallenBack = true;
        mapRef.current.removeLayer(tileLayerRef.current);
        const osmLayer = L.tileLayer(OSM_FALLBACK_URL, {
          maxZoom: 19,
          attribution:
            '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
        }).addTo(mapRef.current);
        tileLayerRef.current = osmLayer;
      }
    });

    layer.addTo(map);
    tileLayerRef.current = layer;
  }, [theme]);

  // Update markers and invalidate size whenever visibility or apartments change
  useEffect(() => {
    const map = mapRef.current;
    const cluster = clusterRef.current;
    if (!map || !cluster) return;

    cluster.clearLayers();
    const bounds: [number, number][] = [];

    apartments.forEach((apt) => {
      const coords = resolveCoordinates(apt);
      if (!coords) return;

      bounds.push([coords.lat, coords.lon]);

      const isMatch = apt.is_mutual_match === true;
      let pinClass = "pin-interested";
      let iconContent = "🏠";

      if (isMatch) {
        pinClass = "pin-match";
        iconContent = "💚";
      } else if (apt.status?.startsWith("Applied")) {
        pinClass = "pin-applied";
        iconContent = "✓";
      } else if (apt.status?.startsWith("Viewing")) {
        pinClass = "pin-viewing";
        iconContent = "👁";
      } else if (apt.status?.startsWith("Not")) {
        pinClass = "pin-not";
        iconContent = "✕";
      }

      const customIcon = L.divIcon({
        className: `custom-pin ${pinClass}`,
        html: `<span>${iconContent}</span>`,
        iconSize: isMatch ? [34, 34] : [28, 28],
        iconAnchor: isMatch ? [17, 17] : [14, 14],
        popupAnchor: [0, -14],
      });

      const marker = L.marker([coords.lat, coords.lon], { icon: customIcon });
      const leoVote = formatVoteEmoji(apt.votes?.Leo);
      const ellaVote = formatVoteEmoji(apt.votes?.Ella);

      const popupHtml = `
        <div class="popup-card">
          ${
            isMatch
              ? '<div class="glass-badge mutual-glass-badge" style="font-size:0.75rem; padding:3px 8px; margin-bottom:4px;">💚 Mutual Match</div>'
              : ""
          }
          <div class="popup-title">${escapeHtml(apt.title)}</div>
          <div style="font-size: 0.8rem; color: var(--text-muted); margin-bottom: 4px;">📍 ${escapeHtml(
            apt.asuinalue
          )}</div>
          <div class="popup-specs">
            <span>${apt.price} €/kk</span> • <span>${apt.size_m2} m²</span> • <span>${apt.eur_per_m2} €/m²</span>
          </div>
          <div style="font-size: 0.78rem; margin: 6px 0; color: var(--text-secondary);">
            <div><strong>Status:</strong> ${escapeHtml(apt.status)}</div>
            <div><strong>Votes:</strong> Leo (${escapeHtml(
              leoVote
            )}) • Ella (${escapeHtml(ellaVote)})</div>
          </div>
          <button type="button" class="popup-jump-btn" data-apt-id="${apt.id}">
            Jump to Listing Card ↓
          </button>
        </div>
      `;

      marker.bindPopup(popupHtml);
      cluster.addLayer(marker);
    });

    if (isVisible) {
      const timer = window.setTimeout(() => {
        map.invalidateSize();
        if (bounds.length === 1) {
          map.setView(bounds[0], 14);
        } else if (bounds.length > 1) {
          map.fitBounds(bounds, { padding: [40, 40], maxZoom: 15 });
        }
      }, 200);
      return () => window.clearTimeout(timer);
    }
  }, [apartments, isVisible]);

  return (
    <section
      className={`map-section${isVisible ? " visible" : ""}`}
      id="map-section"
    >
      <div id="leaflet-map" ref={containerRef} />
      <div className="map-legend">
        <span className="legend-item">
          <span className="legend-dot dot-match" /> 💚 Mutual Match
        </span>
        <span className="legend-item">
          <span className="legend-dot dot-interested" /> Interested
        </span>
        <span className="legend-item">
          <span className="legend-dot dot-viewing" /> Viewing Booked
        </span>
        <span className="legend-item">
          <span className="legend-dot dot-applied" /> Applied
        </span>
        <span className="legend-item">
          <span className="legend-dot dot-not" /> Not Interested
        </span>
      </div>
    </section>
  );
}
