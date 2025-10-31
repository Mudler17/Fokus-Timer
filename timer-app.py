
# app.py — Fokus-Timer 2.0 (freundliche Töne, Takt-Intervalle, Presets, Zen-UI)
# Dependencies: streamlit, numpy

import time
from io import BytesIO
import base64
import wave
import numpy as np
import streamlit as st
import random

st.set_page_config(page_title="Fokus-Timer 2.0", page_icon="⏳", layout="centered")

# ====== ZEN UI / THEME ======
st.markdown('''
<style>
:root {
  --bg1: #f7f9fc;
  --bg2: #e7f0ff;
  --card: rgba(255,255,255,.75);
  --pill: rgba(255,255,255,.9);
  --fg: #1a1f2b;
  --muted: #667085;
  --accent: #3b82f6;
  --good: #22c55e;
}
html, body, .stApp {
  background: linear-gradient(160deg, var(--bg1) 0%, var(--bg2) 100%);
  font-family: "Inter", "Segoe UI", system-ui, -apple-system, sans-serif;
}
.card {
  background: var(--card);
  backdrop-filter: blur(8px);
  border-radius: 20px;
  box-shadow: 0 12px 30px rgba(16,24,40,.08);
  padding: 1.5rem;
}
.header {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 1rem;
  align-items: center;
}
.title {
  font-weight: 800;
  font-size: 1.6rem;
  color: var(--fg);
}
.subtle { color: var(--muted); }
.pill {
  background: var(--pill);
  border-radius: 999px;
  padding: .25rem .6rem;
  font-size: .9rem;
  color: var(--fg);
  box-shadow: 0 2px 6px rgba(16,24,40,.06);
}
.grid {
  display: grid;
  grid-template-columns: 1fr 360px;
  gap: 1.25rem;
  align-items: stretch;
}
.timebox {
  text-align: center;
  display:flex;
  flex-direction:column;
  justify-content:center;
}
.time {
  font-size: 6rem;
  font-weight: 900;
  line-height: 1;
  letter-spacing: .04em;
  color: var(--fg);
  text-shadow: 0 4px 12px rgba(16,24,40,.08);
}
.progress {
  width:100%; height: 12px; background: rgba(0,0,0,.06);
  border-radius: 999px; overflow:hidden; margin-top:.75rem;
}
.progress > div {
  height:100%;
  background: linear-gradient(90deg, var(--accent), #60a5fa);
  transition: width .25s ease;
}
.meta {
  display:flex; gap:.75rem; justify-content:center; align-items:center;
  color: var(--muted); margin-top:.4rem; font-size:.95rem;
}
.sandwrap {
  display:flex; flex-direction:column; align-items:center; justify-content:center; gap:.5rem;
}
.sandlabel { font-size:.9rem; color: var(--muted); }
svg { display:block; filter: drop-shadow(0 6px 10px rgba(16,24,40,.08)); }
.quote { color: var(--muted); font-style: italic; text-align:center; margin-top:.5rem; }
.actions { display:flex; gap:.5rem; }
.presetbar { display:flex; flex-wrap:wrap; gap:.5rem; }
.presetbtn {
  background: var(--pill); color: var(--fg);
  border: 1px solid rgba(16,24,40,.08);
  padding: .45rem .7rem; border-radius: 999px; font-size:.9rem;
}
.smallnote { font-size:.85rem; color: var(--muted); }
</style>
''', unsafe_allow_html=True)

QUOTES = [
  "Der nächste gute Schritt ist klein — tu ihn jetzt.",
  "Tiefe Konzentration entsteht aus kleinen, wiederholten Fokusschritten.",
  "Atme einmal tief durch. Dann nur die nächste Minute.",
  "Weniger Ablenkung, mehr Gegenwart."
]

# ====== AUDIO / MELODY ENGINE ======
def _env(n, head=0.02, tail=0.04):
    # simple linear fade-in/out envelope
    env = np.ones(n)
    hi = int(n*head); ti = int(n*tail)
    if hi>0: env[:hi] = np.linspace(0,1,hi)
    if ti>0: env[-ti:] = np.linspace(1,0,ti)
    return env

def synth_tone(freq=440, dur=0.25, sr=44100, vol=0.5, wave="sine"):
    t = np.linspace(0, dur, int(sr*dur), False)
    if wave=="sine":
        y = np.sin(2*np.pi*freq*t)
    elif wave=="triangle":
        y = 2*np.arcsin(np.sin(2*np.pi*freq*t))/np.pi
    elif wave=="square":
        y = np.sign(np.sin(2*np.pi*freq*t))
    else: # saw
        y = 2*(t*freq - np.floor(0.5 + t*freq))
    return (y * _env(len(t)) * vol).astype(np.float32)

