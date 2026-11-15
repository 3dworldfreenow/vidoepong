"""Parvati Vlog Editor - a small multi-track video editor.
Flask serves the editor UI and does the heavy work with FFmpeg:
upload, proxies, thumbnails, waveforms, silence detection and final export.
Run:  python app.py   then open http://127.0.0.1:5000
Needs: Python 3.8+, Flask, and ffmpeg/ffprobe on your PATH."""
import os, json, uuid, subprocess, threading, re, shutil, base64, time, array
from flask import Flask, request, jsonify, send_from_directory, send_file, abort

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, 'data')
D_MEDIA, D_PROXY, D_THUMB, D_PEAK, D_OUT, D_TMP, D_LUT = [os.path.join(DATA, n) for n in ('media', 'proxy', 'thumb', 'peaks', 'out', 'tmp', 'luts')]
for d in (D_MEDIA, D_PROXY, D_THUMB, D_PEAK, D_OUT, D_TMP, D_LUT): os.makedirs(d, exist_ok=True)
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
    d = {'media': D_MEDIA, 'proxy': D_PROXY, 'thumb': D_THUMB, 'out': D_OUT, 'lut': D_LUT}.get(kind)
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

# ----------------------------- colour: built-in LUTs -----------------------------
def _clamp(v): return 0.0 if v < 0 else 1.0 if v > 1 else v
def grade(rgb, sat=1.0, con=1.0, gam=1.0, temp=0.0, sh=(0, 0, 0), hi=(0, 0, 0), fade=0.0, bw=False):
    r, g, b = rgb
    r, g, b = r + temp * .10, g + temp * .02, b - temp * .10
    l = .2126 * r + .7152 * g + .0722 * b
    w = _clamp(l)
    r += sh[0] * (1 - w) + hi[0] * w; g += sh[1] * (1 - w) + hi[1] * w; b += sh[2] * (1 - w) + hi[2] * w
    l = .2126 * r + .7152 * g + .0722 * b
    if bw: r = g = b = l
    else: r, g, b = l + (r - l) * sat, l + (g - l) * sat, l + (b - l) * sat
    out = []
    for c in (r, g, b):
        c = _clamp(c) ** (1 / gam)
        c = .5 + (c - .5) * con
        c = fade + c * (1 - fade)
        out.append(_clamp(c))
    return out
PRESETS = {
    'cinematic':  ('Cinematic teal & orange', dict(sat=1.12, con=1.14, sh=(-.03, .01, .05), hi=(.05, .02, -.05))),
    'warm_vlog':  ('Warm vlog', dict(sat=1.15, con=1.06, temp=.45, gam=1.04)),
    'golden':     ('Golden hour', dict(sat=1.22, con=1.1, temp=.8, hi=(.05, .03, -.06))),
    'cool_moody': ('Cool & moody', dict(sat=.88, con=1.16, temp=-.6, gam=.94, sh=(-.02, 0, .04))),
    'vivid':      ('Vivid nature', dict(sat=1.45, con=1.1, gam=1.03)),
    'faded':      ('Faded film', dict(sat=.85, con=.96, fade=.07, hi=(.03, .015, -.02))),
    'matte':      ('Soft matte', dict(sat=.92, con=1.04, fade=.05, temp=.15)),
    'bw':         ('Black & white', dict(bw=True, con=1.22)),
    'clean':      ('Clean & fresh', dict(sat=1.06, con=1.04, gam=1.05)),
}
def build_luts(N=25):
    for key, (label, kw) in PRESETS.items():
        p = os.path.join(D_LUT, key + '.cube')
        if os.path.exists(p): continue
        lines = ['TITLE "%s"' % label, 'LUT_3D_SIZE %d' % N]
        for b in range(N):
            for g in range(N):
                for r in range(N):
                    o = grade((r / (N - 1), g / (N - 1), b / (N - 1)), **kw)
                    lines.append('%.5f %.5f %.5f' % tuple(o))
        open(p, 'w').write('\n'.join(lines) + '\n')
build_luts()
LUT_DB = os.path.join(DATA, 'luts.json')
def user_luts():
    try: return json.load(open(LUT_DB, encoding='utf-8'))
    except Exception: return []

