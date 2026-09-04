/**
 * Transport map helpers — Leaflet + Nominatim/OSRM via Django APIs.
 * Expects window.TRANSPORT_MAP config from the template.
 */
(function () {
  function cfg() {
    return window.TRANSPORT_MAP || {
      geocodeUrl: "/transport/api/geocode/",
      routeUrl: "/transport/api/route/",
      defaultLat: 6.4584,
      defaultLng: 7.5464,
      defaultZoom: 12,
      csrfToken: "",
    };
  }

  function debounce(fn, ms) {
    let t;
    return function () {
      const args = arguments;
      clearTimeout(t);
      t = setTimeout(() => fn.apply(this, args), ms);
    };
  }

  function getCookie(name) {
    const m = document.cookie.match(new RegExp("(^| )" + name + "=([^;]+)"));
    return m ? m[2] : "";
  }

  async function geocode(q) {
    const c = cfg();
    const res = await fetch(c.geocodeUrl + "?q=" + encodeURIComponent(q), {
      headers: { Accept: "application/json", "X-Requested-With": "XMLHttpRequest" },
    });
    if (!res.ok) return [];
    const data = await res.json();
    return data.results || [];
  }

  async function route(points) {
    const c = cfg();
    const res = await fetch(c.routeUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        "X-CSRFToken": c.csrfToken || getCookie("csrftoken"),
        "X-Requested-With": "XMLHttpRequest",
      },
      body: JSON.stringify({ points }),
    });
    if (!res.ok) throw new Error("Route failed");
    return res.json();
  }

  function attachSuggest(input, onPick) {
    if (!input) return;
    const box = document.createElement("div");
    box.className = "transport-suggest list-group shadow-sm";
    box.style.cssText =
      "position:absolute;z-index:1050;max-height:220px;overflow:auto;display:none;width:100%;";
    const wrap = document.createElement("div");
    wrap.style.position = "relative";
    input.parentNode.insertBefore(wrap, input);
    wrap.appendChild(input);
    wrap.appendChild(box);

    const run = debounce(async () => {
      const q = input.value.trim();
      if (q.length < 3) {
        box.style.display = "none";
        return;
      }
      const results = await geocode(q);
      box.innerHTML = "";
      if (!results.length) {
        box.style.display = "none";
        return;
      }
      results.forEach((r) => {
        const a = document.createElement("button");
        a.type = "button";
        a.className = "list-group-item list-group-item-action small text-start";
        a.textContent = r.label;
        a.addEventListener("click", () => {
          input.value = r.label;
          box.style.display = "none";
          onPick(r);
        });
        box.appendChild(a);
      });
      box.style.display = "block";
    }, 350);

    input.addEventListener("input", run);
    input.addEventListener("blur", () => setTimeout(() => (box.style.display = "none"), 200));
  }

  function initRideMap(options) {
    const c = cfg();
    const mapEl = document.getElementById(options.mapId || "rideMap");
    if (!mapEl || typeof L === "undefined") return null;

    const map = L.map(mapEl).setView(
      [c.defaultLat, c.defaultLng],
      c.defaultZoom
    );
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: "&copy; OpenStreetMap",
    }).addTo(map);

    let originMarker = null;
    let destMarker = null;
    let routeLayer = null;
    const state = { origin: null, destination: null };

    function setMarker(kind, lat, lng, label) {
      const icon = L.divIcon({
        className: "",
        html:
          '<div style="background:' +
          (kind === "origin" ? "#0f766e" : "#c2410c") +
          ';color:#fff;border-radius:50%;width:28px;height:28px;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:700;border:2px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,.35)">' +
          (kind === "origin" ? "A" : "B") +
          "</div>",
        iconSize: [28, 28],
        iconAnchor: [14, 14],
      });
      if (kind === "origin") {
        if (originMarker) map.removeLayer(originMarker);
        originMarker = L.marker([lat, lng], { icon }).addTo(map).bindPopup(label || "Origin");
        state.origin = { lat, lng, label };
      } else {
        if (destMarker) map.removeLayer(destMarker);
        destMarker = L.marker([lat, lng], { icon }).addTo(map).bindPopup(label || "Destination");
        state.destination = { lat, lng, label };
      }
    }

    async function refreshRoute() {
      if (!state.origin || !state.destination) return;
      try {
        const data = await route([state.origin, state.destination]);
        if (options.distanceInput) options.distanceInput.value = data.distance_km;
        if (options.durationInput) options.durationInput.value = data.duration_min;
        if (options.geometryInput)
          options.geometryInput.value = JSON.stringify(data.geometry || {});
        if (options.providerInput) options.providerInput.value = data.provider || "";
        if (routeLayer) map.removeLayer(routeLayer);
        if (data.geometry && data.geometry.coordinates && data.geometry.coordinates.length) {
          const latlngs = data.geometry.coordinates.map((c) => [c[1], c[0]]);
          routeLayer = L.polyline(latlngs, { color: "#0f766e", weight: 4 }).addTo(map);
          map.fitBounds(routeLayer.getBounds(), { padding: [30, 30] });
        }
        if (options.statusEl) {
          options.statusEl.textContent =
            data.distance_km + " km · ~" + data.duration_min + " min (" + data.provider + ")";
        }
      } catch (e) {
        if (options.statusEl) options.statusEl.textContent = "Could not calculate route.";
      }
    }

    if (options.originInput) {
      attachSuggest(options.originInput, (r) => {
        if (options.originLat) options.originLat.value = r.lat;
        if (options.originLng) options.originLng.value = r.lng;
        setMarker("origin", r.lat, r.lng, r.label);
        refreshRoute();
      });
    }
    if (options.destInput) {
      attachSuggest(options.destInput, (r) => {
        if (options.destLat) options.destLat.value = r.lat;
        if (options.destLng) options.destLng.value = r.lng;
        setMarker("destination", r.lat, r.lng, r.label);
        refreshRoute();
      });
    }

    // Seed from hidden fields if present
    const olat = options.originLat && parseFloat(options.originLat.value);
    const olng = options.originLng && parseFloat(options.originLng.value);
    if (olat && olng) setMarker("origin", olat, olng, options.originInput && options.originInput.value);
    const dlat = options.destLat && parseFloat(options.destLat.value);
    const dlng = options.destLng && parseFloat(options.destLng.value);
    if (dlat && dlng) setMarker("destination", dlat, dlng, options.destInput && options.destInput.value);
    if (olat && olng && dlat && dlng) refreshRoute();

    setTimeout(() => map.invalidateSize(), 200);
    return { map, refreshRoute, setMarker, state };
  }

  function initReadOnlyRoute(mapId, geometry, markers) {
    const c = cfg();
    const mapEl = document.getElementById(mapId);
    if (!mapEl || typeof L === "undefined") return;
    const map = L.map(mapEl).setView([c.defaultLat, c.defaultLng], c.defaultZoom);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: "&copy; OpenStreetMap",
    }).addTo(map);
    const layers = [];
    (markers || []).forEach((m, i) => {
      if (m.lat == null || m.lng == null) return;
      const marker = L.marker([m.lat, m.lng]).addTo(map).bindPopup(m.label || ("Stop " + (i + 1)));
      layers.push(marker);
    });
    if (geometry && geometry.coordinates && geometry.coordinates.length) {
      const latlngs = geometry.coordinates.map((c) => [c[1], c[0]]);
      const line = L.polyline(latlngs, { color: "#0f766e", weight: 4 }).addTo(map);
      layers.push(line);
      map.fitBounds(line.getBounds(), { padding: [28, 28] });
    } else if (layers.length) {
      const group = L.featureGroup(layers);
      map.fitBounds(group.getBounds(), { padding: [28, 28] });
    }
    setTimeout(() => map.invalidateSize(), 200);
  }

  function initShuttleMap(options) {
    const c = cfg();
    const mapEl = document.getElementById(options.mapId || "shuttleMap");
    if (!mapEl || typeof L === "undefined") return;

    const map = L.map(mapEl).setView([c.defaultLat, c.defaultLng], c.defaultZoom);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: "&copy; OpenStreetMap",
    }).addTo(map);

    let origin = null;
    let routeLayer = null;
    const stopMarkers = [];

    function clearStops() {
      stopMarkers.forEach((m) => map.removeLayer(m));
      stopMarkers.length = 0;
    }

    async function refresh() {
      const points = [];
      if (origin) points.push(origin);
      document.querySelectorAll(".shuttle-passenger-row").forEach((row) => {
        if (row.querySelector('[name$="-DELETE"]')?.checked) return;
        const lat = parseFloat(row.querySelector(".shuttle-dest-lat")?.value || "");
        const lng = parseFloat(row.querySelector(".shuttle-dest-lng")?.value || "");
        const label = row.querySelector(".shuttle-destination")?.value || "";
        if (!isNaN(lat) && !isNaN(lng)) points.push({ lat, lng, label });
      });
      clearStops();
      points.slice(1).forEach((p, i) => {
        stopMarkers.push(
          L.marker([p.lat, p.lng]).addTo(map).bindPopup(p.label || "Stop " + (i + 1))
        );
      });
      if (points.length < 2) return;
      try {
        const data = await route(points);
        if (options.distanceInput) options.distanceInput.value = data.distance_km;
        if (options.durationInput) options.durationInput.value = data.duration_min;
        if (options.geometryInput)
          options.geometryInput.value = JSON.stringify(data.geometry || {});
        if (options.providerInput) options.providerInput.value = data.provider || "";
        if (routeLayer) map.removeLayer(routeLayer);
        if (data.geometry?.coordinates?.length) {
          const latlngs = data.geometry.coordinates.map((c) => [c[1], c[0]]);
          routeLayer = L.polyline(latlngs, { color: "#c2410c", weight: 4 }).addTo(map);
          map.fitBounds(routeLayer.getBounds(), { padding: [30, 30] });
        }
        if (options.statusEl) {
          options.statusEl.textContent =
            data.distance_km + " km · ~" + data.duration_min + " min · " + (points.length - 1) + " stop(s)";
        }
      } catch (e) {
        if (options.statusEl) options.statusEl.textContent = "Could not calculate route.";
      }
    }

    if (options.originInput) {
      attachSuggest(options.originInput, (r) => {
        if (options.originLat) options.originLat.value = r.lat;
        if (options.originLng) options.originLng.value = r.lng;
        origin = { lat: r.lat, lng: r.lng, label: r.label };
        if (window._shuttleOriginMarker) map.removeLayer(window._shuttleOriginMarker);
        window._shuttleOriginMarker = L.marker([r.lat, r.lng]).addTo(map).bindPopup("Origin");
        refresh();
      });
    }

    document.querySelectorAll(".shuttle-destination").forEach((input) => {
      if (input.dataset.bound) return;
      input.dataset.bound = "1";
      const row = input.closest(".shuttle-passenger-row");
      attachSuggest(input, (r) => {
        const lat = row.querySelector(".shuttle-dest-lat");
        const lng = row.querySelector(".shuttle-dest-lng");
        if (lat) lat.value = r.lat;
        if (lng) lng.value = r.lng;
        refresh();
      });
    });

    const addBtn = document.getElementById("addPassengerRow");
    if (addBtn) {
      addBtn.addEventListener("click", () => {
        setTimeout(() => {
          document.querySelectorAll(".shuttle-destination").forEach((input) => {
            if (input.dataset.bound) return;
            input.dataset.bound = "1";
            const row = input.closest(".shuttle-passenger-row");
            attachSuggest(input, (r) => {
              const lat = row.querySelector(".shuttle-dest-lat");
              const lng = row.querySelector(".shuttle-dest-lng");
              if (lat) lat.value = r.lat;
              if (lng) lng.value = r.lng;
              refresh();
            });
          });
        }, 50);
      });
    }

    setTimeout(() => map.invalidateSize(), 200);
    return { refresh };
  }

  window.TransportMap = {
    initRideMap,
    initReadOnlyRoute,
    initShuttleMap,
    geocode,
    route,
  };
})();
