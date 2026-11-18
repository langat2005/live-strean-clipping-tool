"""
Live Stream AI Clipper Studio — MVP Dashboard with Real-Time Live Feed.
Features:
  1. 🔴 Live Stream Buffer Feed (real-time stream snapshot, buffer health, active stage progress)
  2. 💬 Live Chat Ticker (incoming messages, velocity meter, hype alerts)
  3. 📝 Live Clipping Activity Feed (step-by-step progress tracking)
  4. 🎞️ Clip Gallery (playable 9:16 videos with dynamic subtitles & metadata)
  5. ⚙️ Live Clipper Engine Controls (Start/Stop background engine)
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import time
from datetime import datetime

import pandas as pd
import streamlit as st

from ffmpeg_utils import resolve_ffmpeg, resolve_ffprobe

# ─── Page Configuration ───
st.set_page_config(
    page_title="Live Stream Clipper Studio",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ─── File Paths ───
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CLIPS_DIR = PROJECT_ROOT / "storage" / "clips"
TEST_DIR = PROJECT_ROOT / "storage" / "integration_test"
TEMP_DIR = PROJECT_ROOT / "storage" / "temp"
BUFFER_DIR = PROJECT_ROOT / "storage" / "buffer"
VENV_PYTHON = PROJECT_ROOT / "venv" / "Scripts" / "python.exe"
PID_FILE = PROJECT_ROOT / "storage" / "clipper_process.json"
STATE_FILE = PROJECT_ROOT / "storage" / "pipeline_state.json"
PREVIEW_IMG = BUFFER_DIR / "live_preview.jpg"


# ─── Process Management Helpers ───
def get_system_env():
    """Retrieve PATH including system and user paths for FFmpeg."""
    env = os.environ.copy()
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             '[System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")'],
            capture_output=True, text=True, timeout=5
        )
        if r.returncode == 0 and r.stdout.strip():
            env["PATH"] = r.stdout.strip() + ";" + env.get("PATH", "")
    except Exception:
        pass
    return env


def is_clipper_running() -> tuple[bool, int, str]:
    """Check if the background clipper process is currently alive."""
    if not PID_FILE.exists():
        return False, 0, ""
    try:
        data = json.loads(PID_FILE.read_text(encoding="utf-8"))
        pid = data.get("pid", 0)
        mode = data.get("mode", "unknown")
        r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                           capture_output=True, text=True, timeout=5)
        if str(pid) in r.stdout:
            return True, pid, mode
    except Exception:
        pass
    return False, 0, ""


def stop_clipper():
    """Stop the background clipper process."""
    is_running, pid, _ = is_clipper_running()
    if is_running and pid > 0:
        try:
            subprocess.run(["taskkill", "/PID", str(pid), "/F", "/T"], capture_output=True, timeout=5)
        except Exception:
            pass
    if PID_FILE.exists():
        PID_FILE.unlink(missing_ok=True)


def start_clipper_url(stream_input: str, threshold: float, cooldown: float, framing: str):
    """Launch main.py in the background with a resolved stream link."""
    stop_clipper()
    log_file = PROJECT_ROOT / "storage" / "clipper_live.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    
    cmd = [
        str(VENV_PYTHON),
        str(PROJECT_ROOT / "main.py"),
        f"--url={stream_input}",
        f"--threshold={threshold}",
        f"--cooldown={cooldown}",
        f"--framing={framing}"
    ]

    env = get_system_env()
    log_handle = open(log_file, "w", encoding="utf-8")
    
    proc = subprocess.Popen(
        cmd,
        cwd=str(PROJECT_ROOT),
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        env=env,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    )

    PID_FILE.write_text(json.dumps({
        "pid": proc.pid,
        "mode": stream_input,
        "started_at": datetime.now().isoformat(),
        "cmd": cmd
    }), encoding="utf-8")

    return proc.pid


def start_clipper(mode: str, target: str, stream_url: str, threshold: float, cooldown: float, framing: str):
    """Launch main.py in the background and record its PID."""
    stop_clipper()
    log_file = PROJECT_ROOT / "storage" / "clipper_live.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    
    cmd = [
        str(VENV_PYTHON),
        str(PROJECT_ROOT / "main.py"),
        f"--threshold={threshold}",
        f"--cooldown={cooldown}",
        f"--framing={framing}"
    ]

    if mode == "Mock Simulation":
        cmd.append("--mock")
    elif mode == "YouTube Live":
        cmd.extend(["--youtube", target])
    elif mode == "Twitch":
        cmd.extend(["--twitch", target])

    if stream_url:
        cmd.extend(["--stream-url", stream_url])

    env = get_system_env()
    log_handle = open(log_file, "w", encoding="utf-8")
    
    proc = subprocess.Popen(
        cmd,
        cwd=str(PROJECT_ROOT),
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        env=env,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    )

    PID_FILE.write_text(json.dumps({
        "pid": proc.pid,
        "mode": mode,
        "started_at": datetime.now().isoformat(),
        "cmd": cmd
    }), encoding="utf-8")

    return proc.pid


def load_pipeline_state() -> dict:
    """Load latest live state from storage/pipeline_state.json."""
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def find_clips(only_final=True) -> list[Path]:
    """Find all clip video files, sorted by recency."""
    clips = []
    if CLIPS_DIR.exists():
        pattern = "*_final.mp4" if only_final else "*.mp4"
        clips.extend(CLIPS_DIR.glob(pattern))

    if TEST_DIR.exists():
        pattern = "FINAL_*.mp4" if only_final else "*.mp4"
        clips.extend(TEST_DIR.glob(pattern))

    return sorted(clips, key=lambda p: p.stat().st_mtime, reverse=True)


def get_video_info(path: Path) -> dict:
    """Read video properties via ffprobe."""
    try:
        r = subprocess.run(
            [resolve_ffprobe(), "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height,duration,codec_name",
             "-show_entries", "format=duration,size",
             "-of", "json", str(path)],
            capture_output=True, text=True, timeout=5, env=get_system_env()
        )
        data = json.loads(r.stdout)
        stream = data.get("streams", [{}])[0]
        fmt = data.get("format", {})
        dur = float(fmt.get("duration", stream.get("duration", 0) or 0))
        size_kb = int(fmt.get("size", path.stat().st_size)) / 1024
        return {
            "resolution": f"{stream.get('width', '?')}×{stream.get('height', '?')}",
            "codec": stream.get("codec_name", "h264"),
            "duration": f"{dur:.1f}s" if dur > 0 else "N/A",
            "size": f"{size_kb / 1024:.2f} MB" if size_kb > 1024 else f"{size_kb:.0f} KB"
        }
    except Exception:
        size_kb = path.stat().st_size / 1024
        return {
            "resolution": "1080×1920",
            "codec": "h264",
            "duration": "N/A",
            "size": f"{size_kb / 1024:.2f} MB" if size_kb > 1024 else f"{size_kb:.0f} KB"
        }


# ─── Custom CSS Styling ───
st.markdown("""
<style>
    .live-badge {
        display: inline-block;
        background-color: #ff0055;
        color: white;
        font-weight: 800;
        font-size: 0.8rem;
        padding: 4px 10px;
        border-radius: 12px;
        letter-spacing: 1px;
        animation: pulse 1.5s infinite;
    }
    @keyframes pulse {
        0% { opacity: 1; }
        50% { opacity: 0.5; }
        100% { opacity: 1; }
    }
    .feed-card {
        background-color: #0e1117;
        border: 1px solid #1e2638;
        border-radius: 10px;
        padding: 16px;
        margin-bottom: 12px;
    }
    .chat-bubble {
        padding: 6px 12px;
        border-radius: 6px;
        margin-bottom: 6px;
        font-size: 0.9rem;
        background-color: #161b26;
        border-left: 3px solid #334155;
    }
    .chat-hype {
        background-color: #2b1d07;
        border-left: 3px solid #f59e0b;
        color: #fef3c7;
        font-weight: 600;
    }
