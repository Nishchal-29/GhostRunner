/* GhostRunner Client Application */

// --- Global Application State ---
const state = {
  lat: 40.7580,
  lon: -73.9855,
  locationName: "Times Square, NYC",
  genre: "cyberpunk",
  distanceM: 2500,
  sessionId: null,
  route: null,
  stats: null,
  ws: null,
  isPaused: false,
  simSpeed: 1.0,
  audioMuted: false,
  lastDialogue: null,
  commsLog: [],
  map: null,
  routeLayer: null,
  runnerMarker: null,
  landmarkLayers: [],
  maneuverLayers: [],
  isSpeaking: false
};

// --- Web Audio API Radio Sound Effects ---
class TacticalRadioAudio {
  constructor() {
    this.ctx = null;
    this.audioEl = document.getElementById('audioPlayer');
  }

  initContext() {
    if (!this.ctx) {
      const AudioContext = window.AudioContext || window.webkitAudioContext;
      this.ctx = new AudioContext();
    }
    if (this.ctx.state === 'suspended') {
      this.ctx.resume();
    }
  }

  // Tactical radio squelch / chirp beep
  playRadioChirp() {
    try {
      this.initContext();
      const osc = this.ctx.createOscillator();
      const gain = this.ctx.createGain();

      osc.type = 'sawtooth';
      osc.frequency.setValueAtTime(880, this.ctx.currentTime);
      osc.frequency.exponentialRampToValueAtTime(1760, this.ctx.currentTime + 0.08);

      gain.gain.setValueAtTime(0.12, this.ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.01, this.ctx.currentTime + 0.08);

      osc.connect(gain);
      gain.connect(this.ctx.destination);

      osc.start();
      osc.stop(this.ctx.currentTime + 0.09);
    } catch (e) {
      console.warn("Radio chirp audio error:", e);
    }
  }

  // Radio end static click
  playRadioClick() {
    try {
      this.initContext();
      const osc = this.ctx.createOscillator();
      const gain = this.ctx.createGain();

      osc.type = 'sine';
      osc.frequency.setValueAtTime(420, this.ctx.currentTime);

      gain.gain.setValueAtTime(0.08, this.ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, this.ctx.currentTime + 0.06);

      osc.connect(gain);
      gain.connect(this.ctx.destination);

      osc.start();
      osc.stop(this.ctx.currentTime + 0.06);
    } catch (e) {
      console.warn("Radio click audio error:", e);
    }
  }

  // Play narration line: uses server MP3 if valid, or Web Speech API with radio filter
  async speak(text, audioFilename) {
    if (state.audioMuted || !text) return;

    this.playRadioChirp();
    state.isSpeaking = true;

    // Check if server audio MP3 is available and not empty
    if (audioFilename) {
      try {
        const audioUrl = `/audio/${audioFilename}`;
        const headResp = await fetch(audioUrl, { method: 'HEAD' });
        const len = parseInt(headResp.headers.get('content-length') || '0', 10);
        if (len > 500) {
          this.audioEl.src = audioUrl;
          this.audioEl.onended = () => {
            this.playRadioClick();
            state.isSpeaking = false;
          };
          await this.audioEl.play();
          return;
        }
      } catch (err) {
        console.warn("Server MP3 playback fell back to synthesizer:", err);
      }
    }

    // High quality Web Speech API dispatcher voice
    if ('speechSynthesis' in window) {
      window.speechSynthesis.cancel();
      const utter = new SpeechSynthesisUtterance(text);
      utter.rate = 1.05;
      utter.pitch = 0.95;

      const voices = window.speechSynthesis.getVoices();
      const englishVoices = voices.filter(v => v.lang.startsWith('en'));
      if (englishVoices.length > 0) {
        // Prefer natural / google / crisp voice
        const preferred = englishVoices.find(v => v.name.includes('Natural') || v.name.includes('Google') || v.name.includes('David') || v.name.includes('Alex'));
        utter.voice = preferred || englishVoices[0];
      }

      utter.onend = () => {
        this.playRadioClick();
        state.isSpeaking = false;
      };
      utter.onerror = () => {
        state.isSpeaking = false;
      };

      setTimeout(() => {
        window.speechSynthesis.speak(utter);
      }, 90);
    } else {
      state.isSpeaking = false;
    }
  }
}

const radioAudio = new TacticalRadioAudio();

