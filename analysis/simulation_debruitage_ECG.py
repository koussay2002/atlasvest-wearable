import numpy as np, json, time
from scipy import signal
from numpy.lib.stride_tricks import sliding_window_view
from sklearn.neural_network import MLPRegressor

FS = 250
rng_master = np.random.default_rng(2026)

# ---------- generation ----------
def gen_ecg(dur, hr, rng):
    N = int(dur*FS); t = np.arange(N)/FS
    rr0 = 60.0/hr
    ar = 0.0; tb = 0.4; beats = []; rrs = []
    while tb < dur+1:
        ar = 0.9*ar + rng.normal(0, 0.012)
        rr = max(0.28, rr0*(1+ar))
        beats.append(tb); rrs.append(rr); tb += rr
    beats = np.array(beats); rrs = np.array(rrs)
    amp = rng.uniform(0.8, 1.3)
    x = np.zeros(N)
    for tbk, rr in zip(beats, rrs):
        sq = np.sqrt(rr)
        waves = [(0.12, -(0.09+0.04*sq), 0.022), (-0.12, -0.028, 0.010), (1.0, 0.0, 0.011),
                 (-0.22, 0.026, 0.012), (0.28, 0.13+0.12*sq*0.9, 0.040)]
        i0 = max(0, int((tbk-0.5)*FS)); i1 = min(N, int((tbk+0.7)*FS))
        tt = t[i0:i1]
        for a, o, w in waves:
            x[i0:i1] += amp*a*np.exp(-0.5*((tt-(tbk+o))/w)**2)
    r = beats[(beats > 0.2) & (beats < dur-0.2)]
    return x, r

def gen_acc(dur, rng):
    N = int(dur*FS)
    f0 = rng.uniform(2.4, 3.2)
    f = f0 + np.cumsum(rng.normal(0, 0.004, N))*0.2
    f = np.clip(f, 2.0, 3.6)
    ph = 2*np.pi*np.cumsum(f)/FS
    A = rng.uniform(1.0, 2.5)
    z = A*(np.sin(ph)+0.4*np.sin(2*ph+0.7)+0.2*np.sin(3*ph+1.3))
    ap = 0.6*A*(np.sin(ph+1.0)+0.5*np.sin(2*ph))
    ml = 0.4*A*(np.sin(ph/2+0.3)+0.3*np.sin(1.5*ph))
    sos = signal.butter(2, 8, fs=FS, output='sos')
    acc = []
    for s in (z, ap, ml):
        terr = signal.sosfilt(sos, rng.normal(0, 1, N))*0.25*np.sqrt(FS/16)
        acc.append(s + terr + rng.normal(0, 0.02, N))
    return np.array(acc).T, f

SOS_ECG = signal.butter(2, [0.5, 40], btype='band', fs=FS, output='sos')
SOS_ACC = signal.butter(2, 0.5, btype='high', fs=FS, output='sos')
SOS_LP12 = signal.butter(2, 12, fs=FS, output='sos')
SOS_EMG = signal.butter(4, [20, 100], btype='band', fs=FS, output='sos')
SOS_UNOBS = signal.butter(2, [1, 10], btype='band', fs=FS, output='sos')