@app.route('/api/luts')
def luts():
    out = [dict(id=k, label=v[0], file=k + '.cube', builtin=True) for k, v in PRESETS.items()]
    return jsonify(out + user_luts())

@app.route('/api/lut', methods=['POST'])
def add_lut():
    f = request.files.get('file')
    if not f: return jsonify(error='No file'), 400
    txt = f.read().decode('utf-8', 'ignore')
    if 'LUT_3D_SIZE' not in txt: return jsonify(error='Only 3D .cube LUT files are supported'), 400
    lid = 'u' + uuid.uuid4().hex[:6]; open(os.path.join(D_LUT, lid + '.cube'), 'w').write(txt)
    ent = dict(id=lid, label=os.path.splitext(f.filename)[0][:40], file=lid + '.cube', builtin=False)
    db = user_luts(); db.append(ent); json.dump(db, open(LUT_DB, 'w', encoding='utf-8'))
    return jsonify(ent)

@app.route('/api/analyze/<mid>')            # simple auto-enhance: measure brightness / range / saturation
def analyze(mid):
    m = get_media(mid)
    if not m or m['kind'] == 'audio': return jsonify(error='no picture'), 400
    t0 = float(request.args.get('t', 0)); d = min(float(request.args.get('d', 8)), 12)
    src = os.path.join(D_MEDIA, m['file'])
    cmd = [FFMPEG, '-hide_banner', '-ss', str(t0), '-t', str(d), '-i', src, '-vf', 'fps=2,scale=480:-2,signalstats,metadata=print:file=-', '-an', '-f', 'null', '-']
    out = run(cmd).stdout.decode('utf-8', 'ignore'); vals = {}
    for k in ('YLOW', 'YAVG', 'YHIGH', 'SATAVG'):
        v = [float(x) for x in re.findall(r'lavfi\.signalstats\.%s=([\d.]+)' % k, out)]
        if v: vals[k] = sum(v) / len(v)
    if 'YAVG' not in vals: return jsonify(error='could not analyse'), 400
    rng = max(40, vals['YHIGH'] - vals['YLOW'])
    adj = dict(brightness=round(max(-.18, min(.22, (112 - vals['YAVG']) / 255 * .8)), 3),
               contrast=round(max(.92, min(1.35, 190 / rng)), 3),
               saturation=round(max(.9, min(1.5, 52 / (vals.get('SATAVG', 50) + 1))), 3))
    return jsonify(adj=adj, stats=vals)

@app.route('/api/extract/<mid>', methods=['POST'])   # pull the sound out of a video into the library
def extract(mid):
    m = get_media(mid)
    if not m or not m.get('hasAudio'): return jsonify(error='This clip has no audio'), 400
    nid = uuid.uuid4().hex[:10]; fn = nid + '.m4a'; path = os.path.join(D_MEDIA, fn)
    r = run([FFMPEG, '-y', '-i', os.path.join(D_MEDIA, m['file']), '-vn', '-c:a', 'aac', '-b:a', '192k', path])
    if r.returncode: return jsonify(error='extract failed'), 500
    _, a, dur = probe(path)
    n = dict(id=nid, name=os.path.splitext(m['name'])[0] + ' (audio).m4a', kind='audio', dur=round(dur, 3), w=0, h=0, hasAudio=True, file=fn, proxy=fn, thumb=None, status='ready')
    shutil.copy(path, os.path.join(D_PROXY, fn)); media.append(n); persist(); return jsonify(n)

