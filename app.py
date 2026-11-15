"""Parvati Vlog Editor - a small multi-track video editor.
Flask serves the editor UI and does the heavy work with FFmpeg:
upload, proxies, thumbnails, waveforms, silence detection and final export.
Run:  python app.py   then open http://127.0.0.1:5000
Needs: Python 3.8+, Flask, and ffmpeg/ffprobe on your PATH."""
import os, json, uuid, subprocess, threading, re, shutil, base64, time, array
from flask import Flask, request, jsonify, send_from_directory, send_file, abort

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, 'data')
D_MEDIA, D_PROXY, D_THUMB, D_PEAK, D_OUT, D_TMP = [os.path.join(DATA, n) for n in ('media', 'proxy', 'thumb', 'peaks', 'out', 'tmp')]
for d in (D_MEDIA, D_PROXY, D_THUMB, D_PEAK, D_OUT, D_TMP): os.makedirs(d, exist_ok=True)
FFMPEG = shutil.which('ffmpeg') or 'ffmpeg'
FFPROBE = shutil.which('ffprobe') or 'ffprobe'
IMG_EXT = {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.gif'}
AUD_EXT = {'.mp3', '.wav', '.m4a', '.aac', '.ogg', '.flac', '.opus', '.wma'}

app = Flask(__name__, static_folder='static', static_url_path='/static')
app.config['MAX_CONTENT_LENGTH'] = 8 * 1024 ** 3
lock = threading.Lock()
MEDIA_DB = os.path.join(DATA, 'media.json')
PROJ = os.path.join(DATA, 'project.json')
media = []
if os.path.exists(MEDIA_DB):
    try: media = json.load(open(MEDIA_DB, encoding='utf-8'))
    except Exception: media = []
for m in media:                                   # a restart interrupts any unfinished proxy job
    if m.get('status') == 'processing': m['status'] = 'ready' if m.get('proxy') and os.path.exists(os.path.join(D_PROXY, m['proxy'])) else 'error'
def persist():
    with lock: json.dump(media, open(MEDIA_DB, 'w', encoding='utf-8'), ensure_ascii=False)
def get_media(mid):
    for m in media:
        if m['id'] == mid: return m
def run(cmd, **kw): return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kw)

def probe(path):
    r = run([FFPROBE, '-v', 'error', '-show_entries', 'stream=codec_type,codec_name,width,height,duration:format=duration', '-of', 'json', path])
    j = json.loads(r.stdout or '{}'); st = j.get('streams', [])
    v = next((s for s in st if s.get('codec_type') == 'video'), None); a = next((s for s in st if s.get('codec_type') == 'audio'), None)
    dur = float(j.get('format', {}).get('duration') or (v or a or {}).get('duration') or 0)
    return v, a, dur

def make_proxy(m):
    src = os.path.join(D_MEDIA, m['file'])
    try:
        if m['kind'] == 'video':
            out = m['id'] + '.mp4'
            cmd = [FFMPEG, '-y', '-i', src, '-vf', 'scale=-2:540', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '27', '-g', '15', '-pix_fmt', 'yuv420p']
            cmd += ['-c:a', 'aac', '-b:a', '96k'] if m['hasAudio'] else ['-an']
            r = run(cmd + ['-movflags', '+faststart', os.path.join(D_PROXY, out)])
        elif m['kind'] == 'audio':
            out = m['id'] + '.m4a'
            r = run([FFMPEG, '-y', '-i', src, '-vn', '-c:a', 'aac', '-b:a', '128k', os.path.join(D_PROXY, out)])
        else:
            out = m['id'] + '.jpg'
            r = run([FFMPEG, '-y', '-i', src, '-vf', 'scale=1280:-2:force_original_aspect_ratio=decrease', '-frames:v', '1', os.path.join(D_PROXY, out)])
        m['proxy'] = out; m['status'] = 'ready' if r.returncode == 0 else 'error'
    except Exception:
        m['status'] = 'error'
    persist()

@app.route('/')
def index(): return send_from_directory(app.static_folder, 'index.html')

@app.route('/api/media', methods=['GET'])
def list_media(): return jsonify(media)