// --- Animated Radio Waveform Canvas ---
function initWaveformCanvas() {
  const canvas = document.getElementById('radioCanvas');
  const ctx = canvas.getContext('2d');
  let phase = 0;

  function render() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    const bars = 16;
    const barWidth = canvas.width / bars - 2;

    for (let i = 0; i < bars; i++) {
      let h = 3;
      if (state.isSpeaking) {
        h = 4 + Math.abs(Math.sin(phase + i * 0.45)) * 14;
      }
      ctx.fillStyle = state.isSpeaking ? 'var(--primary)' : 'rgba(255, 255, 255, 0.2)';
      ctx.fillRect(i * (barWidth + 2), (canvas.height - h) / 2, barWidth, h);
    }

    phase += 0.15;
    requestAnimationFrame(render);
  }
  render();
}

// --- Leaflet Map Setup ---
function initMap() {
  state.map = L.map('map', {
    zoomControl: false,
    attributionControl: false
  }).setView([state.lat, state.lon], 15);

  // CartoDB Dark Matter tiles
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '© OpenStreetMap contributors'
  }).addTo(state.map);

  L.control.zoom({ position: 'topright' }).addTo(state.map);

  // Interactive click on map to set start location
  state.map.on('click', (e) => {
    if (document.getElementById('setupModal').classList.contains('hidden') === false) {
      updateLocation(e.latlng.lat, e.latlng.lng, `Selected Point (${e.latlng.lat.toFixed(4)}, ${e.latlng.lng.toFixed(4)})`);
    }
  });
}

function updateLocation(lat, lon, label) {
  state.lat = lat;
  state.lon = lon;
  state.locationName = label || `Location (${lat.toFixed(4)}, ${lon.toFixed(4)})`;

  document.getElementById('currentLocLabel').innerText = `${state.locationName}`;

  if (state.map) {
    state.map.setView([lat, lon], 15);
  }
}

// --- Presets Loader ---
async function loadPresets() {
  const container = document.getElementById('presetsList');
  container.innerHTML = '<div style="font-size:0.75rem; color:#888;">Loading hotspots...</div>';

  try {
    const res = await fetch('/api/missions/presets');
    const presets = await res.json();
    container.innerHTML = '';

    presets.forEach((p, idx) => {
      const chip = document.createElement('div');
      chip.className = `preset-chip ${idx === 0 ? 'active' : ''}`;
      chip.innerHTML = `
        <span class="preset-chip-title">${p.name}</span>
        <span class="preset-chip-sub">${(p.distance_m / 1000).toFixed(1)} km • ${p.genre.toUpperCase()}</span>
      `;
      chip.onclick = () => {
        document.querySelectorAll('.preset-chip').forEach(c => c.classList.remove('active'));
        chip.classList.add('active');
        updateLocation(p.lat, p.lon, p.location_name);
        selectGenre(p.genre);
        setDistance(p.distance_m);
      };
      container.appendChild(chip);
    });
  } catch (e) {
    console.error("Failed to load presets:", e);
  }
}

// --- Genre Selection ---
function selectGenre(genre) {
  state.genre = genre;
  document.body.className = `theme-${genre}`;

  document.querySelectorAll('.genre-card').forEach(card => {
    if (card.dataset.genre === genre) {
      card.classList.add('active');
    } else {
      card.classList.remove('active');
    }
  });

  const genreNames = {
    cyberpunk: 'Cyberpunk Courier',
    zombie: 'Zombie Escape',
    spy: 'Spy Exfiltration'
  };
  const callsigns = {
    cyberpunk: 'DISPATCH // CORPSEC FREQ 142.8 MHz',
    zombie: 'SURVIVOR CONTROL // RESCUE NET 98.4 MHz',
    spy: 'HANDLER // CLASSIFIED SATELLITE LINK 315.0 MHz'
  };

  document.getElementById('hudGenreTag').innerText = genreNames[genre] || genre;
  document.getElementById('operatorCallsign').innerText = callsigns[genre] || 'RADIO DISPATCH';
}

function setDistance(meters) {
  state.distanceM = meters;
  document.getElementById('distanceSlider').value = meters;
  document.getElementById('distanceDisplay').innerText = `${(meters / 1000).toFixed(1)} km`;
  document.getElementById('hudTotalDist').innerText = `${(meters / 1000).toFixed(2)}`;
}

// --- Browser GPS Locator ---
function useCurrentGPS() {
  const btn = document.getElementById('btnUseGps');
  btn.innerHTML = '<span>⏳</span> Acquiring GPS...';

  if (!navigator.geolocation) {
    alert("Geolocation is not supported by your browser.");
    btn.innerHTML = '<span>📡</span> Use My GPS Location';
    return;
  }

  navigator.geolocation.getCurrentPosition(
    (pos) => {
      const lat = pos.coords.latitude;
      const lon = pos.coords.longitude;
      btn.innerHTML = '<span>✓</span> GPS Locked';
      updateLocation(lat, lon, `My GPS (${lat.toFixed(4)}, ${lon.toFixed(4)})`);
    },
    (err) => {
      console.warn("GPS error:", err);
      alert("Could not access your GPS. Using New York demo hotspot.");
      btn.innerHTML = '<span>📡</span> Use My GPS Location';
    },
    { enableHighAccuracy: true, timeout: 8000 }
  );
}