AMB = {   # synthetic background sounds (no downloads needed)
    'river': "anoisesrc=c=pink:r=44100:a=0.5[n1];anoisesrc=c=brown:r=44100:a=0.7[n2];[n1]highpass=f=350,lowpass=f=5200,tremolo=f=0.35:d=0.35[a];[n2]lowpass=f=420[b];[a][b]amix=inputs=2:normalize=0,volume=0.9",
    'wind': "anoisesrc=c=brown:r=44100:a=0.8,lowpass=f=900,highpass=f=60,tremolo=f=0.12:d=0.85,volume=1.4",
    'rain': "anoisesrc=c=white:r=44100:a=0.25,highpass=f=1600,lowpass=f=9500,tremolo=f=7:d=0.08,volume=0.9",
    'forest': "anoisesrc=c=pink:r=44100:a=0.18,highpass=f=800,lowpass=f=6000,tremolo=f=0.2:d=0.5[n];anoisesrc=c=brown:r=44100:a=0.4,lowpass=f=300[b];[n][b]amix=inputs=2:normalize=0",
    'pad': "sine=f=110:r=44100[a];sine=f=164.81:r=44100[b];sine=f=220.5:r=44100[c];sine=f=329.6:r=44100[d];[a][b][c][d]amix=inputs=4:normalize=0,tremolo=f=0.18:d=0.45,lowpass=f=1400,aecho=0.8:0.7:420|700:0.45|0.3,volume=0.35",
}
AMB_LABEL = {'river': 'River stream', 'wind': 'Soft wind', 'rain': 'Rain', 'forest': 'Forest air', 'pad': 'Cinematic pad'}
@app.route('/api/ambience', methods=['POST'])
def ambience():
    b = request.get_json(force=True); kind = b.get('kind'); sec = max(10, min(int(b.get('seconds', 60)), 600))
    if kind not in AMB: return jsonify(error='unknown sound'), 400
    nid = uuid.uuid4().hex[:10]; fn = nid + '.m4a'; path = os.path.join(D_MEDIA, fn)
    r = run([FFMPEG, '-y', '-f', 'lavfi', '-t', str(sec), '-i', AMB[kind].replace(';', ';', 1), '-t', str(sec), '-af', 'afade=t=in:d=1.5,afade=t=out:st=%d:d=2' % (sec - 2), '-c:a', 'aac', '-b:a', '160k', path]) \
        if ';' not in AMB[kind] else run([FFMPEG, '-y', '-filter_complex', AMB[kind] + ',atrim=0:%d,afade=t=in:d=1.5,afade=t=out:st=%d:d=2' % (sec, sec - 2), '-t', str(sec), '-c:a', 'aac', '-b:a', '160k', path])
    if r.returncode: return jsonify(error='could not generate: ' + r.stderr.decode('utf-8', 'ignore')[-300:]), 500
    n = dict(id=nid, name='%s (%ds).m4a' % (AMB_LABEL[kind], sec), kind='audio', dur=float(sec), w=0, h=0, hasAudio=True, file=fn, proxy=fn, thumb=None, status='ready')
    shutil.copy(path, os.path.join(D_PROXY, fn)); media.append(n); persist(); return jsonify(n)

# ----------------------------- export -----------------------------
JOBS = {}
def atempo_chain(s):
    f = []
    while s > 2.0: f.append('atempo=2.0'); s /= 2.0
    while s < 0.5: f.append('atempo=0.5'); s /= 0.5
    f.append('atempo=%.5f' % s); return ','.join(f)
def clen(c): return max(0.04, (c['out'] - c['in']) / max(c.get('speed', 1), .05))
def dec(durl, path): open(path, 'wb').write(base64.b64decode(durl.split(',', 1)[1]))
VOICE_FX = 'highpass=f=90,afftdn=nf=-28,acompressor=threshold=0.12:ratio=3:attack=5:release=120,equalizer=f=3200:t=q:w=1.2:g=2,dynaudnorm=f=200:g=5'

def lut_stmts(i, o, lutfile, amt, tag):
    if amt >= .99: return ['%slut3d=file=%s:interp=tetrahedral%s' % (i, lutfile, o)]
    return ['%ssplit=2[%sa][%sb]' % (i, tag, tag), '[%sb]lut3d=file=%s:interp=tetrahedral[%sc]' % (tag, lutfile, tag),
            '[%sc][%sa]blend=all_mode=normal:all_opacity=%.3f%s' % (tag, tag, amt, o)]