@app.route('/api/upload', methods=['POST'])
def upload():
    out = []
    for f in request.files.getlist('files'):
        ext = os.path.splitext(f.filename)[1].lower() or '.bin'
        mid = uuid.uuid4().hex[:10]; fn = mid + ext; path = os.path.join(D_MEDIA, fn); f.save(path)
        v, a, dur = probe(path)
        if ext in IMG_EXT: kind, dur = 'image', 5.0
        elif v and (dur > 0): kind = 'video'
        elif a: kind = 'audio'
        else: os.remove(path); continue
        m = dict(id=mid, name=f.filename, kind=kind, dur=round(dur, 3), w=(v or {}).get('width', 0), h=(v or {}).get('height', 0), hasAudio=bool(a), file=fn, proxy=None, thumb=None, status='processing')
        if kind in ('video', 'image'):
            th = mid + '.jpg'; run([FFMPEG, '-y', '-ss', '0.5' if kind == 'video' and dur > 1 else '0', '-i', path, '-frames:v', '1', '-vf', 'scale=320:-2', os.path.join(D_THUMB, th)])
            if os.path.exists(os.path.join(D_THUMB, th)): m['thumb'] = th
        media.append(m); persist(); out.append(m)
        threading.Thread(target=make_proxy, args=(m,), daemon=True).start()
    return jsonify(out)

@app.route('/api/media/<mid>', methods=['DELETE'])
def del_media(mid):
    m = get_media(mid)
    if m:
        for d, k in ((D_MEDIA, 'file'), (D_PROXY, 'proxy'), (D_THUMB, 'thumb')):
            if m.get(k):
                try: os.remove(os.path.join(d, m[k]))
                except OSError: pass
        media.remove(m); persist()
    return jsonify(ok=True)

@app.route('/file/<kind>/<name>')
def files(kind, name):
    d = {'media': D_MEDIA, 'proxy': D_PROXY, 'thumb': D_THUMB, 'out': D_OUT}.get(kind)
    if not d: abort(404)
    return send_from_directory(d, name, conditional=True)

@app.route('/api/project', methods=['GET', 'POST'])
def project():
    if request.method == 'POST':
        with lock: json.dump(request.get_json(force=True), open(PROJ, 'w', encoding='utf-8'), ensure_ascii=False)
        return jsonify(ok=True)
    if os.path.exists(PROJ): return send_file(PROJ, mimetype='application/json')
    return jsonify(None)