// --- Mission Deployment & Compilation ---
async function deployMission() {
  const btn = document.getElementById('btnDeployMission');
  const steps = document.getElementById('loadingSteps');
  btn.disabled = true;
  steps.classList.remove('hidden');

  const s1 = document.getElementById('step1');
  const s2 = document.getElementById('step2');
  const s3 = document.getElementById('step3');
  const s4 = document.getElementById('step4');

  s1.className = 'loading-step-item active';
  s1.innerText = '⟳ Calculating closed loop pedestrian route (Valhalla)...';

  try {
    setTimeout(() => {
      s1.className = 'loading-step-item done';
      s1.innerText = '✓ Pedestrian route calibrated.';
      s2.className = 'loading-step-item active';
      s2.innerText = '⟳ Scanning OpenStreetMap landmarks & intersections...';
    }, 1200);

    setTimeout(() => {
      s2.className = 'loading-step-item done';
      s2.innerText = '✓ Landmarks mapped & laterally snapped.';
      s3.className = 'loading-step-item active';
      s3.innerText = '⟳ AI Dispatcher crafting narrative mission beats...';
    }, 2800);

    const payload = {
      start_lat: state.lat,
      start_lon: state.lon,
      distance_m: state.distanceM,
      genre: state.genre
    };

    const res = await fetch('/api/missions/create', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    if (!res.ok) {
      throw new Error(`Server returned ${res.status}: ${res.statusText}`);
    }

    const data = await res.json();
    state.sessionId = data.session_id;
    state.route = data.route;
    state.stats = data.stats;

    s3.className = 'loading-step-item done';
    s3.innerText = '✓ Narrative drafted.';
    s4.className = 'loading-step-item done';
    s4.innerText = '✓ Audio transmission channels prepared.';

    if (data.fallback_used && data.fallback_reason) {
      alert(`Notice: ${data.fallback_reason}`);
    }

    // Render Route on Map
    renderRoute(data.route);

    // Close Setup Modal & Reveal HUD
    setTimeout(() => {
      document.getElementById('setupModal').classList.add('hidden');
      document.getElementById('btnCloseModal').style.display = 'block';
      document.getElementById('hudTelemetry').classList.remove('hidden');
      document.getElementById('commsDeck').classList.remove('hidden');
      btn.disabled = false;
      steps.classList.add('hidden');

      // Connect to live WebSocket
      connectWebSocket(data.session_id);

      // Play intro beat if available
      if (data.intro_beat && data.intro_beat.variants) {
        const text = data.intro_beat.variants.operator || "Mission initialized. Commencing route telemetry.";
        const audioFile = data.intro_beat.audio ? data.intro_beat.audio.operator : null;
        receiveTransmission({
          id: data.intro_beat.id,
          kind: "INTRO",
          text: text,
          audio: audioFile,
          chainage_m: 0.0
        });
      }
    }, 800);

  } catch (err) {
    console.error("Compilation error:", err);
    alert(`Mission generation failed: ${err.message}. Please try a preset hotspot.`);
    btn.disabled = false;
    steps.classList.add('hidden');
  }
}

// --- Route & Landmarks Map Rendering ---
function renderRoute(route) {
  if (!state.map || !route || !route.points) return;

  // Clear previous layers
  if (state.routeLayer) state.map.removeLayer(state.routeLayer);
  state.landmarkLayers.forEach(l => state.map.removeLayer(l));
  state.landmarkLayers = [];
  state.maneuverLayers.forEach(m => state.map.removeLayer(m));
  state.maneuverLayers = [];

  const latlngs = route.points.map(p => [p[0], p[1]]);

  // Draw Glowing Route Polyline
  state.routeLayer = L.polyline(latlngs, {
    color: getComputedStyle(document.body).getPropertyValue('--primary').trim() || '#00f0ff',
    weight: 6,
    opacity: 0.9,
    lineCap: 'round',
    lineJoin: 'round',
    dashArray: null
  }).addTo(state.map);

  state.map.fitBounds(state.routeLayer.getBounds(), { padding: [60, 60] });

  // Start & Runner Marker
  const startPt = latlngs[0];
  if (state.runnerMarker) state.map.removeLayer(state.runnerMarker);

  const runnerIcon = L.divIcon({
    className: 'runner-marker-icon',
    iconSize: [22, 22],
    iconAnchor: [11, 11]
  });

  state.runnerMarker = L.marker(startPt, { icon: runnerIcon, zIndexOffset: 1000 }).addTo(state.map);

  // Render Landmarks
  if (route.landmarks && route.landmarks.length > 0) {
    route.landmarks.forEach(lm => {
      const kindIcons = {
        historic: '🏛️',
        museum: '🏛️',
        tourism: '⭐',
        cafe: '☕',
        restaurant: '🍽️',
        fast_food: '🍔',
        shop: '🛍️',
        park: '🌲',
        leisure: '⚽',
        junction: '🚦',
        poi: '📍'
      };
      const iconChar = kindIcons[lm.kind] || '📍';

      const lmIcon = L.divIcon({
        className: 'landmark-icon',
        html: `<span style="font-size:12px;">${iconChar}</span>`,
        iconSize: [26, 26],
        iconAnchor: [13, 13]
      });

      const marker = L.marker([lm.lat, lm.lon], { icon: lmIcon })
        .bindPopup(`
          <div style="font-family:sans-serif; min-width:140px;">
            <b style="color:#00f0ff;">${lm.name}</b><br/>
            <small style="color:#aaa;">Type: ${lm.kind} • Side: ${lm.side} (${lm.offset_m.toFixed(0)}m)</small><br/>
            <small style="color:#666;">Route dist: ${lm.chainage_m.toFixed(0)}m</small>
          </div>
        `)
        .addTo(state.map);

      state.landmarkLayers.push(marker);
    });
  }

  // Update total distance in HUD
  document.getElementById('hudTotalDist').innerText = (route.length_m / 1000).toFixed(2);
}

// --- WebSocket Streaming ---
function connectWebSocket(sessionId) {
  if (state.ws) {
    state.ws.close();
  }

  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${protocol}//${window.location.host}/ws/${sessionId}`;
  state.ws = new WebSocket(wsUrl);

  state.ws.onopen = () => {
    document.getElementById('sysStatus').innerText = 'LIVE TELEMETRY STREAM';
  };

  state.ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      handleWsMessage(data);
    } catch (e) {
      console.error("Failed to parse WS message:", e);
    }
  };

  state.ws.onclose = () => {
    document.getElementById('sysStatus').innerText = 'SESSION CONCLUDED';
  };
}