def build_export(job, proj, overlays, fx_png, opts):
    tmp = os.path.join(D_TMP, job); os.makedirs(tmp, exist_ok=True)
    W, H = (1920, 1080) if opts.get('res', '1080') == '1080' else (1280, 720); fps = int(opts.get('fps', 30)); fx = proj.get('fx', {})
    clips = proj['clips']; D = max(c['start'] + clen(c) for c in clips)
    inputs = ['-f', 'lavfi', '-t', '%.3f' % D, '-i', 'color=c=black:s=%dx%d:r=%d' % (W, H, fps), '-f', 'lavfi', '-t', '%.3f' % D, '-i', 'anullsrc=r=48000:cl=stereo']
    n = 2; vf = []; af = []; seq = []; voice = []; duck = []; other = []; luts = {}
    def lut_file(lid):
        if not lid: return None
        if lid in luts: return luts[lid]
        src = os.path.join(D_LUT, lid + '.cube')
        if not os.path.exists(src) or not re.match(r'^[A-Za-z0-9_]+$', lid): return None
        luts[lid] = 'lut_%s.cube' % lid; shutil.copy(src, os.path.join(tmp, luts[lid])); return luts[lid]
    def afx(c, idx, L, sp, fi, fo, kind):
        a = '[%d:a]%s,asetpts=PTS-STARTPTS' % (idx, atempo_chain(sp))
        if c.get('voiceFx'): a += ',' + VOICE_FX
        a += ',volume=%.3f' % c.get('vol', 1)
        if fi: a += ',afade=t=in:st=0:d=%.3f' % fi
        if fo: a += ',afade=t=out:st=%.3f:d=%.3f' % (max(0, L - fo), fo)
        af.append(a + ',aresample=48000,adelay=%d|%d,apad[a%d]' % (c['start'] * 1000, c['start'] * 1000, idx)); kind.append('[a%d]' % idx)
    order = lambda t: {'V1': 0, 'V2': 1}.get(t, 2 + int(t[1:]) / 10 if t[0] == 'T' else None)
    for c in sorted([c for c in clips if order(c['track']) is not None], key=lambda c: (order(c['track']), c['start'])):
        L = clen(c); sp = max(c.get('speed', 1), .05); fi = min(c.get('fadeIn', 0), L / 2); fo = min(c.get('fadeOut', 0), L / 2)
        if c['track'][0] == 'T':
            fd = os.path.join(tmp, c['id']); mf = os.path.join(fd, 'manifest.json')
            if not re.match(r'^[a-z0-9]+$', c['id']) or not os.path.exists(mf): continue
            man = json.load(open(mf)); durs = man['durs']
            if not durs: continue
            lines = []
            for i, dd in enumerate(durs): lines += ["file 'f%05d.png'" % i, 'duration %.5f' % dd]
            lines.append("file 'f%05d.png'" % (len(durs) - 1)); open(os.path.join(fd, 'list.txt'), 'w').write('\n'.join(lines) + '\n')
            inputs += ['-f', 'concat', '-safe', '0', '-i', os.path.join(fd, 'list.txt')]
            vf.append("[%d:v]format=rgba,fps=%d,setpts=PTS-STARTPTS+%.3f/TB[v%d]" % (n, fps, c['start'], n))
            seq.append((n, c['start'], c['start'] + L, True, int(man['box'][0]), int(man['box'][1]))); n += 1; continue
        m = next((m for m in media if m['id'] == c.get('media')), None)
        if not m: continue
        src = os.path.join(D_MEDIA, m['file'])
        fit = ('scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d' % (W, H, W, H)) if c.get('fit') == 'cover' else ('scale=%d:%d:force_original_aspect_ratio=decrease,pad=%d:%d:(ow-iw)/2:(oh-ih)/2:black' % (W, H, W, H))
        if m['kind'] == 'image': inputs += ['-loop', '1', '-framerate', str(fps), '-t', '%.3f' % L, '-i', src]; pre = '[%d:v]%s,setsar=1,fps=%d' % (n, fit, fps)
        else:
            inputs += ['-ss', '%.3f' % c['in'], '-t', '%.3f' % (c['out'] - c['in']), '-i', src]; pre = '[%d:v]setpts=(PTS-STARTPTS)/%.5f,%s,setsar=1,fps=%d' % (n, sp, fit, fps)
            if m['hasAudio'] and not c.get('mute'): afx(c, n, L, sp, fi, fo, voice)
        z = float(c.get('zoom', 1) or 1)
        if z > 1.001: pre += ',scale=iw*%.4f:ih*%.4f,crop=%d:%d:x=clip((iw-ow)/2+(%.4f)*ow,0,iw-ow):y=clip((ih-oh)/2+(%.4f)*oh,0,ih-oh)' % (z, z, W, H, c.get('panX', 0) or 0, c.get('panY', 0) or 0)
        b = float(c.get('brightness', 0) or 0); ct = float(c.get('contrast', 1) or 1); sa = float(c.get('saturation', 1) or 1); tp = float(c.get('temp', 0) or 0); sh = float(c.get('sharpen', 0) or 0)
        if abs(b) > .001 or abs(ct - 1) > .001 or abs(sa - 1) > .001: pre += ',eq=brightness=%.3f:contrast=%.3f:saturation=%.3f' % (b, ct, sa)
        if abs(tp) > .001: pre += ',colorbalance=rm=%.3f:bm=%.3f:rh=%.3f:bh=%.3f' % (tp * .14, -tp * .14, tp * .08, -tp * .08)
        if sh > .001: pre += ',unsharp=5:5:%.3f:5:5:0' % (sh * 1.2)
        post = 'format=rgba'
        if fi: post += ',fade=t=in:st=0:d=%.3f:alpha=1' % fi
        if fo: post += ',fade=t=out:st=%.3f:d=%.3f:alpha=1' % (max(0, L - fo), fo)
        post += ',setpts=PTS-STARTPTS+%.3f/TB' % c['start']
        lf = lut_file(c.get('lut')) if c.get('lut') else None
        if lf: vf.append(pre + '[p%d]' % n); vf += lut_stmts('[p%d]' % n, '[q%d]' % n, lf, float(c.get('lutAmt', 1)), 'k%d' % n); vf.append('[q%d]%s[v%d]' % (n, post, n))
        else: vf.append('%s,%s[v%d]' % (pre, post, n))
        seq.append((n, c['start'], c['start'] + L, False, 0, 0)); n += 1
    for c in [c for c in clips if c['track'] in ('A1', 'A2', 'A3')]:
        m = next((m for m in media if m['id'] == c.get('media')), None)
        if not m or not m['hasAudio']: continue
        L = clen(c); sp = max(c.get('speed', 1), .05); fi = min(c.get('fadeIn', 0), L / 2); fo = min(c.get('fadeOut', 0), L / 2)
        inputs += ['-ss', '%.3f' % c['in'], '-t', '%.3f' % (c['out'] - c['in']), '-i', os.path.join(D_MEDIA, m['file'])]
        afx(c, n, L, sp, fi, fo, duck if c.get('duck') else other); n += 1
    cur = '[0:v]'; k = 0; graded = False
    gl = lut_file(fx.get('lut')) if fx.get('lut') else None
    def do_grade():
        nonlocal cur, graded, k
        graded = True
        if gl: vf.extend(lut_stmts(cur, '[gr]', gl, float(fx.get('lutAmt', .7)), 'gg')); cur = '[gr]'
    for (idx, s, e, is_text, ox, oy) in seq:
        if is_text and not graded: do_grade()
        vf.append("%s[v%d]overlay=x=%d:y=%d:eof_action=pass:enable='between(t,%.3f,%.3f)'[o%d]" % (cur, idx, ox, oy, s, e, k)); cur = '[o%d]' % k; k += 1
    if not graded: do_grade()
    if fx_png:
        p = os.path.join(tmp, 'fx.png'); dec(fx_png, p); inputs += ['-loop', '1', '-framerate', str(fps), '-t', '%.3f' % D, '-i', p]
        vf.append('[%d:v]scale=%d:%d,format=rgba[fxl]' % (n, W, H)); vf.append('%s[fxl]overlay=eof_action=pass[ofx]' % cur); cur = '[ofx]'; n += 1
    post = []
    if fx.get('grain'): post.append('noise=alls=6:allf=t')
    post.append('format=yuv420p'); vf.append('%s%s[vout]' % (cur, ','.join(post)))
    af.append('[1:a]atrim=0:%.3f[sil]' % D)
    bus = ['[sil]']
    amix = lambda labs, o: '%samix=inputs=%d:duration=longest:normalize=0%s' % (''.join(labs), len(labs), o)
    if voice:
        af.append(amix(voice, '[vb]'))
        if duck: af.append('[vb]asplit=2[vm][vs]'); bus.append('[vm]')
        else: bus.append('[vb]')
    if duck:
        af.append(amix(duck, '[mb]'))
        if voice:
            af.append('[mb][vs]sidechaincompress=threshold=0.035:ratio=10:attack=25:release=600:makeup=1[md]'); bus.append('[md]')
        else: bus.append('[mb]')
    bus += other
    tail = ',loudnorm=I=-14:TP=-1.5:LRA=11' if opts.get('loudnorm') else ''
    af.append('%samix=inputs=%d:duration=first:normalize=0%s,alimiter=limit=0.97[aout]' % (''.join(bus), len(bus), tail))
    out = os.path.join(D_OUT, job + '.mp4')
    cmd = [FFMPEG, '-y', '-hide_banner', '-nostats', '-progress', 'pipe:1'] + inputs + ['-filter_complex', ';'.join(vf + af), '-map', '[vout]', '-map', '[aout]', '-t', '%.3f' % D,
           '-c:v', 'libx264', '-preset', opts.get('preset', 'medium'), '-crf', str(opts.get('crf', 18)), '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-movflags', '+faststart', out]
    open(os.path.join(tmp, 'cmd.txt'), 'w').write(' '.join('"%s"' % x if (' ' in x or ';' in x) else x for x in cmd))
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, cwd=tmp)   # cwd=tmp so LUT file names stay simple on every OS
    tail_l = []
    for line in p.stdout:
        tail_l = (tail_l + [line])[-25:]
        m = re.match(r'out_time_(?:us|ms)=(\d+)', line)
        if m: JOBS[job]['progress'] = min(.99, int(m.group(1)) / 1e6 / D)
    p.wait()
    if p.returncode == 0 and os.path.exists(out): JOBS[job].update(state='done', progress=1, file=job + '.mp4', size=os.path.getsize(out))
    else: JOBS[job].update(state='error', error=''.join(tail_l))
    shutil.rmtree(tmp, ignore_errors=True)