@app.route('/api/peaks/<mid>')
def peaks(mid):                                   # 50 peaks per second for the waveform
    m = get_media(mid)
    if not m or not m.get('hasAudio'): return jsonify([])
    cache = os.path.join(D_PEAK, mid + '.json')
    if os.path.exists(cache): return send_file(cache, mimetype='application/json')
    p = subprocess.Popen([FFMPEG, '-v', 'error', '-i', os.path.join(D_MEDIA, m['file']), '-vn', '-ac', '1', '-ar', '8000', '-f', 's16le', '-'], stdout=subprocess.PIPE)
    raw = p.stdout.read(); p.wait()
    s = array.array('h'); s.frombytes(raw[:len(raw) // 2 * 2])
    out = [round(max(abs(x) for x in s[i:i + 160]) / 32768, 3) for i in range(0, len(s), 160)] if len(s) else []
    json.dump(out, open(cache, 'w')); return jsonify(out)

@app.route('/api/silence/<mid>')
def silence(mid):
    m = get_media(mid)
    if not m or not m.get('hasAudio'): return jsonify(silences=[], dur=0)
    db = float(request.args.get('db', -32)); md = float(request.args.get('min', .6))
    r = run([FFMPEG, '-hide_banner', '-i', os.path.join(D_MEDIA, m['file']), '-vn', '-af', 'silencedetect=noise=%ddB:d=%s' % (db, md), '-f', 'null', '-'])
    log = r.stderr.decode('utf-8', 'ignore'); sil = []; cur = None
    for line in log.splitlines():
        a = re.search(r'silence_start: ([\d.]+)', line); b = re.search(r'silence_end: ([\d.]+)', line)
        if a: cur = float(a.group(1))
        if b and cur is not None: sil.append([cur, float(b.group(1))]); cur = None
    if cur is not None: sil.append([cur, m['dur']])
    return jsonify(silences=sil, dur=m['dur'])

# ----------------------------- export -----------------------------
JOBS = {}
def atempo_chain(s):
    f = []
    while s > 2.0: f.append('atempo=2.0'); s /= 2.0
    while s < 0.5: f.append('atempo=0.5'); s /= 0.5
    f.append('atempo=%.5f' % s); return ','.join(f)
def clen(c): return max(0.04, (c['out'] - c['in']) / max(c.get('speed', 1), .05))
def dec(durl, path):
    open(path, 'wb').write(base64.b64decode(durl.split(',', 1)[1]))

def build_export(job, proj, overlays, fx_png, opts):
    tmp = os.path.join(D_TMP, job); os.makedirs(tmp, exist_ok=True)
    W, H = (1920, 1080) if opts.get('res', '1080') == '1080' else (1280, 720); fps = int(opts.get('fps', 30)); fx = proj.get('fx', {})
    clips = proj['clips']
    D = max(c['start'] + clen(c) for c in clips)
    inputs = ['-f', 'lavfi', '-t', '%.3f' % D, '-i', 'color=c=black:s=%dx%d:r=%d' % (W, H, fps), '-f', 'lavfi', '-t', '%.3f' % D, '-i', 'anullsrc=r=48000:cl=stereo']
    n = 2; vf = []; af = []; vlabels = []; alabels = []
    order = {'V1': 0, 'V2': 1, 'T1': 2}
    for c in sorted([c for c in clips if c['track'] in order], key=lambda c: (order[c['track']], c['start'])):
        L = clen(c); sp = max(c.get('speed', 1), .05); fi = min(c.get('fadeIn', 0), L / 2); fo = min(c.get('fadeOut', 0), L / 2)
        if c['track'] == 'T1':
            png = os.path.join(tmp, c['id'] + '.png')
            if c['id'] not in overlays: continue
            dec(overlays[c['id']], png)
            inputs += ['-loop', '1', '-framerate', str(fps), '-t', '%.3f' % L, '-i', png]
            chain = '[%d:v]scale=%d:%d,format=rgba,fade=t=in:st=0:d=0.9:alpha=1,fade=t=out:st=%.3f:d=0.9:alpha=1' % (n, W, H, max(0, L - .9))
        else:
            m = next((m for m in media if m['id'] == c['media']), None)
            if not m: continue
            src = os.path.join(D_MEDIA, m['file'])
            fit = ('scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d' % (W, H, W, H)) if c.get('fit') == 'cover' else ('scale=%d:%d:force_original_aspect_ratio=decrease,pad=%d:%d:(ow-iw)/2:(oh-ih)/2:black' % (W, H, W, H))
            if m['kind'] == 'image':
                inputs += ['-loop', '1', '-framerate', str(fps), '-t', '%.3f' % L, '-i', src]; chain = '[%d:v]%s,setsar=1,fps=%d,format=rgba' % (n, fit, fps)
            else:
                inputs += ['-ss', '%.3f' % c['in'], '-t', '%.3f' % (c['out'] - c['in']), '-i', src]
                chain = '[%d:v]setpts=(PTS-STARTPTS)/%.5f,%s,setsar=1,fps=%d,format=rgba' % (n, sp, fit, fps)
                if m['hasAudio'] and not c.get('mute') and c['track'] in ('V1', 'V2'):
                    a = '[%d:a]%s,asetpts=PTS-STARTPTS,volume=%.3f' % (n, atempo_chain(sp), c.get('vol', 1))
                    if fi: a += ',afade=t=in:st=0:d=%.3f' % fi
                    if fo: a += ',afade=t=out:st=%.3f:d=%.3f' % (max(0, L - fo), fo)
                    af.append(a + ',aresample=48000,adelay=%d|%d,apad[a%d]' % (c['start'] * 1000, c['start'] * 1000, n)); alabels.append('[a%d]' % n)
            if fi: chain += ',fade=t=in:st=0:d=%.3f:alpha=1' % fi
            if fo: chain += ',fade=t=out:st=%.3f:d=%.3f:alpha=1' % (max(0, L - fo), fo)
        vf.append(chain + ',setpts=PTS-STARTPTS+%.3f/TB[v%d]' % (c['start'], n)); vlabels.append((n, c['start'], c['start'] + L)); n += 1
    for c in [c for c in clips if c['track'] in ('A1', 'A2')]:
        m = next((m for m in media if m['id'] == c['media']), None)
        if not m or not m['hasAudio']: continue
        L = clen(c); sp = max(c.get('speed', 1), .05); fi = min(c.get('fadeIn', 0), L / 2); fo = min(c.get('fadeOut', 0), L / 2)
        inputs += ['-ss', '%.3f' % c['in'], '-t', '%.3f' % (c['out'] - c['in']), '-i', os.path.join(D_MEDIA, m['file'])]
        a = '[%d:a]%s,asetpts=PTS-STARTPTS,volume=%.3f' % (n, atempo_chain(sp), c.get('vol', 1))
        if fi: a += ',afade=t=in:st=0:d=%.3f' % fi
        if fo: a += ',afade=t=out:st=%.3f:d=%.3f' % (max(0, L - fo), fo)
        af.append(a + ',aresample=48000,adelay=%d|%d,apad[a%d]' % (c['start'] * 1000, c['start'] * 1000, n)); alabels.append('[a%d]' % n); n += 1
    cur = '[0:v]'
    for i, (idx, s, e) in enumerate(vlabels):
        vf.append("%s[v%d]overlay=eof_action=pass:enable='between(t,%.3f,%.3f)'[o%d]" % (cur, idx, s, e, i)); cur = '[o%d]' % i
    if fx_png:
        p = os.path.join(tmp, 'fx.png'); dec(fx_png, p); inputs += ['-loop', '1', '-framerate', str(fps), '-t', '%.3f' % D, '-i', p]
        vf.append('[%d:v]scale=%d:%d,format=rgba[fxl]' % (n, W, H)); vf.append('%s[fxl]overlay=eof_action=pass[ofx]' % cur); cur = '[ofx]'; n += 1
    post = []
    if fx.get('grade'): post.append('eq=contrast=1.05:saturation=1.12,colorbalance=rs=-.04:bs=.07:rh=.07:bh=-.05')
    if fx.get('grain'): post.append('noise=alls=6:allf=t')
    post.append('format=yuv420p')
    vf.append('%s%s[vout]' % (cur, ','.join(post)))
    af.append('[1:a]atrim=0:%.3f[sil]' % D)
    allA = '[sil]' + ''.join(alabels)
    af.append('%samix=inputs=%d:duration=first:normalize=0,alimiter=limit=0.97[aout]' % (allA, len(alabels) + 1))
    out = os.path.join(D_OUT, job + '.mp4')
    cmd = [FFMPEG, '-y', '-hide_banner', '-nostats', '-progress', 'pipe:1'] + inputs + ['-filter_complex', ';'.join(vf + af), '-map', '[vout]', '-map', '[aout]', '-t', '%.3f' % D,
           '-c:v', 'libx264', '-preset', opts.get('preset', 'medium'), '-crf', str(opts.get('crf', 18)), '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', out]
    open(os.path.join(tmp, 'cmd.txt'), 'w').write(' '.join('"%s"' % x if ' ' in x or ';' in x else x for x in cmd))
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    tail = []
    for line in p.stdout:
        tail = (tail + [line])[-25:]
        m = re.match(r'out_time_(?:us|ms)=(\d+)', line)
        if m: JOBS[job]['progress'] = min(.99, int(m.group(1)) / 1e6 / D)
    p.wait()
    if p.returncode == 0 and os.path.exists(out): JOBS[job].update(state='done', progress=1, file=job + '.mp4', size=os.path.getsize(out))
    else: JOBS[job].update(state='error', error=''.join(tail))
    shutil.rmtree(tmp, ignore_errors=True)

@app.route('/api/export', methods=['POST'])
def export():
    body = request.get_json(force=True); proj = body['project']
    if not proj.get('clips'): return jsonify(error='Timeline is empty'), 400
    job = uuid.uuid4().hex[:8]; JOBS[job] = dict(state='running', progress=0)
    def go():
        try: build_export(job, proj, body.get('overlays', {}), body.get('fx'), body.get('opts', {}))
        except Exception as e: JOBS[job].update(state='error', error=repr(e))
    threading.Thread(target=go, daemon=True).start()
    return jsonify(job=job)

@app.route('/api/export/<job>')
def export_status(job): return jsonify(JOBS.get(job) or dict(state='error', error='unknown job'))

if __name__ == '__main__':
    print('\n  Vlog editor running →  http://127.0.0.1:5000\n  (ffmpeg: %s)\n' % FFMPEG)
    app.run(host='127.0.0.1', port=5000, threaded=True)