def make_record(dur, snr_db, rng, hr=None):
    hr = hr if hr is not None else rng.uniform(115, 185)
    ecg, rpk = gen_ecg(dur, hr, rng)
    acc, f = gen_acc(dur, rng)
    N = len(ecg); t = np.arange(N)/FS
    acc_hp = signal.sosfilt(SOS_ACC, acc, axis=0)
    # observable motion artifact (linear + nonlinear), time-varying coupling
    u = []
    for k in range(3):
        d = int(rng.uniform(0.010, 0.050)*FS)
        s = np.roll(acc_hp[:, k], d); s[:d] = 0
        u.append(signal.sosfilt(SOS_LP12, s))
    u = np.array(u).T
    mod = 1 + 0.4*np.sin(2*np.pi*0.05*t + rng.uniform(0, 6.28))
    a = rng.normal(0, 1, 3); b = rng.normal(0, 1, 3); c = rng.normal(0, 1)
    lin = (u @ a)*mod
    nonlin = (np.sign(u)*u**2 @ b)*mod + c*u[:, 0]*u[:, 1]
    env = np.abs(signal.sosfilt(SOS_LP12, np.abs(acc_hp[:, 0]))) + 0.2
    unobs = signal.sosfilt(SOS_UNOBS, rng.normal(0, 1, N))*env
    emg = signal.sosfilt(SOS_EMG, rng.normal(0, 1, N))*env
    bw = 0.5*np.sin(2*np.pi*rng.uniform(0.2, 0.4)*t+rng.uniform(0, 6.28)) + np.cumsum(rng.normal(0, 0.003, N))
    def nz(x):
        x = x - x.mean(); return x/np.sqrt(np.mean(x**2))
    Pn = np.var(ecg)/10**(snr_db/10)
    noise = np.sqrt(Pn)*(np.sqrt(0.25)*nz(lin)+np.sqrt(0.25)*nz(nonlin)+np.sqrt(0.25)*nz(unobs)
                         +np.sqrt(0.15)*nz(emg)+np.sqrt(0.10)*nz(bw))
    noisy = ecg + noise
    return dict(clean=ecg, noisy=noisy, acc=acc_hp, r=rpk, snr=snr_db)

def bp(x):
    return signal.sosfilt(SOS_ECG, x)

# ---------- NLMS ----------
def nlms(d, acc, L=16, mu=0.02):
    N = len(d)
    pad = np.vstack([np.zeros((L-1, 3)), acc])
    W = sliding_window_view(pad, L, axis=0)        # (N,3,L)
    X = W.reshape(N, 3*L)
    w = np.zeros(3*L); e = np.zeros(N)
    for n in range(N):
        x = X[n]
        y = w @ x
        en = d[n]-y
        e[n] = en
        w += (mu*en/(1e-3 + x @ x))*x
    return e

# ---------- QRS detection ----------
SOS_QRS = signal.butter(2, [5, 15], btype='band', fs=FS, output='sos')
def detect_qrs(x):
    from scipy.ndimage import maximum_filter1d
    b = signal.sosfiltfilt(SOS_QRS, x)
    d = np.gradient(b); sq = d**2
    w = int(0.12*FS)
    mwi = np.convolve(sq, np.ones(w)/w, mode='same')
    thr = 0.30*maximum_filter1d(mwi, size=int(4*FS))
    pk, _ = signal.find_peaks(mwi, height=thr, distance=int(0.25*FS))
    out = []
    for p in pk:
        lo = max(0, p-int(0.08*FS)); hi = min(len(b), p+int(0.08*FS))
        out.append(lo+np.argmax(np.abs(b[lo:hi])))
    return np.array(out)/FS

def score(det, true, t0=3.0, tol=0.06):
    det = det[det > t0]; true = true[true > t0]
    used = np.zeros(len(det), bool); tp = 0
    for r in true:
        if len(det) == 0: break
        i = np.argmin(np.abs(det-r))
        if abs(det[i]-r) <= tol and not used[i]:
            used[i] = True; tp += 1
    fn = len(true)-tp; fp = len(det)-tp
    se = tp/max(1, tp+fn); ppv = tp/max(1, tp+fp)
    return tp, fn, fp

def snr_out(out, ref, skip=2*FS):
    e = out[skip:]-ref[skip:]
    return 10*np.log10(np.sum(ref[skip:]**2)/np.sum(e**2))

# ---------- DAE windows ----------
WIN = 256; HOP_TR = 64; HOP_INF = 128; DEC = 4
def windows(sig, acc, hop, with_acc=True):
    N = len(sig)
    idx = np.arange(0, N-WIN+1, hop)
    Xe = np.stack([sig[i:i+WIN] for i in idx])
    if with_acc:
        Xa = np.stack([acc[i:i+WIN:DEC].T.ravel() for i in idx])/3.0
        return idx, np.hstack([Xe/2.0, Xa])
    return idx, Xe/2.0

def ola(preds, idx, N):
    w = np.hanning(WIN)+1e-3
    out = np.zeros(N); ws = np.zeros(N)
    for p, i in zip(preds, idx):
        out[i:i+WIN] += w*p*2.0; ws[i:i+WIN] += w
    ws[ws == 0] = 1
    return out/ws