function handleWsMessage(data) {
  if (data.type === 'telemetry') {
    updateTelemetryHUD(data);
  } else if (data.type === 'beat') {
    const beat = data.beat;
    const text = (beat.variants && beat.variants.operator) || "Maintain heading. Scan surroundings.";
    const audioFile = beat.audio ? beat.audio.operator : null;

    receiveTransmission({
      id: beat.id,
      kind: beat.kind || 'BEAT',
      text: text,
      audio: audioFile,
      chainage_m: beat.anchor_chainage_m || 0.0
    });
  } else if (data.type === 'speed_changed') {
    state.simSpeed = data.mult;
  }
}

function updateTelemetryHUD(fix) {
  const distKm = (fix.chainage_m / 1000).toFixed(2);
  document.getElementById('hudCoveredDist').innerText = distKm;

  const percent = Math.min(100, Math.round((fix.progress || 0) * 100));
  document.getElementById('hudProgressPercent').innerText = `${percent}%`;
  document.getElementById('hudProgressBar').style.width = `${percent}%`;

  const speedMps = fix.speed || 3.2;
  document.getElementById('hudSpeed').innerText = speedMps.toFixed(1);

  // Calculate Pace (min/km)
  if (speedMps > 0.5) {
    const secPerKm = 1000 / speedMps;
    const mins = Math.floor(secPerKm / 60);
    const secs = Math.floor(secPerKm % 60).toString().padStart(2, '0');
    document.getElementById('hudPace').innerText = `${mins}:${secs}`;
  }

  // Update Runner Marker Position
  if (state.runnerMarker && fix.lat && fix.lon) {
    state.runnerMarker.setLatLng([fix.lat, fix.lon]);
    // Smoothly pan map to follow runner
    if (!state.map.getBounds().contains([fix.lat, fix.lon])) {
      state.map.panTo([fix.lat, fix.lon], { animate: true, duration: 0.5 });
    }
  }

  // Determine next maneuver
  if (state.route && state.route.maneuvers) {
    const upcoming = state.route.maneuvers.find(m => m.chainage_m > fix.chainage_m);
    if (upcoming) {
      const remainingM = Math.max(0, Math.round(upcoming.chainage_m - fix.chainage_m));
      document.getElementById('turnDist').innerText = `In ${remainingM}m`;
      document.getElementById('turnInstruction').innerText = upcoming.instruction || `Turn ${upcoming.type}`;

      const turnIcons = {
        'turn_right': '⮡',
        'turn_left': '⮠',
        'straight': '⬆',
        'slight_right': '↗',
        'slight_left': '↖',
        'u_turn': '↩'
      };
      document.getElementById('turnIcon').innerText = turnIcons[upcoming.type] || '⮡';
    } else {
      document.getElementById('turnDist').innerText = `Finish`;
      document.getElementById('turnInstruction').innerText = `Approaching destination`;
    }
  }
}