def merge_voices(voices):
    # Mix multiple waveforms (same sr)
    if not voices: return np.zeros(1, dtype=np.float32)
    L = max(len(v) for v in voices)
    mix = np.zeros(L, dtype=np.float32)
    for v in voices:
        mix[:len(v)] += v
    # soft limiter
    mix /= max(1.0, np.max(np.abs(mix))*1.2)
    return mix

def seq_to_wav(seq, sr=44100):
    y = np.concatenate(seq) if seq else np.zeros(1, dtype=np.float32)
    # float32 -> int16 WAV
    y16 = (y * 32767).astype(np.int16)
    buf = BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(sr)
        wf.writeframes(y16.tobytes())
    return buf.getvalue()

def play_wav(bts):
    b64 = base64.b64encode(bts).decode("utf-8")
    st.markdown(f'''
    <audio autoplay hidden>
      <source src="data:audio/wav;base64,{b64}" type="audio/wav">
    </audio>
    ''', unsafe_allow_html=True)

# Friendly chord dictionaries (A4=440)
A4=440.0
NOTES = {
    "C4":261.63,"D4":293.66,"E4":329.63,"F4":349.23,"G4":392.00,"A4":440.00,"B4":493.88,
    "C5":523.25,"D5":587.33,"E5":659.25,"F5":698.46,"G5":783.99
}

def triad(root="C4", quality="maj"):
    r = NOTES[root]
    if quality=="maj":
        return [r, r*2**(4/12), r*2**(7/12)]  # 0, +4, +7
    elif quality=="min":
        return [r, r*2**(3/12), r*2**(7/12)]  # 0, +3, +7
    else:
        return [r]

def chord_sound(freqs, dur=0.28, style="sanft", vol=0.6):
    # style: sanft (sine triad), klar (single sine), klassisch (triangle triad)
    seq=[]
    if style=="klar":
        seq.append(synth_tone(freqs[0], dur=dur, wave="sine", vol=vol))
    elif style=="klassisch":
        voices=[synth_tone(f, dur=dur, wave="triangle", vol=vol*0.75) for f in freqs]
        seq.append(merge_voices(voices))
    else: # sanft
        voices=[synth_tone(f, dur=dur, wave="sine", vol=vol*0.7) for f in freqs]
        seq.append(merge_voices(voices))
    return seq_to_wav(seq)

def two_bar_motif(style="sanft", vol=0.5):
    # kleine „spielerische“ Zweitakt-Melodie
    seq=[]
    patt=[("C4","maj"),("G4","maj"),("F4","maj"),("C5","maj")]
    for r,q in patt:
        seq.append(synth_tone(NOTES[r], dur=0.16, wave="sine", vol=vol))
    return seq_to_wav(seq)

def chime(kind="start", style="sanft", vol=0.5):
    if kind=="start":
        freqs=triad("C4","maj"); play_wav(chord_sound(freqs, style=style, vol=vol))
    elif kind=="half":
        freqs=triad("G4","maj"); play_wav(chord_sound(freqs, style=style, vol=vol))
    elif kind=="end":
        freqs=triad("F4","maj"); play_wav(chord_sound(freqs, style=style, vol=vol))
    elif kind=="tick":
        play_wav(two_bar_motif(style=style, vol=min(vol,0.45)))

# ====== STATE ======
def init_state():
    ss = st.session_state
    defaults = dict(
        running=False, start_time=None, paused_at=None, pause_accum=0.0,
        duration_sec=25*60, next_interval_sec=None, halfway=True, half_fired=False,
        interval_mode="none", interval_custom=60, measure_len=15, measure_count=0,
        sound_style="sanft", volume=0.5, desc="",
    )
    for k,v in defaults.items():
        if k not in ss: ss[k]=v
init_state()

# ====== HEADER / CONTROLS ======
st.markdown('<div class="card header">', unsafe_allow_html=True)
left, right = st.columns([0.65, 0.35])
with left:
    st.markdown(f'<div class="title">⏳ Fokus-Timer 2.0</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="subtle">Status: <span class="pill">{"laufend" if st.session_state.running else "bereit/pausiert"}</span></div>', unsafe_allow_html=True)