@app.route('/api/export/begin', methods=['POST'])
def export_begin():
    job = uuid.uuid4().hex[:8]; os.makedirs(os.path.join(D_TMP, job), exist_ok=True); return jsonify(job=job)

@app.route('/api/frames/<job>/<cid>', methods=['POST'])
def frames(job, cid):
    if not (re.match(r'^[a-z0-9]+$', job) and re.match(r'^[a-z0-9]+$', cid)): abort(400)
    d = os.path.join(D_TMP, job, cid); os.makedirs(d, exist_ok=True)
    for f in request.files.getlist('f'):
        m = re.search(r'(\d+)', f.filename or '')
        if m: f.save(os.path.join(d, 'f%05d.png' % int(m.group(1))))
    return jsonify(ok=True)

@app.route('/api/frames/<job>/<cid>/manifest', methods=['POST'])
def frames_manifest(job, cid):
    if not (re.match(r'^[a-z0-9]+$', job) and re.match(r'^[a-z0-9]+$', cid)): abort(400)
    d = os.path.join(D_TMP, job, cid); os.makedirs(d, exist_ok=True)
    json.dump(request.get_json(force=True), open(os.path.join(d, 'manifest.json'), 'w')); return jsonify(ok=True)

@app.route('/api/export', methods=['POST'])
def export():
    body = request.get_json(force=True); proj = body['project']
    if not proj.get('clips'): return jsonify(error='Timeline is empty'), 400
    job = body.get('job') or uuid.uuid4().hex[:8]
    if not re.match(r'^[a-z0-9]+$', job): abort(400)
    JOBS[job] = dict(state='running', progress=0)
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