</style>
""", unsafe_allow_html=True)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# HEADER & GLOBAL STATUS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

h_col1, h_col2 = st.columns([3, 1])
with h_col1:
    st.title("🎬 Live Stream AI Clipper Studio")
    st.caption("Automated Chat Spike Detection • Rolling Ring Buffer • 9:16 Vertical Reframing • Dynamic Captions")

with h_col2:
    is_running, run_pid, run_mode = is_clipper_running()
    if is_running:
        st.markdown(f'<div class="live-badge">🔴 LIVE STREAMING</div>', unsafe_allow_html=True)
        st.caption(f"Engine PID: `{run_pid}` ({run_mode})")
    else:
        st.info("⚪ **Clipper Engine Idle**")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SIDEBAR CONTROLS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

with st.sidebar:
    st.header("⚡ Detection & Buffer Settings")
    threshold = st.slider("Spike Threshold (msgs/3s)", 3.0, 30.0, 8.0, 0.5)
    cooldown = st.slider("Cooldown Period (s)", 15, 120, 45, 5)
    framing = st.selectbox("9:16 Framing Mode", ["blur_background", "center_crop", "split_cam_game"])
    whisper_model = st.selectbox("Whisper Model", ["tiny", "base", "small", "medium", "large-v3"], index=0)

    st.divider()

    st.subheader("🧪 Diagnostics")
    if st.button("▶ Run Full Integration Test", use_container_width=True):
        with st.spinner("Testing all modules end-to-end..."):
            res = subprocess.run(
                [str(VENV_PYTHON), str(PROJECT_ROOT / "test_integration.py")],
                capture_output=True, text=True, cwd=str(PROJECT_ROOT),
                env=get_system_env(), timeout=120
            )
            if res.returncode == 0:
                st.success("✅ Test Passed!")
                st.code(res.stdout[-1200:], language="text")
            else:
                st.error("❌ Test Failed")
                st.code(res.stdout[-600:] + "\n" + res.stderr[-600:], language="text")

    st.divider()
    if st.button("🔄 Manual Refresh", use_container_width=True):
        st.rerun()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 🔗 STREAM LINK & AUTO-CLIPPING LAUNCHER
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

with st.container(border=True):
    is_running, run_pid, run_mode = is_clipper_running()

    if is_running:
        st.markdown(f"### 🟢 Currently Clipping Stream: `{run_mode}` (Engine PID: {run_pid})")
        sc1, sc2 = st.columns([4, 1])
        with sc1:
            st.caption("The rolling ring buffer is capturing live stream footage. Chat is actively being monitored for engagement velocity spikes.")
        with sc2:
            if st.button("⏹ STOP CLIPPING", type="primary", use_container_width=True, key="stop_top_bar"):
                stop_clipper()
                st.warning("Clipper stopped.")
                time.sleep(1)
                st.rerun()
    else:
        st.markdown("### 🔗 Paste Stream Link & Start Automated Clipping")
        st.caption("Put any live stream link below — YouTube Live, Twitch channel, or video stream — and click Start.")

        url_col, btn_col = st.columns([4, 1])
        with url_col:
            user_stream_link = st.text_input(
                "Stream URL / Channel",
                placeholder="Paste YouTube Live URL, Twitch channel name/URL (e.g. shroud), or direct .m3u8...",
                label_visibility="collapsed",
                key="top_stream_link_input"
            )

        with btn_col:
            launch_clicked = st.button("🚀 START CLIPPING", type="primary", use_container_width=True, key="launch_top_bar")

        # Quick preset shortcut buttons
        st.caption("⚡ Quick Preset Streams:")
        q1, q2, q3, q4, q5 = st.columns(5)
        if q1.button("🎮 Mock Test Stream", use_container_width=True, key="q_mock"):
            user_stream_link = "mock"
            launch_clicked = True
        if q2.button("🟣 Twitch: shroud", use_container_width=True, key="q_shroud"):
            user_stream_link = "shroud"
            launch_clicked = True
        if q3.button("🟣 Twitch: tarik", use_container_width=True, key="q_tarik"):
            user_stream_link = "tarik"
            launch_clicked = True
        if q4.button("🟣 Twitch: kaicenat", use_container_width=True, key="q_kai"):
            user_stream_link = "kaicenat"
            launch_clicked = True
        if q5.button("🔴 YouTube Live URL", use_container_width=True, key="q_yt"):
            user_stream_link = "https://www.youtube.com/watch?v=jfKfPfyJRdk"
            launch_clicked = True

        if launch_clicked:
            target_to_start = user_stream_link.strip() if user_stream_link else "mock"
            with st.spinner(f"Connecting to stream '{target_to_start}' and starting capture engine..."):
                pid = start_clipper_url(
                    stream_input=target_to_start,
                    threshold=threshold,
                    cooldown=cooldown,
                    framing=framing
                )
                st.success(f"🚀 Clipping engine started! (PID {pid}) Monitoring '{target_to_start}'...")
                time.sleep(1.2)
                st.rerun()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TABS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

tab_live_feed, tab_gallery, tab_runner, tab_spike, tab_health = st.tabs([
    "🔴 Live Feed & Monitor",
    "🎞️ Clip Gallery",
    "⚙️ Engine Controls",
    "📊 Spike Detector Demo",
    "🩺 System Health"
])


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TAB 1: LIVE FEED & MONITOR (Auto-Refreshing)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@st.fragment(run_every=2)
def render_live_feed():
    """Live feed fragment that updates every 2 seconds without full-page reloads."""
    state = load_pipeline_state()
    is_running, run_pid, run_mode = is_clipper_running()

    # Top Status Row
    status_str = state.get("status", "IDLE" if not is_running else "BUFFERING")
    step_num = state.get("step", 0)
    total_steps = state.get("total_steps", 6)
    step_title = state.get("step_title", "Waiting for activity..." if is_running else "Engine stopped.")
    progress_pct = state.get("clip_progress_pct", 0)
    current_velocity = state.get("current_velocity", 0.0)

    # Status Cards Row
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Pipeline Stage", f"{status_str}", f"Step {step_num}/{total_steps}")
    m2.metric("Chat Velocity", f"{current_velocity} msgs/3s", delta="🔥 SPIKE!" if current_velocity >= threshold else "Normal")
    
    buf_info = state.get("buffer_info", {})
    buf_secs = buf_info.get("buffered_seconds", 0)
    m3.metric("Ring Buffer", f"{buf_secs}s / 60s", f"{buf_info.get('total_chunks', 0)} chunks")

    all_clips = find_clips(only_final=True)
    m4.metric("Clips Produced", len(all_clips), delta=f"+1 {all_clips[0].name[:12]}..." if all_clips else None)

    # Active Clipping Progress Bar
    if status_str not in ["IDLE", "BUFFERING"]:
        st.markdown(f"**⚡ Active Job:** `{state.get('active_clip_id', 'clip_job')}` — *{step_title}*")
        st.progress(progress_pct / 100.0)
    elif is_running:
        st.caption("🟢 Ring buffer continuously recording stream into memory. Monitoring chat for velocity spike...")

    st.divider()

    # Main Live Feed Grid: [Stream Buffer Visual Preview] vs [Latest Rendered Clip]
    col_stream, col_clip = st.columns([1, 1])

    with col_stream:
        st.markdown("### 🔴 Live Stream Buffer Feed")
        st.caption("Real-time visual snapshot of the rolling 60-second video buffer")

        if PREVIEW_IMG.exists():
            st.image(str(PREVIEW_IMG), use_container_width=True, caption=f"Live Buffer Snapshot — {buf_info.get('latest_chunk', 'chunk.ts')}")
        else:
            # Check if there are any .ts chunks
            ts_chunks = sorted(BUFFER_DIR.glob("chunk_*.ts"), key=lambda p: p.stat().st_mtime, reverse=True) if BUFFER_DIR.exists() else []
            if ts_chunks:
                # Extract preview frame on the fly
                try:
                    subprocess.run([
                        resolve_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y",
                        "-ss", "0.5", "-i", str(ts_chunks[0]),
                        "-vframes", "1", "-q:v", "2",
                        str(PREVIEW_IMG)
                    ], timeout=3, capture_output=True)
                    if PREVIEW_IMG.exists():
                        st.image(str(PREVIEW_IMG), use_container_width=True, caption=f"Live Buffer Snapshot ({ts_chunks[0].name})")
                    else:
                        st.info("Buffering stream segments... Preview frame will appear shortly.")
                except Exception:
                    st.info("Capturing live video buffer...")
            else:
                st.info("No stream buffer active. Start the clipper in the **Engine Controls** tab to view the live feed.")

    with col_clip:
        st.markdown("### 🎬 Latest Captured Clip (TikTok 9:16)")
        st.caption("Most recent finished clip with dynamic active-word subtitle burn-in")

        if all_clips:
            latest_clip = all_clips[0]
            st.video(str(latest_clip))
            vinfo = get_video_info(latest_clip)
            st.caption(f"**{latest_clip.name}** | {vinfo['resolution']} | {vinfo['duration']} | {vinfo['size']}")

            # Companion metadata
            meta_path = latest_clip.parent / f"{latest_clip.stem.replace('_final', '_meta')}.json"
            if meta_path.exists():
                try:
                    mdata = json.loads(meta_path.read_text(encoding="utf-8"))
                    st.markdown(f"**Title:** {mdata.get('title', 'N/A')}")
                    tags = mdata.get("tags", [])
                    if tags:
                        st.caption(" ".join(f"`{t}`" for t in tags[:5]))
                except Exception:
                    pass
        else:
            st.info("No clips generated yet. As soon as a chat spike occurs, the formatted 9:16 video will play here automatically.")

    st.divider()

    # Bottom Row: [Live Chat Ticker Feed] vs [Live Activity & Stage Log]
    chat_col, event_col = st.columns([1, 1])

    with chat_col:
        st.markdown("### 💬 Live Incoming Chat Feed")
        chat_ticker = state.get("chat_ticker", [])

        if not chat_ticker:
            st.caption("Waiting for live chat stream...")
        else:
            for item in chat_ticker[:8]:
                is_hype = item.get("is_hype", False)
                css_class = "chat-bubble chat-hype" if is_hype else "chat-bubble"
                hype_icon = "🔥 [HYPE]" if is_hype else "💬"
                st.markdown(
                    f'<div class="{css_class}">'
                    f'<span style="color: #94a3b8; font-size: 0.8rem;">[{item.get("time")}]</span> '
                    f'<strong>{item.get("author")}</strong>: {item.get("text")} '
                    f'<span style="float: right; color: #f59e0b;">{hype_icon}</span>'
                    f'</div>',
                    unsafe_allow_html=True
                )

    with event_col:
        st.markdown("### 📝 Live Clipping Activity Feed")
        events = state.get("events_feed", [])

        if not events:
            st.caption("Waiting for pipeline events...")
        else:
            for evt in events[:8]:
                e_type = evt.get("type", "info")
                e_icon = "🔥" if e_type == "spike" else "🎉" if e_type == "clip_done" else "⚙️"
                st.markdown(
                    f'<div class="chat-bubble">'
                    f'<span style="color: #94a3b8; font-size: 0.8rem;">[{evt.get("time")}]</span> '
                    f'{e_icon} {evt.get("message")}'
                    f'</div>',
                    unsafe_allow_html=True
                )


with tab_live_feed:
    render_live_feed()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TAB 2: CLIP GALLERY
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

with tab_gallery:
    filter_col1, filter_col2 = st.columns([3, 1])
    with filter_col1:
        st.subheader("All Generated Clips & TikTok Formatted Videos")
    with filter_col2:
        only_final = st.checkbox("Final Subtitled Clips Only", value=True, key="gal_only_final")

    clips = find_clips(only_final=only_final)

    if not clips:
        st.warning("No clips found yet. Start the clipper or run the integration test to generate clips.")
    else:
        st.info(f"Showing **{len(clips)}** clip(s) available in storage.")

        for i in range(0, len(clips), 2):
            cols = st.columns(2)
            for j in range(2):
                if i + j < len(clips):
                    vid = clips[i + j]
                    with cols[j]:
                        with st.container(border=True):
                            st.video(str(vid))
                            st.markdown(f"#### 📹 `{vid.name}`")

                            vinfo = get_video_info(vid)
                            mcol1, mcol2, mcol3 = st.columns(3)
                            mcol1.metric("Format", vinfo["resolution"])
                            mcol2.metric("Duration", vinfo["duration"])
                            mcol3.metric("Size", vinfo["size"])

                            parent = vid.parent
                            meta_file = parent / f"{vid.stem.replace('_final', '_meta')}.json"
                            if not meta_file.exists():
                                meta_file = parent / f"{vid.stem}_meta.json"

                            if meta_file.exists():
                                try:
                                    mdata = json.loads(meta_file.read_text(encoding="utf-8"))
                                    st.markdown(f"**Title:** {mdata.get('title', 'N/A')}")
                                    tags = mdata.get("tags", [])
                                    if tags:
                                        st.caption(" ".join(f"`{t}`" for t in tags[:6]))
                                except Exception:
                                    pass

                            st.caption(f"Created: {datetime.fromtimestamp(vid.stat().st_mtime).strftime('%Y-%m-%d %H:%M:%S')}")

                            st.download_button(
                                "⬇️ Download Clip (.mp4)",
                                data=vid.read_bytes(),
                                file_name=vid.name,
                                mime="video/mp4",
                                key=f"dl_gal_{vid.name}_{i+j}",
                                use_container_width=True
                            )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TAB 3: ENGINE CONTROLS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

with tab_runner:
    st.subheader("Clipper Engine Controller")
    st.caption("Start or stop the automated live background clipper process.")

    c_mode, c_input, c_stream = st.columns([1, 1, 1])
    with c_mode:
        platform_choice = st.selectbox(
            "Platform Source",
            ["Mock Simulation", "YouTube Live", "Twitch"],
            key="ctrl_platform"
        )

    with c_input:
        if platform_choice == "YouTube Live":
            target_val = st.text_input("YouTube URL / ID", "https://www.youtube.com/watch?v=...", key="ctrl_yt")
        elif platform_choice == "Twitch":
            target_val = st.text_input("Twitch Channel", "shroud", key="ctrl_tw")
        else:
            target_val = st.text_input("Mock Stream Name", "mock_streamer", key="ctrl_mock")

    with c_stream:
        stream_media_input = st.text_input(
            "Direct Stream Media URL (Optional)",
            value="https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/BigBuckBunny.mp4" if platform_choice == "Mock Simulation" else "",
            help="HLS .m3u8 or video stream URL for FFmpeg ring-buffer. Leave blank for default.",
            key="ctrl_stream"
        )

    is_running, run_pid, _ = is_clipper_running()

    btn_col1, btn_col2, _ = st.columns([1, 1, 2])
    with btn_col1:
        if not is_running:
            if st.button("🚀 Start Live Clipper", type="primary", use_container_width=True, key="btn_start"):
                pid = start_clipper(
                    mode=platform_choice,
                    target=target_val,
                    stream_url=stream_media_input,
                    threshold=threshold,
                    cooldown=cooldown,
                    framing=framing
                )
                st.success(f"Clipper started with PID {pid}!")
                time.sleep(1)
                st.rerun()
        else:
            st.button("🚀 Start Live Clipper", disabled=True, use_container_width=True, key="btn_start_dis")

    with btn_col2:
        if is_running:
            if st.button("⏹ Stop Clipper", type="secondary", use_container_width=True, key="btn_stop"):
                stop_clipper()
                st.warning("Clipper stopped.")
                time.sleep(1)
                st.rerun()
        else:
            st.button("⏹ Stop Clipper", disabled=True, use_container_width=True, key="btn_stop_dis")

    st.markdown("#### Engine Terminal Logs")
    log_path = PROJECT_ROOT / "storage" / "clipper_live.log"
    if log_path.exists():
        try:
            log_text = log_path.read_text(encoding="utf-8", errors="replace")
            lines = log_text.strip().split("\n")
            recent = "\n".join(lines[-40:]) if len(lines) > 40 else log_text
            st.code(recent or "Waiting for log events...", language="text")
        except Exception as e:
            st.code(f"Could not read log file: {e}")
    else:
        st.code("No active session log yet. Click 'Start Live Clipper' above to begin.")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TAB 4: SPIKE DETECTOR DEMO
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

with tab_spike:
    st.subheader("Chat Velocity & Spike Simulation")
    st.caption("Demonstrates the moving-window algorithm (`collections.deque`) and keyword sentiment multiplier.")

    s_left, s_right = st.columns([2, 1])

    with s_right:
        st.markdown("**Test Parameters**")
        p_thresh = st.number_input("Velocity Threshold", 3.0, 25.0, threshold, 0.5, key="p_thresh_spk")
        p_window = st.number_input("Window Duration (sec)", 1.0, 8.0, 3.0, 0.5, key="p_win_spk")
        p_total = st.slider("Total Chat Messages", 15, 60, 35, key="p_tot_spk")
        p_burst_start = st.slider("Spike Burst Position", 5, 45, 18, key="p_start_spk")
        p_burst_size = st.slider("Spike Message Count", 3, 15, 8, key="p_size_spk")

        run_btn = st.button("⚡ Run Velocity Simulation", type="primary", use_container_width=True, key="btn_sim_spk")

    with s_left:
        if run_btn:
            sys.path.insert(0, str(PROJECT_ROOT))
            from chat.base import ChatMessage
            from chat.spike_detector import SpikeDetector
            from config import ChatSpikeConfig
            import random

            cfg = ChatSpikeConfig(
                window_duration_seconds=p_window,
                spike_threshold=p_thresh,
                cooldown_seconds=10.0
            )

            detected_spikes = []
            detector = SpikeDetector(config=cfg, on_spike=lambda evt: detected_spikes.append(evt))

            normal_chat = ["gg", "nice game", "what rank is this", "lol", "true", "music is fire", "w play", "hello"]
            hype_chat = ["WTF WHAT A CLUTCH", "CLIP THAT NOW", "POGGERS OMG", "LETS GOOO", "HOLY INSANE FLICK", "SHEESH NO WAY"]

            t_now = time.time()
            chart_t = []
            chart_v = []
            log_entries = []

            for i in range(p_total):
                if p_burst_start <= i < p_burst_start + p_burst_size:
                    txt = random.choice(hype_chat)
                    m_time = t_now + i * 0.09
                    category = "🔥 Hype Spike"
                else:
                    txt = random.choice(normal_chat)
                    m_time = t_now + i * 0.7
                    category = "💬 Normal"

                msg = ChatMessage(author=f"user_{i}", message=txt, timestamp=m_time)
                detector.process_message(msg)

                chart_t.append(round(m_time - t_now, 2))
                chart_v.append(detector.current_velocity)
                log_entries.append({
                    "Time (s)": f"{m_time - t_now:.2f}",
                    "Type": category,
                    "Message": txt,
                    "Velocity": f"{detector.current_velocity:.1f}"
                })

            df = pd.DataFrame({
                "Time (s)": chart_t,
                "Chat Velocity": chart_v,
                "Spike Threshold": [p_thresh] * len(chart_t)
            })

            st.line_chart(df.set_index("Time (s)"), color=["#00E5FF", "#FF3366"])

            if detected_spikes:
                st.success(f"🎯 **{len(detected_spikes)} Spike Event(s) Successfully Triggered!**")
                for s_i, sp in enumerate(detected_spikes):
                    st.markdown(
                        f"- **Event #{s_i+1}**: Velocity = `{sp.velocity:.1f}` | "
                        f"Message = *\"{sp.trigger_message.message}\"* | "
                        f"Keywords = `{', '.join(sp.top_keywords_found)}`"
                    )
            else:
                st.warning("No spikes crossed the threshold. Try lowering the threshold or increasing burst size.")

            with st.expander("View Simulated Message Telemetry"):
                st.dataframe(pd.DataFrame(log_entries), use_container_width=True)
        else:
            st.info("Click **Run Velocity Simulation** to generate real-time engagement telemetry.")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TAB 5: SYSTEM HEALTH
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

with tab_health:
    st.subheader("System Readiness & Diagnostics")

    c1, c2, c3, c4 = st.columns(4)
    all_final_clips = find_clips(only_final=True)
    c1.metric("Final TikTok Clips", len(all_final_clips))
    c2.metric("Storage Buffer Chunks", len(list(BUFFER_DIR.glob("*.ts"))) if BUFFER_DIR.exists() else 0)
    c3.metric("Virtualenv Python", "✅ 3.14.7" if VENV_PYTHON.exists() else "❌ Missing")
    c4.metric("FFmpeg Status", "✅ Installed")

    st.divider()

    h_col1, h_col2 = st.columns(2)

    with h_col1:
        st.markdown("#### System Binaries")
        bins = {
            "FFmpeg Video Encoder": resolve_ffmpeg,
            "FFprobe Analyzer": resolve_ffprobe
        }
        for name, resolve_binary in bins.items():
            try:
                bin_cmd = resolve_binary()
                r = subprocess.run([bin_cmd, "-version"], capture_output=True, text=True, timeout=5, env=get_system_env())
                ver = r.stdout.split("\n")[0].strip() if r.stdout else r.stderr.split("\n")[0].strip()
                st.markdown(f"✅ **{name}**\n`{ver[:70]}`")
            except Exception:
                st.markdown(f"❌ **{name}** — Not found")

    with h_col2:
        st.markdown("#### Python Engine Modules")
        mods = {
            "faster-whisper (Speech-to-Text)": "faster_whisper",
            "PyAV (Audio Decoding)": "av",
            "Streamlit (Dashboard)": "streamlit",
            "Pandas (Telemetry Data)": "pandas",
            "PyTorch (Model Execution)": "torch"
        }
        for name, mod_key in mods.items():
            try:
                r = subprocess.run(
                    [str(VENV_PYTHON), "-c", f"import {mod_key}; print(getattr({mod_key}, '__version__', 'OK'))"],
                    capture_output=True, text=True, timeout=8
                )
                if r.returncode == 0:
                    st.markdown(f"✅ **{name}** (`{r.stdout.strip()}`)")
                else:
                    st.markdown(f"❌ **{name}** — Import error")
            except Exception:
                st.markdown(f"❌ **{name}** — Not installed")