with right:
    b1,b2,b3 = st.columns(3)
    if b1.button("Start ▶️", use_container_width=True):
        st.session_state.start_time = time.time()
        st.session_state.pause_accum = 0.0 if st.session_state.paused_at is None else st.session_state.pause_accum
        st.session_state.paused_at = None
        st.session_state.running = True
        st.session_state.half_fired = False
        st.session_state.measure_count = 0
        # schedule first tick
        if st.session_state.interval_mode=="none":
            st.session_state.next_interval_sec = None
        elif st.session_state.interval_mode=="60":
            st.session_state.next_interval_sec = 60
        elif st.session_state.interval_mode=="300":
            st.session_state.next_interval_sec = 300
        elif st.session_state.interval_mode=="rhythm":
            st.session_state.next_interval_sec = st.session_state.measure_len
        else: # custom
            st.session_state.next_interval_sec = max(1, int(st.session_state.interval_custom))
        chime("start", style=st.session_state.sound_style, vol=st.session_state.volume)
    if b2.button("Pause ⏸️", use_container_width=True):
        if st.session_state.running:
            st.session_state.paused_at = time.time()
            st.session_state.running = False
    if b3.button("Reset 🔄", use_container_width=True):
        st.session_state.running=False; st.session_state.start_time=None
        st.session_state.paused_at=None; st.session_state.pause_accum=0.0
        st.session_state.next_interval_sec=None; st.session_state.half_fired=False
st.markdown('</div>', unsafe_allow_html=True)

# ====== PRESETS / QUICK START ======
st.markdown('<div class="card">', unsafe_allow_html=True)
st.markdown('**Was möchtest du jetzt tun?**', unsafe_allow_html=True)
c1,c2,c3,c4,c5 = st.columns(5)
presets = [
    ("✉️ E-Mails beantworten", 15*60),
    ("📞 Telefonate planen", 10*60),
    ("📖 Kapitel lesen", 25*60),
    ("💡 Konzentriert arbeiten", 45*60),
    ("🧘 Kurze Pause", 5*60),
]
for (label, secs), col in zip(presets, (c1,c2,c3,c4,c5)):
    if col.button(label, use_container_width=True):
        st.session_state.duration_sec = secs
        st.session_state.desc = label.replace("✉️ ","").replace("📞 ","").replace("📖 ","").replace("💡 ","").replace("🧘 ","")
        # Auto-Start bei Preset
        st.session_state.start_time = time.time()
        st.session_state.pause_accum = 0.0
        st.session_state.paused_at = None
        st.session_state.running = True
        st.session_state.half_fired = False
        if st.session_state.interval_mode=="none":
            st.session_state.next_interval_sec = None
        elif st.session_state.interval_mode=="60":
            st.session_state.next_interval_sec = 60
        elif st.session_state.interval_mode=="300":
            st.session_state.next_interval_sec = 300
        elif st.session_state.interval_mode=="rhythm":
            st.session_state.next_interval_sec = st.session_state.measure_len
        else:
            st.session_state.next_interval_sec = max(1, int(st.session_state.interval_custom))
        chime("start", style=st.session_state.sound_style, vol=st.session_state.volume)
st.markdown('</div>', unsafe_allow_html=True)

# ====== SETTINGS ======
with st.expander("Einstellungen"):
    r1,r2,r3,r4 = st.columns(4)
    preset_mode = r1.selectbox("Dauer-Preset", ["Benutzerdefiniert","Pomodoro 25:00","Kurz 10:00","Lang 45:00"], index=1)
    if preset_mode=="Benutzerdefiniert":
        minutes = r2.number_input("Minuten", 1, 240, 25, 1)
    elif preset_mode=="Pomodoro 25:00":
        minutes = 25
    elif preset_mode=="Kurz 10:00":
        minutes = 10
    else:
        minutes = 45
    seconds = r3.number_input("Sek.", 0, 59, 0, 5)
    if r4.button("Übernehmen", use_container_width=True):
        st.session_state.duration_sec = int(minutes)*60 + int(seconds)
        if st.session_state.running:
            st.session_state.start_time = time.time()
            st.session_state.pause_accum = 0.0
            st.session_state.half_fired = False

    r5, r6, r7, r8 = st.columns(4)
    interval_choice = r5.selectbox("Tonintervall", [
        "Kein Signal", "Alle 60 Sekunden", "Alle 5 Minuten", "Rhythmisch: 4×15s", "Benutzerdefiniert (Sekunden)"
    ])
    if interval_choice=="Kein Signal":
        st.session_state.interval_mode="none"
    elif interval_choice=="Alle 60 Sekunden":
        st.session_state.interval_mode="60"
    elif interval_choice=="Alle 5 Minuten":
        st.session_state.interval_mode="300"
    elif interval_choice=="Rhythmisch: 4×15s":
        st.session_state.interval_mode="rhythm"
        st.session_state.measure_len = 15
    else:
        st.session_state.interval_mode="custom"
    if st.session_state.interval_mode=="custom":
        st.session_state.interval_custom = r6.number_input("Sekunden", 1, 3600, int(st.session_state.interval_custom), 1)

    st.session_state.halfway = r7.checkbox("🔔 Halbzeit-Signal", True)
    st.session_state.volume = r8.slider("Lautstärke", 0.0, 1.0, st.session_state.volume, 0.05)

    r9, r10 = st.columns(2)
    st.session_state.sound_style = r9.selectbox("Klangstil", ["sanft", "klar", "klassisch"], index=["sanft","klar","klassisch"].index(st.session_state.sound_style))
    st.session_state.desc = r10.text_input("Beschreibung", value=st.session_state.desc, placeholder="z. B. 'Kapitel lesen'")

