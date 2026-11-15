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
- **Look** (right panel): letterbox bars, vignette, grain, teal/orange grade, accent colour.
- **Export MP4**: renders with FFmpeg. Your project autosaves in `data/project.json`.

Notes: your originals are never changed. Text clips export with a fade in/out (the preview shows the full animation).
