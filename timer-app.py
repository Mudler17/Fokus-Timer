# app.py
# Streamlit Fokus-Timer mit mehreren Layouts, Menüsteuerung, Tönen
# + Pomodoro-Zyklusmodus und CSV-Logging

import os
import time
from io import BytesIO
import base64
import wave
import numpy as np
import streamlit as st
import matplotlib.pyplot as plt
import csv
from datetime import datetime

st.set_page_config(page_title='Fokus-Timer', page_icon='⏳', layout='centered')

# --------- Stil / CSS ---------
st.markdown(
    '''
    <style>
    .big-time { font-size: 6rem; font-weight: 700; line-height: 1; text-align:center; }
    .center { text-align: center; }
    .muted { opacity: 0.7; }
    .pill { padding: .25rem .6rem; border-radius: 999px; background: #efefef; display:inline-block; }
    .footer { opacity: .6; font-size: .85rem; text-align:center; margin-top: 1rem; }
    </style>
    ''',
    unsafe_allow_html=True
)

# --------- Helper: Audio erzeugen ---------
def generate_tone(freq=880, duration=0.35, volume=0.5, waveform='sine', samplerate=44100):
    t = np.linspace(0, duration, int(samplerate * duration), False)
    if waveform == 'sine':
        wave_data = np.sin(2 * np.pi * freq * t)
    elif waveform == 'square':
        wave_data = np.sign(np.sin(2 * np.pi * freq * t))
    elif waveform == 'triangle':
        wave_data = 2 * np.arcsin(np.sin(2 * np.pi * freq * t)) / np.pi
    elif waveform == 'saw':
        wave_data = 2 * (t * freq - np.floor(0.5 + t * freq))
    else:
        wave_data = np.sin(2 * np.pi * freq * t)
    fade_len = int(0.02 * samplerate)
    if fade_len > 0:
        fade_in = np.linspace(0, 1, fade_len)
        fade_out = np.linspace(1, 0, fade_len)
        wave_data[:fade_len] *= fade_in
        wave_data[-fade_len:] *= fade_out
    audio = (wave_data * (volume * 32767)).astype(np.int16)
    buf = BytesIO()
    with wave.open(buf, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(samplerate)
        wf.writeframes(audio.tobytes())
    return buf.getvalue()

def autoplay_audio(audio_bytes: bytes):
    b64 = base64.b64encode(audio_bytes).decode('utf-8')
    md = f'''
    <audio autoplay hidden>
        <source src="data:audio/wav;base64,{b64}" type="audio/wav">
    </audio>
    '''
    st.markdown(md, unsafe_allow_html=True)

def chime(kind='tick', volume=0.5):
    if kind == 'tick':
        autoplay_audio(generate_tone(880, 0.18, volume, 'sine'))
    elif kind == 'half':
        for f in (660, 880):
            autoplay_audio(generate_tone(f, 0.18, volume, 'triangle'))
    elif kind == 'end':
        for f, d in ((523,0.22), (659,0.22), (784,0.28)):
            autoplay_audio(generate_tone(f, d, volume, 'sine'))

# --------- Pfade ---------
LOG_DIR = 'logs'
os.makedirs(LOG_DIR, exist_ok=True)
LOG_PATH = os.path.join(LOG_DIR, 'session_log.csv')

def ensure_log_file():
    if not os.path.exists(LOG_PATH):
        with open(LOG_PATH, 'w', newline='', encoding='utf-8') as f:
            w = csv.writer(f)
            w.writerow(['phase','description','start_ts','end_ts','duration_sec','session_index','long_break_every'])

def append_log(row):
    ensure_log_file()
    with open(LOG_PATH, 'a', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(row)

# --------- Zustand ---------
def init_state():
    ss = st.session_state
    defaults = {
        'running': False,
        'start_time': None,
        'paused_at': None,
        'pause_accum': 0.0,
        'duration_sec': 25*60,
        'next_interval_sec': None,
        'half_fired': False,
        'phase': 'focus',  # 'focus' | 'break'
        'session_index': 0,
        'focus_default': 25*60,
        'short_break_default': 5*60,
        'long_break_default': 15*60,
        'long_break_every': 4,
        'auto_start_next': True,
        'desc': ''
    }
    for k,v in defaults.items():
        if k not in ss: ss[k] = v

init_state()

# --------- Sidebar: Steuerung ---------
st.sidebar.title('⚙️ Einstellungen')
preset = st.sidebar.selectbox(
    'Voreinstellung',
    ['Benutzerdefiniert', 'Pomodoro 25/5/15', 'Kurzfokus 10', 'Langfokus 45'],
    index=1
)
if preset == 'Pomodoro 25/5/15':
    minutes = 25
    st.session_state.focus_default = 25*60
    st.session_state.short_break_default = 5*60
    st.session_state.long_break_default = 15*60
elif preset == 'Kurzfokus 10':
    minutes = 10
    st.session_state.focus_default = 10*60
elif preset == 'Langfokus 45':
    minutes = 45
    st.session_state.focus_default = 45*60
else:
    minutes = st.sidebar.number_input('Minuten', 1, 240, 25, 1)
    st.session_state.focus_default = int(minutes)*60

seconds = st.sidebar.number_input('Sekunden', 0, 59, 0, 5)

# Pomodoro-Optionen
with st.sidebar.expander('Pomodoro-Zyklus', expanded=True):
    st.session_state.short_break_default = st.number_input('Kurze Pause (Min.)', 1, 30, int(st.session_state.short_break_default//60), 1)*60
    st.session_state.long_break_default = st.number_input('Lange Pause (Min.)', 5, 60, int(st.session_state.long_break_default//60), 5)*60
    st.session_state.long_break_every = st.number_input('Lange Pause nach X Fokus-Sessions', 2, 10, int(st.session_state.long_break_every), 1)
    st.session_state.auto_start_next = st.checkbox('Nächste Phase automatisch starten', value=bool(st.session_state.auto_start_next))

# Intervalle & Töne
interval_choice = st.sidebar.selectbox('Intervall-Signal', ['Aus', 'Jede Minute', 'Alle 5 Minuten', 'Benutzerdefiniert (Minuten)'])
if interval_choice == 'Jede Minute':
    interval_min = 1
elif interval_choice == 'Alle 5 Minuten':
    interval_min = 5
elif interval_choice == 'Benutzerdefiniert (Minuten)':
    interval_min = st.sidebar.number_input('Intervall (Minuten)', 1, 120, 5)
else:
    interval_min = None
halfway_signal = st.sidebar.checkbox('🔔 Signal auf halber Strecke', value=True)
volume = st.sidebar.slider('Lautstärke', 0.0, 1.0, 0.5, 0.05)

layout = st.sidebar.selectbox('Visualisierung', ['Digital (groß)', 'Ring (Donut)', 'Segmente'])

st.sidebar.markdown('---')
colA, colB, colC = st.sidebar.columns(3)
if colA.button('Start ▶️'):
    st.session_state.duration_sec = int(minutes)*60 + int(seconds) if preset=='Benutzerdefiniert' else st.session_state.focus_default
    st.session_state.start_time = time.time()
    st.session_state.pause_accum = 0.0
    st.session_state.paused_at = None
    st.session_state.running = True
    st.session_state.half_fired = False
    st.session_state.phase = 'focus'
    if interval_min:
        st.session_state.next_interval_sec = interval_min * 60
    else:
        st.session_state.next_interval_sec = None
    chime('tick', volume)

if colB.button('Pause ⏸️'):
    if st.session_state.running:
        st.session_state.paused_at = time.time()
        st.session_state.running = False

if colC.button('Reset 🔄'):
    for k in ['running','start_time','paused_at','pause_accum','next_interval_sec','half_fired']:
        st.session_state[k] = {'running':False,'start_time':None,'paused_at':None,'pause_accum':0.0,'next_interval_sec':None,'half_fired':False}[k]
    st.session_state.session_index = 0
    st.session_state.phase = 'focus'

if not st.session_state.running and st.session_state.paused_at is not None:
    if st.sidebar.button('Weiter ▶️'):
        delta = time.time() - st.session_state.paused_at
        st.session_state.pause_accum += delta
        st.session_state.paused_at = None
        st.session_state.running = True
        chime('tick', volume)

# --------- Hauptbereich ---------
st.title('⏳ Fokus-Timer')

st.session_state.desc = st.text_input('Kurzbeschreibung (optional)', value=st.session_state.get('desc',''), placeholder="z. B. 'Kapitel lesen' oder 'Bericht schreiben'")

def fmt_time(s):
    s = max(0, int(round(s)))
    m, sec = divmod(s, 60)
    return f"{m:02d}:{sec:02d}"

def draw_ring(remaining, total):
    pct = 0 if total == 0 else max(0, min(1, remaining/total))
    fig, ax = plt.subplots(figsize=(4,4))
    ax.axis('equal')
    ax.pie([pct, 1-pct], startangle=90, counterclock=False, wedgeprops=dict(width=0.3))
    ax.text(0, 0, fmt_time(remaining), ha='center', va='center', fontsize=36, fontweight='bold')
    ax.set_aspect('equal')
    st.pyplot(fig, use_container_width=False)

def draw_segments(remaining, total, segments=12):
    pct = 0 if total == 0 else max(0, min(1, remaining/total))
    filled = int(round(pct * segments))
    segs = ['█'] * filled + ['░'] * (segments - filled)
    st.markdown(f"<div class='center' style='font-size:2rem;letter-spacing:.2rem;'>{''.join(segs)}</div>", unsafe_allow_html=True)
    st.markdown(f"<div class='center muted'>{int(pct*100)}% verbleibend</div>", unsafe_allow_html=True)
    st.markdown(f"<div class='center big-time'>{fmt_time(remaining)}</div>", unsafe_allow_html=True)

def render(remaining, total):
    st.markdown(f"<div class='center pill'>Phase: <b>{'Fokus' if st.session_state.phase=='focus' else 'Pause'}</b></div>", unsafe_allow_html=True)
    if layout == 'Digital (groß)':
        st.markdown(f"<div class='big-time'>{fmt_time(remaining)}</div>", unsafe_allow_html=True)
        st.progress(0 if total==0 else 1-remaining/total)
    elif layout == 'Ring (Donut)':
        draw_ring(remaining, total)
    elif layout == 'Segmente':
        draw_segments(remaining, total)

def get_elapsed():
    if st.session_state.start_time is None:
        return 0.0
    now = time.time()
    if st.session_state.running:
        return now - st.session_state.start_time - st.session_state.pause_accum
    else:
        paused = st.session_state.paused_at or now
        return paused - st.session_state.start_time - st.session_state.pause_accum

def switch_phase_and_maybe_autostart():
    # Phase wechseln (Focus -> Break oder Break -> Focus) inkl. Dauer setzen
    if st.session_state.phase == 'focus':
        # Log Focus
        append_log(['focus', st.session_state.desc,
                    datetime.fromtimestamp(st.session_state.start_time).isoformat(),
                    datetime.now().isoformat(),
                    int(get_elapsed()),
                    st.session_state.session_index,
                    st.session_state.long_break_every])
        st.session_state.session_index += 1
        # Bestimmen, ob lange oder kurze Pause
        if st.session_state.session_index % int(st.session_state.long_break_every) == 0:
            st.session_state.duration_sec = int(st.session_state.long_break_default)
        else:
            st.session_state.duration_sec = int(st.session_state.short_break_default)
        st.session_state.phase = 'break'
    else:
        # Log Break
        append_log(['break', st.session_state.desc,
                    datetime.fromtimestamp(st.session_state.start_time).isoformat(),
                    datetime.now().isoformat(),
                    int(get_elapsed()),
                    st.session_state.session_index,
                    st.session_state.long_break_every])
        # zurück zu Fokus
        st.session_state.duration_sec = int(st.session_state.focus_default)
        st.session_state.phase = 'focus'

    # entweder automatisch starten oder auf manuellen Start warten
    st.session_state.start_time = time.time() if st.session_state.auto_start_next else None
    st.session_state.pause_accum = 0.0
    st.session_state.paused_at = None
    st.session_state.running = bool(st.session_state.auto_start_next)
    st.session_state.half_fired = False
    if st.session_state.running:
        chime('tick', volume)

# --------- Ablauf ---------
total = st.session_state.duration_sec
if st.session_state.start_time is None:
    if total:
        render(total, total)
    st.caption('Bereit. Wähle eine Dauer und drücke **Start**. (Pomodoro-Optionen in der Sidebar)')
else:
    # Live-Loop
    while True:
        elapsed = get_elapsed()
        remaining = max(0, total - elapsed)

        # Halbzeit
        if halfway_signal and not st.session_state.half_fired and total > 0 and elapsed >= total/2:
            chime('half', volume)
            st.session_state.half_fired = True

        # Intervalle
        if st.session_state.running and st.session_state.next_interval_sec is not None:
            if elapsed >= st.session_state.next_interval_sec and remaining > 0:
                chime('tick', volume)
                st.session_state.next_interval_sec += (interval_min * 60)

        # Render
        render(remaining, total)

        # Ende der Phase
        if remaining <= 0.01:
            if st.session_state.running:
                chime('end', volume)
            st.session_state.running = False
            switch_phase_and_maybe_autostart()
            break

        if not st.session_state.running:
            break

        time.sleep(0.1)

# --------- Logging/Export ---------
ensure_log_file()
if os.path.exists(LOG_PATH):
    with open(LOG_PATH, 'rb') as f:
        st.sidebar.download_button('📥 Log herunterladen (CSV)', f, file_name='focus_timer_log.csv', mime='text/csv')

st.markdown("<div class='footer'>Tipp: Pomodoro-Zyklus, Intervalle & Lautstärke in der Sidebar anpassen.</div>", unsafe_allow_html=True)