# ====== CORE LOGIC ======
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
    width, height = 200, 280
    top_h = 130; bottom_h = 130
    top_fill = int(top_h * pct_remaining)
    bot_fill = int(bottom_h * (1 - pct_remaining))
    svg = f'''
<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" aria-label="Sanduhr">
  <defs>
    <clipPath id="clipTop"><polygon points="30,20 170,20 100,150" /></clipPath>
    <clipPath id="clipBottom"><polygon points="100,150 30,260 170,260" /></clipPath>
  </defs>
  <rect x="14" y="8" width="172" height="268" rx="22" fill="white" opacity=".55"/>
  <polygon points="30,20 170,20 100,150" fill="none" stroke="#334155" stroke-width="3"/>
  <polygon points="100,150 30,260 170,260" fill="none" stroke="#334155" stroke-width="3"/>
  <g clip-path="url(#clipTop)">
    <rect x="30" y="{20 + (top_h - top_fill)}" width="140" height="{top_fill}" fill="#E0C068"/>
  </g>
  <g clip-path="url(#clipBottom)">
    <rect x="30" y="{260 - bot_fill}" width="140" height="{bot_fill}" fill="#E0C068"/>
  </g>
  <circle cx="100" cy="150" r="3.5" fill="#E0C068"/>
</svg>
'''
    return svg

# Fixed placeholders
left_col, right_col = st.columns([1, 1])
left_area = left_col.empty()
right_area = right_col.empty()

def render_once():
    total = st.session_state.duration_sec or 0
    elapsed = get_elapsed()
    remaining = max(0, total - elapsed)
    pct = 0 if total==0 else max(0, min(1, remaining/total))

    # Signals
    if st.session_state.running and total > 0:
        # half
        if st.session_state.halfway and not st.session_state.half_fired and elapsed >= total/2:
            chime("half", style=st.session_state.sound_style, vol=st.session_state.volume)
            st.session_state.half_fired = True
        # interval
        if st.session_state.next_interval_sec is not None and elapsed >= st.session_state.next_interval_sec and remaining > 0:
            if st.session_state.interval_mode=="rhythm":
                st.session_state.measure_count = (st.session_state.measure_count + 1) % 4
                chime("tick", style=st.session_state.sound_style, vol=st.session_state.volume)
                st.session_state.next_interval_sec += st.session_state.measure_len
            else:
                chime("tick", style=st.session_state.sound_style, vol=st.session_state.volume)
                if st.session_state.interval_mode in ("60","300","custom"):
                    add = 60 if st.session_state.interval_mode=="60" else (300 if st.session_state.interval_mode=="300" else int(st.session_state.interval_custom))
                    st.session_state.next_interval_sec += add

    # stop
    if remaining <= 0.01 and st.session_state.start_time is not None:
        if st.session_state.running:
            chime("end", style=st.session_state.sound_style, vol=st.session_state.volume)
        st.session_state.running = False

    with left_area.container():
        st.markdown('<div class="card timebox">', unsafe_allow_html=True)
        st.markdown(f'<div class="time">{int(remaining//60):02d}:{int(remaining%60):02d}</div>', unsafe_allow_html=True)
        st.markdown('<div class="progress"><div style="width:{:.2f}%"></div></div>'.format((1-pct)*100), unsafe_allow_html=True)
        st.markdown(f'<div class="meta"><span>{int(pct*100)}% verbleibend</span><span>•</span><span>{st.session_state.desc or "—"}</span></div>', unsafe_allow_html=True)
        st.markdown(f'<div class="quote">„{random.choice(QUOTES)}“</div>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

    with right_area.container():
        st.markdown('<div class="card sandwrap">', unsafe_allow_html=True)
        st.markdown(hourglass_svg(pct), unsafe_allow_html=True)
        st.markdown('<div class="sandlabel">Sanduhr</div>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

# Initial render
render_once()

# Live update in-place
if st.session_state.running:
    while st.session_state.running:
        time.sleep(0.2)
        render_once()

st.markdown('<div class="smallnote" style="text-align:center;margin-top:.5rem;">Hinweis: Ein Klick (Start) aktiviert ggf. blockierte Browser-Töne.</div>', unsafe_allow_html=True)
