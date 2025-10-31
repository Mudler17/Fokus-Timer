
# app.py
# Fokus‑Timer (Streamlit) — feste Ansicht, Sanduhr, aufgeräumtes UI
# Abhängigkeiten: streamlit, numpy. KEIN streamlit-extras, KEIN matplotlib.

import time
from io import BytesIO
import base64
import wave
import numpy as np
import streamlit as st

st.set_page_config(page_title="Fokus-Timer", page_icon="⏳", layout="centered")

# ---------- CSS ----------
st.markdown('''
<style>
:root { --fg:#111; --muted:#666; --pill:#f2f2f2; }
.container { max-width: 960px; margin: 0 auto; }
.hgroup { display:flex; flex-direction:column; gap:.25rem; }
.title { font-size:1.6rem; font-weight:700; }
.subtle { color: var(--muted); }
.pill { background: var(--pill); border-radius:999px; padding:.25rem .6rem; font-size:.9rem; }
.grid { display:grid; grid-template-columns: 1fr 360px; gap:1.5rem; align-items:center; margin-top:1rem; }
.timebox { text-align:center; }
.time { font-size:6rem; font-weight:800; line-height:1; letter-spacing:.05em; }
.progress { width:100%; height:10px; background:#eee; border-radius:6px; overflow:hidden; margin-top:.5rem; }
.progress > div { height:100%; background:#4CAF50; }
.meta { display:flex; justify-content:center; gap:1rem; color:var(--muted); margin-top:.25rem; }
.footer { text-align:center; color:var(--muted); margin-top:1rem; font-size:.9rem; }
.sandwrap { display:flex; flex-direction:column; align-items:center; gap:.5rem; }
.sandlabel { font-size:.9rem; color:var(--muted); }
svg { display:block; }
</style>
''', unsafe_allow_html=True)

# ---------- Audio ----------
def generate_tone(freq=880, duration=0.3, volume=0.5, waveform="sine", samplerate=44100):
    t = np.linspace(0, duration, int(samplerate * duration), False)
    if waveform == "sine":
        wave_data = np.sin(2 * np.pi * freq * t)
    elif waveform == "square":
        wave_data = np.sign(np.sin(2 * np.pi * freq * t))
    elif waveform == "triangle":
        wave_data = 2 * np.arcsin(np.sin(2 * np.pi * freq * t)) / np.pi
    else:
        wave_data = 2 * (t * freq - np.floor(0.5 + t * freq))
    fade_len = int(0.02 * samplerate)
    fade_in = np.linspace(0,1,fade_len); fade_out = np.linspace(1,0,fade_len)
    wave_data[:fade_len] *= fade_in; wave_data[-fade_len:] *= fade_out
    audio = (wave_data * (volume * 32767)).astype(np.int16)
    buf = BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(samplerate)
        wf.writeframes(audio.tobytes())
    return buf.getvalue()

def play_audio(audio_bytes: bytes):
    b64 = base64.b64encode(audio_bytes).decode("utf-8")
    st.markdown(f'''
    <audio autoplay hidden>
      <source src="data:audio/wav;base64,{b64}" type="audio/wav">
    </audio>
    ''', unsafe_allow_html=True)

def chime(kind="tick", volume=0.5):
    if kind == "tick":
        play_audio(generate_tone(880, 0.18, volume, "sine"))
    elif kind == "half":
        for f in (660, 880):
            play_audio(generate_tone(f, 0.18, volume, "triangle"))
    elif kind == "end":
        for f,d in ((523,0.22),(659,0.22),(784,0.28)):
            play_audio(generate_tone(f, d, volume, "sine"))

# ---------- State ----------
def init_state():
    ss = st.session_state
    defaults = dict(
        running=False,
        start_time=None,
        paused_at=None,
        pause_accum=0.0,
        duration_sec=25*60,
        next_interval_sec=None,
        halfway_signal=True,
        half_fired=False,
        interval_min=None,
        volume=0.5,
        desc="",
    )
    for k,v in defaults.items():
        if k not in ss: ss[k]=v

init_state()

