# Vlog Editor (Flask + FFmpeg)

## Install once
1. Install Python 3.8+  (python.org)
2. Install FFmpeg and make sure `ffmpeg -version` works in a terminal
   (Windows: `winget install ffmpeg`   Mac: `brew install ffmpeg`   Linux: `sudo apt install ffmpeg`)

## Run
Windows: double-click `run.bat`    Mac/Linux: `./run.sh`
Then open http://127.0.0.1:5000 in Chrome or Edge.

## Using it
- Drop videos / photos / music into the Media panel. Wait for "preparing…" to finish (makes fast preview copies).
- Click **+** (or double-click) to put media on the timeline at the red playhead. Shift+click puts it on Video 2.
- Drag clips to move, drag their edges to trim, drag the ruler to scrub.
- **S** split · **Delete** remove · **Shift+Delete** ripple delete · **Space** play · **Ctrl+Z** undo · **+/-** zoom
- **Remove silences**: select a talking clip, it cuts out the quiet gaps automatically.
- **+ Add text**: cinematic title, lower third, chapter card, subtitle or route tracker on the Text track.
- **Colour** (select a video clip): brightness, contrast, saturation, warm/cool, sharpen, **LUT looks** (9 built in: cinematic teal & orange, warm vlog, golden hour, cool & moody, vivid, faded film, matte, B&W, clean) with a strength slider, and **Auto enhance**.
- **Your own LUT**: Look panel -> "Load your own .cube LUT" (3D .cube files). Apply it to the whole video or per clip.
- **Look** (right panel): whole-video LUT grade + strength, letterbox bars, vignette, grain, accent colour.
- **Sound**: volume, fades, mute, **Clean voice** (noise cut, EQ, compressor), and **Auto-lower under my voice** for music (ducking).
- **Background sound**: left panel -> generate river / wind / rain / forest / cinematic pad (synthetic). Real music: add your own files.
- **Get audio from a video**: click the ♪ button on a video in the Media list (makes a separate audio file), or select a clip and press **Detach audio** (puts the sound on the Audio track so you can cut / move / replace it).
- **Replace**: select a clip -> Replace / tools -> swap the picture or the sound for other media, keeping the timing.
- **D** duplicate · **Q / W** trim start / end to the playhead.
- **Export MP4**: renders with FFmpeg (optional YouTube loudness -14 LUFS). Your project autosaves in `data/project.json`.

Notes: your originals are never changed. Text clips export with a fade in/out (the preview shows the full animation).