# ---------- Quantized forward ----------
def forward_fp(m, X):
    a = X
    for i, (W, b) in enumerate(zip(m.coefs_, m.intercepts_)):
        a = a@W+b
        if i < len(m.coefs_)-1: a = np.maximum(a, 0)
    return a

def calibrate(m, X):
    scales = []
    a = X; scales.append(np.percentile(np.abs(a), 99.9)/127)
    for i, (W, b) in enumerate(zip(m.coefs_, m.intercepts_)):
        a = a@W+b
        if i < len(m.coefs_)-1: a = np.maximum(a, 0)
        scales.append(np.percentile(np.abs(a), 99.9)/127)
    return scales

def forward_int8(m, X, scales):
    def q(a, s): return np.clip(np.round(a/s), -127, 127)*s
    a = q(X, scales[0])
    for i, (W, b) in enumerate(zip(m.coefs_, m.intercepts_)):
        sw = np.abs(W).max()/127
        Wq = np.clip(np.round(W/sw), -127, 127)*sw
        a = a@Wq+b
        if i < len(m.coefs_)-1: a = np.maximum(a, 0)
        a = q(a, scales[i+1])
    return a

def macs(m):
    return int(sum(W.shape[0]*W.shape[1] for W in m.coefs_))
def nparams(m):
    return int(sum(W.size+b.size for W, b in zip(m.coefs_, m.intercepts_)))