# ---------- Header & Controls ----------
colL, colR = st.columns([0.65, 0.35])
with colL:
    st.markdown('<div class="hgroup">', unsafe_allow_html=True)
    st.markdown('<div class="title">⏳ Fokus-Timer</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="subtle">Status: <span class="pill">{"laufend" if st.session_state.running else "bereit/pausiert"}</span></div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)
with colR:
    c1, c2, c3 = st.columns(3)
    if c1.button("Start ▶️", use_container_width=True):
        st.session_state.start_time = time.time()
        st.session_state.pause_accum = 0.0 if st.session_state.paused_at is None else st.session_state.pause_accum
        st.session_state.paused_at = None
        st.session_state.running = True
        st.session_state.half_fired = False
        st.session_state.next_interval_sec = (int(st.session_state.interval_min)*60) if st.session_state.interval_min else None
        chime("tick", st.session_state.volume)
    if c2.button("Pause ⏸️", use_container_width=True):
        if st.session_state.running:
            st.session_state.paused_at = time.time()
            st.session_state.running = False
    if c3.button("Reset 🔄", use_container_width=True):
        st.session_state.running = False
        st.session_state.start_time = None
        st.session_state.paused_at = None
        st.session_state.pause_accum = 0.0
        st.session_state.next_interval_sec = None
        st.session_state.half_fired = False

with st.expander("Einstellungen", expanded=True):
    cA, cB, cC, cD = st.columns(4)
    preset = cA.selectbox("Preset", ["Benutzerdefiniert","Pomodoro 25:00","Kurz 10:00","Lang 45:00"], index=1)
    if preset == "Benutzerdefiniert":
        minutes = cB.number_input("Minuten", 1, 240, 25, 1)
    elif preset == "Pomodoro 25:00":
        minutes = 25
    elif preset == "Kurz 10:00":
        minutes = 10
    else:
        minutes = 45
    seconds = cC.number_input("Sek.", 0, 59, 0, 5)
    if cD.button("Übernehmen", use_container_width=True):
        st.session_state.duration_sec = int(minutes)*60 + int(seconds)
        if st.session_state.running:
            st.session_state.start_time = time.time()
            st.session_state.pause_accum = 0.0
            st.session_state.half_fired = False

    c1, c2, c3, c4 = st.columns(4)
    interval_choice = c1.selectbox("Intervall", ["Aus","Jede Minute","Alle 5 Min","Custom"])
    if interval_choice == "Aus":
        st.session_state.interval_min = None
    elif interval_choice == "Jede Minute":
        st.session_state.interval_min = 1
    elif interval_choice == "Alle 5 Min":
        st.session_state.interval_min = 5
    else:
        st.session_state.interval_min = c2.number_input("Minuten", 1, 120, 5, 1)
    st.session_state.halfway_signal = c3.checkbox("🔔 Halbzeit", True)
    st.session_state.volume = c4.slider("Lautstärke", 0.0, 1.0, st.session_state.volume, 0.05)

    st.session_state.desc = st.text_input("Kurzbeschreibung", value=st.session_state.desc, placeholder="z. B. 'Kapitel lesen'")

# ---------- Helpers ----------
def get_elapsed():
    if st.session_state.start_time is None:
        return 0.0
    now = time.time()
    if st.session_state.running:
        return now - st.session_state.start_time - st.session_state.pause_accum
    else:
        paused = st.session_state.paused_at or now
        return paused - st.session_state.start_time - st.session_state.pause_accum

def hourglass_svg(pct_remaining: float) -> str:
    width, height = 160, 240
    top_h = 110
    bottom_h = 110
    top_fill = int(top_h * pct_remaining)
    bot_fill = int(bottom_h * (1 - pct_remaining))
    svg = f'''
<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" aria-label="Sanduhr">
  <defs>
    <clipPath id="clipTop"><polygon points="20,10 140,10 80,120" /></clipPath>
    <clipPath id="clipBottom"><polygon points="80,120 20,230 140,230" /></clipPath>
  </defs>
  <polygon points="20,10 140,10 80,120" fill="none" stroke="#333" stroke-width="3"/>
  <polygon points="80,120 20,230 140,230" fill="none" stroke="#333" stroke-width="3"/>
  <g clip-path="url(#clipTop)">
    <rect x="20" y="{10 + (top_h - top_fill)}" width="120" height="{top_fill}" fill="#E0C068"/>
  </g>
  <g clip-path="url(#clipBottom)">
    <rect x="20" y="{230 - bot_fill}" width="120" height="{bot_fill}" fill="#E0C068"/>
  </g>
  <circle cx="80" cy="120" r="3" fill="#E0C068"/>
</svg>
'''
    return svg

# ---------- Fixed layout placeholders ----------
left_col, right_col = st.columns([1, 1])
left_area = left_col.empty()
right_area = right_col.empty()

def render_once():
    total = st.session_state.duration_sec or 0
    elapsed = get_elapsed()
    remaining = max(0, total - elapsed)
    pct = 0 if total == 0 else max(0, min(1, remaining/total))

    # Signals
    if st.session_state.running and total > 0:
        if st.session_state.halfway_signal and not st.session_state.half_fired and elapsed >= total/2:
            chime("half", st.session_state.volume)
            st.session_state.half_fired = True
        if st.session_state.next_interval_sec is not None and elapsed >= st.session_state.next_interval_sec and remaining > 0:
            chime("tick", st.session_state.volume)
            st.session_state.next_interval_sec += int(st.session_state.interval_min) * 60
    if remaining <= 0.01 and st.session_state.start_time is not None:
        if st.session_state.running:
            chime("end", st.session_state.volume)
        st.session_state.running = False

    with left_area.container():
        st.markdown('<div class="timebox">', unsafe_allow_html=True)
        st.markdown(f'<div class="time">{int(remaining//60):02d}:{int(remaining%60):02d}</div>', unsafe_allow_html=True)
        st.markdown('<div class="progress"><div style="width:{:.2f}%"></div></div>'.format((1-pct)*100), unsafe_allow_html=True)
        st.markdown(f'<div class="meta"><span>{int(pct*100)}% verbleibend</span><span>•</span><span>{st.session_state.desc or "—"}</span></div>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

    with right_area.container():
        st.markdown('<div class="sandwrap">', unsafe_allow_html=True)
        st.markdown(hourglass_svg(pct), unsafe_allow_html=True)
        st.markdown('<div class="sandlabel">Sanduhr</div>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

# Initial render
render_once()

# Live update in-place (keine neuen Fenster)
if st.session_state.running:
    # Sanfter Loop in genau EINEM fest zugewiesenen Platz
    # (verlässt den Loop, wenn pausiert/gestoppt)
    while st.session_state.running:
        time.sleep(0.2)
        render_once()
        # Stoppt automatisch, wenn Zeit <= 0 in render_once() gesetzt wurde

st.markdown('<div class="footer">Tipp: Autoplay kann blockiert sein — einmal klicken (Start) aktiviert Töne.</div>', unsafe_allow_html=True)