// --- Radio Transmission Display & Narration ---
function receiveTransmission(item) {
  state.lastDialogue = item;
  state.commsLog.push(item);

  // Update count
  document.getElementById('commsCount').innerText = state.commsLog.length;

  // Typewriter display in bottom deck
  const txtEl = document.getElementById('transmissionText');
  const metaEl = document.getElementById('transmissionMeta');

  metaEl.innerText = `[${item.kind}] CHAINAGE: ${item.chainage_m.toFixed(0)}m // DISPATCH CALLOUT`;
  txtEl.innerText = `"${item.text}"`;

  // Append to history drawer
  const historyDrawer = document.getElementById('historyDrawer');
  const histItem = document.createElement('div');
  histItem.className = 'history-item';
  histItem.innerHTML = `
    <div style="font-family:var(--font-mono); font-size:0.65rem; color:var(--primary); margin-bottom:0.2rem;">
      [${item.kind}] at ${item.chainage_m.toFixed(0)}m
    </div>
    <div style="color:#eee;">${item.text}</div>
  `;
  historyDrawer.prepend(histItem);

  // Speak narration
  radioAudio.speak(item.text, item.audio);
}

// --- Setup Event Listeners ---
function initEvents() {
  document.getElementById('btnOpenSetup').onclick = () => {
    document.getElementById('setupModal').classList.remove('hidden');
  };

  document.getElementById('btnCloseModal').onclick = () => {
    document.getElementById('setupModal').classList.add('hidden');
  };

  document.getElementById('btnUseGps').onclick = useCurrentGPS;

  document.getElementById('btnSelectOnMap').onclick = () => {
    document.getElementById('setupModal').classList.add('hidden');
    alert("Click anywhere on the map to place your runner starting location, then reopen Mission Briefing.");
  };

  // Genre Cards
  document.querySelectorAll('.genre-card').forEach(card => {
    card.onclick = () => selectGenre(card.dataset.genre);
  });

  // Distance Slider
  const slider = document.getElementById('distanceSlider');
  slider.oninput = (e) => setDistance(parseInt(e.target.value, 10));

  // Deploy Mission
  document.getElementById('btnDeployMission').onclick = deployMission;

  // Replay Audio
  document.getElementById('btnReplayAudio').onclick = () => {
    if (state.lastDialogue) {
      radioAudio.speak(state.lastDialogue.text, state.lastDialogue.audio);
    }
  };

  // Mute Toggle
  document.getElementById('btnMuteToggle').onclick = () => {
    state.audioMuted = !state.audioMuted;
    document.getElementById('muteIcon').innerText = state.audioMuted ? '🔇' : '🔊';
  };

  // History Drawer Toggle
  document.getElementById('btnToggleHistory').onclick = () => {
    const drawer = document.getElementById('historyDrawer');
    drawer.classList.toggle('hidden');
  };

  // Sim Pause / Resume
  document.getElementById('btnToggleSim').onclick = () => {
    if (!state.ws || state.ws.readyState !== WebSocket.OPEN) return;
    state.isPaused = !state.isPaused;
    state.ws.send(JSON.stringify({ cmd: state.isPaused ? 'pause' : 'resume' }));
    document.getElementById('btnToggleSim').innerText = state.isPaused ? '▶ Resume' : '⏸ Pause';
  };

  // Speed Multipliers
  document.querySelectorAll('.speed-chips button').forEach(btn => {
    btn.onclick = () => {
      document.querySelectorAll('.speed-chips button').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      const speed = parseFloat(btn.dataset.speed);
      if (state.ws && state.ws.readyState === WebSocket.OPEN) {
        state.ws.send(JSON.stringify({ cmd: 'speed', mult: speed }));
      }
    };
  });
}

// --- Initialization ---
window.addEventListener('DOMContentLoaded', () => {
  initMap();
  initWaveformCanvas();
  loadPresets();
  initEvents();
});