if __name__ == "__main__":
    t_start = time.time()
    rng = np.random.default_rng(7)
    # NLMS tuning on a few records
    tune = [make_record(40, s, rng) for s in (-6, 0, 6) for _ in range(2)]
    best = None
    for L in (16, 32):
        for mu in (0.005, 0.01, 0.02, 0.05):
            v = []
            for r in tune:
                d = bp(r['noisy']); ref = bp(r['clean'])
                e = nlms(d, r['acc'], L, mu); v.append(snr_out(e, ref))
            print('NLMS L', L, 'mu', mu, 'meanSNR', np.mean(v), flush=True)
            if best is None or np.mean(v) > best[0]: best = (np.mean(v), L, mu)
    _, L_N, MU_N = best
    print('best NLMS', best, time.time()-t_start, flush=True)

    # training set
    tr = []
    for i in range(70):
        snr = rng.uniform(-6, 14)
        r = make_record(50, snr, rng)
        r['d'] = bp(r['noisy']); r['ref'] = bp(r['clean'])
        r['nl'] = nlms(r['d'], r['acc'], L_N, MU_N)
        tr.append(r)
    print('train records', time.time()-t_start, flush=True)

    def build(kind):
        Xs, Ys = [], []
        for r in tr:
            if kind == 'ecg':   idx, X = windows(r['d'], r['acc'], HOP_TR, False)
            elif kind == 'imu': idx, X = windows(r['d'], r['acc'], HOP_TR, True)
            else:               idx, X = windows(r['nl'], r['acc'], HOP_TR, True)
            Y = np.stack([r['ref'][i:i+WIN] for i in idx])/2.0
            Xs.append(X); Ys.append(Y)
        return np.vstack(Xs), np.vstack(Ys)
    models = {}
    for kind in ('ecg', 'imu', 'casc'):
        X, Y = build(kind)
        m = MLPRegressor(hidden_layer_sizes=(160, 48, 160), activation='relu', solver='adam',
                         learning_rate_init=1e-3, batch_size=256, max_iter=45, early_stopping=True,
                         n_iter_no_change=6, random_state=1, alpha=1e-5)
        m.fit(X, Y)
        models[kind] = (m, calibrate(m, X[:4000]))
        print('trained', kind, X.shape, 'val', m.best_validation_score_, time.time()-t_start, flush=True)

    # ---------- test ----------
    def run_dae(kind, sig, acc, int8=False):
        m, sc = models[kind]
        idx, X = windows(sig, acc, HOP_INF, kind != 'ecg')
        P = forward_int8(m, X, sc) if int8 else forward_fp(m, X)
        return ola(P, idx, len(sig))

    def psqi(x, win=2*FS):
        f, P = signal.welch(x, fs=FS, nperseg=win)
        num = P[(f >= 5) & (f <= 15)].sum(); den = P[(f >= 1) & (f <= 40)].sum()
        return num/den

    levels = [12, 6, 0, -6]
    methods = ['bp', 'nlms', 'dae_ecg', 'dae_imu', 'casc', 'casc_int8', 'casc_gated']
    res = {s: {m: dict(snr=[], tp=0, fn=0, fp=0) for m in methods} for s in levels}
    gate_frac = {s: [] for s in levels}
    sqi_vals = {s: [] for s in levels}
    example = None
    rng_t = np.random.default_rng(99)
    SQI_THR = None
    # SQI threshold: choose from train NLMS outputs 40th percentile-> computed below
    sq_tr = []
    for r in tr[:30]:
        for i in range(3*FS, len(r['nl'])-2*FS, 2*FS):
            sq_tr.append(psqi(r['nl'][i:i+2*FS]))
    SQI_THR = float(np.percentile(sq_tr, 50))
    print('SQI thr', SQI_THR, flush=True)
    for s in levels:
        for k in range(12):
            r = make_record(50, s, rng_t, hr=rng_t.uniform(120, 180))
            d = bp(r['noisy']); ref = bp(r['clean'])
            nl = nlms(d, r['acc'], L_N, MU_N)
            outs = {'bp': d, 'nlms': nl,
                    'dae_ecg': run_dae('ecg', d, r['acc']),
                    'dae_imu': run_dae('imu', d, r['acc']),
                    'casc': run_dae('casc', nl, r['acc']),
                    'casc_int8': run_dae('casc', nl, r['acc'], True)}
            # gated: per 2-s segment use DAE only if SQI(nlms) < thr
            gated = nl.copy(); seg = 2*FS; n_g = 0; n_t = 0
            for i in range(0, len(nl)-seg+1, seg):
                q = psqi(nl[i:i+seg]); sqi_vals[s].append(q); n_t += 1
                if q < SQI_THR:
                    gated[i:i+seg] = outs['casc'][i:i+seg]; n_g += 1
            outs['casc_gated'] = gated; gate_frac[s].append(n_g/n_t)
            for mth in methods:
                o = outs[mth]
                res[s][mth]['snr'].append(snr_out(o, ref))
                det = detect_qrs(o); tp, fn, fp = score(det, r['r'])
                res[s][mth]['tp'] += tp; res[s][mth]['fn'] += fn; res[s][mth]['fp'] += fp
            if s == 0 and k == 0:
                example = dict(t=(np.arange(len(d))/FS)[8*FS:14*FS].tolist(),
                               ref=ref[8*FS:14*FS].tolist(), bp=d[8*FS:14*FS].tolist(),
                               nlms=nl[8*FS:14*FS].tolist(), dae_imu=outs['dae_imu'][8*FS:14*FS].tolist(),
                               casc=outs['casc'][8*FS:14*FS].tolist(),
                               acc=r['acc'][8*FS:14*FS, 0].tolist())
        print('level', s, time.time()-t_start, flush=True)

    summary = {}
    for s in levels:
        summary[s] = {}
        for mth in methods:
            R = res[s][mth]
            se = R['tp']/max(1, R['tp']+R['fn']); ppv = R['tp']/max(1, R['tp']+R['fp'])
            f1 = 2*se*ppv/max(1e-9, se+ppv)
            summary[s][mth] = dict(snr=float(np.mean(R['snr'])), snr_sd=float(np.std(R['snr'])), se=se, ppv=ppv, f1=f1)
        summary[s]['gate_frac'] = float(np.mean(gate_frac[s]))
    info = dict(L=L_N, mu=MU_N, sqi_thr=SQI_THR,
                macs={k: macs(models[k][0]) for k in models}, params={k: nparams(models[k][0]) for k in models},
                n_train_windows=int(build('ecg')[0].shape[0]))
    json.dump(dict(summary=summary, info=info, example=example), open('results.json', 'w'))
    print(json.dumps(summary, indent=1)); print(info)
    print('done', time.time()-t_start)
