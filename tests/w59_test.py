#!/usr/bin/env python3
"""E2E W59: descargas solo en la app, un control por adjunto, perfil
(avatar sobre portada y PNG transparente), botón de bajar, áreas seguras,
barras de Android y cambio de @usuario con espera de 12 h.

Uso: server/.venv/bin/python tests/w59_test.py [--base http://127.0.0.1:8899]
"""
import argparse
import io
import json
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
import chat_ui_test as ct  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

SHOTS = Path("/tmp/opencode")
_pass = [0]
_fail = [0]


def step(name, cond, detail=""):
    if cond:
        _pass[0] += 1
        print(f"  ✓ {name}")
    else:
        _fail[0] += 1
        print(f"  ✗ {name}: {detail}")


def jparse(res):
    try:
        return json.loads(res) if res and res.startswith("{") else {}
    except Exception:
        return {}


def sess_js(u):
    sess = json.dumps({"access": u["access"], "refresh": u["refresh"],
                       "user": u["user"], "pendingEmail": ""})
    return ct.JS_INJECT.replace(
        "SESSION_JSON", sess.replace("\\", "\\\\").replace("'", "\\'"))


def shot(url, out, js=None, wait=600, width=1280, height=860, viewport=False,
         timeout=240):
    cmd = [str(ct.PY), str(ct.SHOT), url, str(out), "--wait", str(wait),
           "--width", str(width), "--height", str(height)]
    if viewport:
        cmd.append("--viewport")
    if js:
        cmd += ["--js", js]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    res = None
    for line in r.stdout.splitlines():
        if line.startswith("JSRES: "):
            try:
                v = json.loads(line[7:].strip())
                res = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
            except Exception:
                res = line[7:].strip()
    ok = r.returncode == 0 and "SHOT:" in r.stdout
    return ok, res, (r.stdout + r.stderr)


def trans_png(path, size=256):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((18, 18, size - 18, size - 18), fill=(255, 122, 0, 255))
    d.rectangle((size // 2 - 10, size // 2 - 10, size // 2 + 10, size // 2 + 10),
                fill=(255, 255, 255, 255))
    img.save(path)
    return path


def accept_friend(base, a, b):
    uid = a["user"]["id"]
    st, rq = ct.http("POST", base + "/api/people/requests",
                     {"username": b["user"]["username"]}, token=a["access"])
    st2, ppl = ct.http("GET", base + "/api/people", token=b["access"])
    payload = ppl.get("people") or ppl
    rid = None
    for row in (payload.get("received") or []):
        u = row.get("user") or {}
        if u.get("id") == uid or row.get("id") == uid:
            rid = row.get("id") or row.get("request_id") or u.get("id")
            break
    if rid is None:
        return False
    st3, _ = ct.http("POST", base + f"/api/people/requests/{rid}/accept",
                     {}, token=b["access"])
    return st in (200, 201) and st3 in (200, 201)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8899")
    a = ap.parse_args()
    SHOTS.mkdir(parents=True, exist_ok=True)
    tag = uuid.uuid4().hex[:6]

    print("→ preparar usuarios, perfiles y conversación")
    A = ct.register(a.base, f"w59a{tag}@t.fi", f"w59a{tag}")
    B = ct.register(a.base, f"w59b{tag}@t.fi", f"w59b{tag}")
    AU, BU = A["user"]["username"], B["user"]["username"]
    BID = B["user"]["id"]

    avatar = ct.upload(a.base, A["access"],
                       trans_png(SHOTS / f"w59-av-{tag}.png"))
    banner = SHOTS / f"w59-bn-{tag}.png"
    Image.new("RGB", (900, 300), (20, 120, 200)).save(banner)
    bn = ct.upload(a.base, A["access"], banner)
    st, r = ct.http("PUT", a.base + "/api/auth/profile",
                    {"display_name": "Ana W59", "bio": "Perfil W59",
                     "avatar_media_id": avatar["id"],
                     "banner_media_id": bn["id"]}, token=A["access"])
    if st != 200:
        raise SystemExit(f"✗ perfil A: {st} {r}")
    A["user"] = r["user"]
    bbn = ct.upload(a.base, B["access"], banner)
    st, r = ct.http("PUT", a.base + "/api/auth/profile",
                    {"display_name": "Beto W59", "bio": "Beto",
                     "banner_media_id": bbn["id"]}, token=B["access"])
    if st != 200:
        raise SystemExit(f"✗ perfil B: {st} {r}")
    B["user"] = r["user"]
    step("amistad A-B", accept_friend(a.base, A, B))
    st, dm = ct.http("POST", a.base + "/api/chats/dm",
                     {"username": BU}, token=A["access"])
    cid = (dm.get("chat") or {}).get("id")
    step("DM creada", st in (200, 201) and bool(cid), dm)
    if not cid:
        raise SystemExit("sin DM")

    pic = SHOTS / f"w59-pic-{tag}.png"
    Image.new("RGB", (400, 300), (220, 60, 40)).save(pic)
    m = ct.upload(a.base, B["access"], pic)
    ct.send(a.base, B["access"], cid,
            {"kind": "image", "body": "", "media_id": m["id"],
             "client_msg_id": str(uuid.uuid4())})
    pic2 = SHOTS / f"w59-pic2-{tag}.png"
    Image.new("RGB", (360, 280), (20, 180, 90)).save(pic2)
    m2 = ct.upload(a.base, B["access"], pic2)
    doc = SHOTS / f"w59-doc-{tag}.txt"
    doc.write_text("documento W59\n", encoding="utf-8")
    md = ct.upload(a.base, B["access"], doc)
    ct.send(a.base, B["access"], cid,
            {"kind": "file", "body": "", "media_id": md["id"],
             "client_msg_id": str(uuid.uuid4())})

    # PNG transparente: el servidor lo convierte a WebP y debe conservar alfa.
    try:
        import urllib.request
        raw = urllib.request.urlopen(a.base + A["user"]["avatar_url"], timeout=20).read()
        im = Image.open(io.BytesIO(raw)).convert("RGBA")
        alpha = im.getchannel("A").getextrema()
        step("el avatar transparente conserva el canal alfa", alpha[0] == 0, alpha)
        step("el avatar transparente tiene zona opaca", alpha[1] > 200, alpha)
    except Exception as e:
        step("el avatar transparente conserva el canal alfa", False, str(e))

    st, me = ct.http("GET", a.base + "/api/users/me", token=A["access"])
    step("/api/users/me incluye username_changed_at",
         st == 200 and "username_changed_at" in (me.get("user") or {}), me)

    # ---------------- preparar navegador ----------------
    shot(a.base + "/", SHOTS / "w59-0-prep.png",
         js="(async()=>{try{const rs=await navigator.serviceWorker.getRegistrations();"
            "for(const r of rs)await r.unregister();}catch(e){};"
            "try{const ks=await caches.keys();for(const k of ks)await caches.delete(k);}catch(e){};"
            "localStorage.removeItem('fm.session');localStorage.removeItem('fm.dl.auto');"
            "localStorage.removeItem('fm.dlauto.v');return 'ok';})()",
         wait=300)
    ok, res, log = shot(a.base + "/", SHOTS / "w59-1-sesion.png",
                        js=sess_js(A), wait=300)
    step("sesión de A inyectada", ok and res == "sesión inyectada", res or log[-400:])

    # ---------------- perfil: portada + avatar + transparente ----------------
    js_profile = """(async () => {
      const sleep = ms => new Promise(r => setTimeout(r, ms));
      const wait = async (sel, ms=12000) => { const t=Date.now(); while(Date.now()-t<ms){const el=document.querySelector(sel); if(el) return el; await sleep(100);} return null; };
      const t0 = Date.now();
      while (Date.now() - t0 < 20000 && window.__fm && __fm.store.booting) await sleep(150);
      __fm.store.meProfileOpen = true;
      const mp = await wait('.modal.meprof', 8000);
      if (!mp) return 'FAIL sin modal';
      const body = mp.querySelector('.mp-body');
      const banner = body.querySelector('.pf-banner');
      const av = body.querySelector('.pf-avwrap .avatar');
      if (!body || !banner || !av) return 'FAIL sin piezas';
      const br = banner.getBoundingClientRect(), ar = av.getBoundingClientRect();
      const cs = getComputedStyle(av);
      const out = {
        overlap: Math.round(br.bottom - ar.top),
        avatarTopOverBody: Math.round(ar.top - body.getBoundingClientRect().top),
        bodyOverflow: getComputedStyle(body).overflowY,
        avatarBg: cs.backgroundColor,
        avatarClass: av.className,
        bannerParent: banner.parentElement.className,
        bannerInBody: body.contains(banner),
        clipped: ar.top < body.getBoundingClientRect().top - 0.5
      };
      const edit = Array.from(mp.querySelectorAll('button')).find(b => b.textContent.indexOf('Editar perfil') >= 0);
      if (!edit) return JSON.stringify(Object.assign(out, {edit:false}));
      edit.click();
      const em = await wait('.modal.meprof.mp-edit', 8000);
      if (!em) return JSON.stringify(Object.assign(out, {edit:true, editor:false}));
      const bimg = em.querySelector('.pf-edit-banner-img');
      const pick = em.querySelector('.avatar-pick');
      const avimg = em.querySelector('.avatar-pick .av-img');
      const ebr = bimg.getBoundingClientRect(), ear = pick.getBoundingClientRect();
      out.editOverlap = Math.round(ebr.bottom - ear.top);
      out.editImgBg = getComputedStyle(avimg).backgroundColor;
      out.editImgClass = avimg.className;
      const ub = em.querySelector('.uname-current .btn');
      out.unameBtn = !!ub;
      if (ub) ub.click();
      const panel = await wait('.uname-edit', 4000);
      if (panel) {
        await sleep(400);
        const warn = panel.querySelector('.uname-warn');
        out.warn = warn ? warn.textContent.replace(/\\s+/g,' ').trim() : '';
        const confirm = panel.querySelector('.btn-full');
        const bodyRect = em.querySelector('.mp-body').getBoundingClientRect();
        out.confirmVisible = confirm.getBoundingClientRect().bottom <= bodyRect.bottom + 0.5;
        out.scrollTop = em.querySelector('.mp-body').scrollTop;
      }
      return JSON.stringify(out);
    })()"""
    ok, res, log = shot(a.base + "/?v=w59-profile", SHOTS / "w59-2-perfil.png",
                        js=js_profile, wait=800)
    d = jparse(res)
    step("perfil: el avatar se monta sobre la portada", ok and d.get("overlap", 0) >= 24, d or log[-400:])
    step("perfil: el avatar no queda recortado por el scroll",
         d.get("bodyOverflow") == "auto" and not d.get("clipped"), d)
    step("perfil: portada dentro del cuerpo con scroll",
         bool(d.get("bannerInBody")), d)
    step("perfil: foto transparente sin fondo",
         d.get("avatarBg") == "rgba(0, 0, 0, 0)" and "has-photo" in (d.get("avatarClass") or ""), d)
    step("editor: avatar sobre portada y foto transparente",
         d.get("editOverlap", 0) >= 24 and d.get("editImgBg") == "rgba(0, 0, 0, 0)" and
         "has-photo" in (d.get("editImgClass") or ""), d)
    step("editor: aviso de 12 h y confirmación visible",
         "12 horas" in (d.get("warn") or "") and d.get("confirmVisible"), d)

    # ---------------- cambio de @usuario ----------------
    new_name = ("w59" + tag)[:18]
    js_uname = """(async () => {
      const sleep = ms => new Promise(r => setTimeout(r, ms));
      const wait = async (sel, ms=10000) => { const t=Date.now(); while(Date.now()-t<ms){const el=document.querySelector(sel); if(el) return el; await sleep(100);} return null; };
      const setVal = (el, v) => { el.value = v; el.dispatchEvent(new Event('input', { bubbles: true })); };
      __fm.store.meProfileOpen = true;
      const mp = await wait('.modal.meprof', 8000);
      const edBtn = Array.from(mp.querySelectorAll('button')).find(b => b.textContent.indexOf('Editar perfil') >= 0);
      edBtn.click();
      const em = await wait('.modal.meprof.mp-edit', 8000);
      const openBtn = em.querySelector('.uname-current .btn');
      openBtn.click();
      const panel = await wait('.uname-edit', 4000);
      if (!panel) return 'FAIL panel';
      await sleep(300);
      const name = panel.querySelectorAll('input')[0];
      const pw = panel.querySelectorAll('input')[1];
      const confirm = panel.querySelector('.btn-full');
      const err = () => (panel.querySelector('.st-err') || {}).textContent || '';
      const out = {warn: !!panel.querySelector('.uname-warn')};
      setVal(name, 'A!'); setVal(pw, 'foxpass12345'); await sleep(80); confirm.click(); await sleep(250);
      out.invalid = err();
      setVal(name, 'nueva_w59'); setVal(pw, 'incorrecta'); await sleep(80); confirm.click();
      let t0=Date.now(); while(Date.now()-t0<8000 && !/contraseña/i.test(err())) await sleep(120);
      out.wrong = err();
      setVal(name, '{BU}'); setVal(pw, 'foxpass12345'); await sleep(80); confirm.click();
      t0=Date.now(); while(Date.now()-t0<8000 && !/uso/i.test(err())) await sleep(120);
      out.dup = err();
      setVal(name, '{NEW}'); setVal(pw, 'foxpass12345'); await sleep(80); confirm.click();
      t0=Date.now(); while(Date.now()-t0<10000 && (__fm.store.user||{}).username !== '{NEW}') await sleep(150);
      out.newName = (__fm.store.user||{}).username;
      out.changedAt = (__fm.store.user||{}).username_changed_at;
      out.closed = !document.querySelector('.uname-edit');
      const open2 = document.querySelector('.uname-current .btn');
      out.btnDisabled = open2 ? open2.disabled : null;
      out.waitText = ((em.querySelector('.uname-wait')||{}).textContent || '').replace(/\\s+/g,' ').trim();
      let sess = null; try { sess = JSON.parse(localStorage.getItem('fm.session')); } catch(e) {}
      out.sessionName = sess && sess.user ? sess.user.username : '';
      return JSON.stringify(out);
    })()""".replace("{BU}", BU).replace("{NEW}", new_name)
    ok, res, log = shot(a.base + "/?v=w59-uname", SHOTS / "w59-3-usuario.png",
                        js=js_uname, wait=600)
    d = jparse(res)
    step("usuario: formato inválido rechazado", "3-20" in (d.get("invalid") or ""), d)
    step("usuario: contraseña incorrecta rechazada", "contraseña" in (d.get("wrong") or "").lower(), d)
    step("usuario: duplicado rechazado", "uso" in (d.get("dup") or ""), d)
    step("usuario: cambio correcto y sesión actualizada",
         d.get("newName") == new_name and d.get("sessionName") == new_name and
         (d.get("changedAt") or 0) > 0, d)
    step("usuario: enfriamiento mostrado y botón desactivado",
         d.get("btnDisabled") and "Podrás cambiarlo" in (d.get("waitText") or ""), d)
    st, me = ct.http("GET", a.base + "/api/users/me", token=A["access"])
    step("usuario: /users/me persiste username_changed_at",
         st == 200 and (me.get("user") or {}).get("username") == new_name and
         (me.get("user") or {}).get("username_changed_at", 0) > 0, me)

    # Recarga: el aviso debe sobrevivir al bootstrap (/users/me).
    js_reload = """(async () => {
      const sleep = ms => new Promise(r => setTimeout(r, ms));
      const wait = async (sel, ms=10000) => { const t=Date.now(); while(Date.now()-t<ms){const el=document.querySelector(sel); if(el) return el; await sleep(100);} return null; };
      const t0 = Date.now(); while (Date.now()-t0<20000 && window.__fm && __fm.store.booting) await sleep(150);
      __fm.store.meProfileOpen = true;
      const mp = await wait('.modal.meprof', 8000);
      const edBtn = mp ? Array.from(mp.querySelectorAll('button')).find(b => b.textContent.indexOf('Editar perfil') >= 0) : null;
      if (edBtn) edBtn.click();
      const em = await wait('.modal.meprof.mp-edit', 8000);
      const btn = em ? em.querySelector('.uname-current .btn') : null;
      return JSON.stringify({
        user: (__fm.store.user||{}).username,
        changedAt: (__fm.store.user||{}).username_changed_at,
        btnDisabled: btn ? btn.disabled : null,
        waitText: em ? ((em.querySelector('.uname-wait')||{}).textContent||'').replace(/\\s+/g,' ').trim() : ''
      });
    })()"""
    ok, res, log = shot(a.base + "/?v=w59-reload", SHOTS / "w59-4-recarga.png",
                        js=js_reload, wait=700)
    d = jparse(res)
    step("usuario: el enfriamiento sobrevive a recargar",
         d.get("user") == new_name and (d.get("changedAt") or 0) > 0 and
         d.get("btnDisabled") and "Podrás cambiarlo" in (d.get("waitText") or ""), d)

    # ---------------- perfil ajeno: modal y panel derecho ----------------
    js_peer = """(async () => {
      const sleep = ms => new Promise(r => setTimeout(r, ms));
      const wait = async (sel, ms=12000) => { const t=Date.now(); while(Date.now()-t<ms){const el=document.querySelector(sel); if(el) return el; await sleep(100);} return null; };
      const item = await wait('.chat-item[data-chat-id="{CID}"]', 12000);
      if (!item) return 'FAIL sin chat';
      item.click();
      await wait('.msgs .msg', 10000);
      __fm.store.infoOpen = true;
      const side = await wait('.profile-panel', 6000);
      const col = document.querySelector('.chat-head .ch-col');
      if (col) col.click();
      const modal = await wait('.modal.pmodal', 6000);
      if (modal) await wait('.modal.pmodal .pf-avwrap', 6000);
      const measure = (root, sel) => {
        if (!root) return null;
        const body = root.querySelector('.pp-body');
        const b = root.querySelector('.pf-banner');
        const av = root.querySelector('.pf-avwrap');
        if (!body || !b || !av) return null;
        const br=b.getBoundingClientRect(), ar=av.getBoundingClientRect();
        return {overlap: Math.round(br.bottom-ar.top),
          clipped: ar.top < body.getBoundingClientRect().top - 0.5,
          parent: b.parentElement.className};
      };
      return JSON.stringify({side: measure(side), modal: measure(modal),
        sideExists: !!side, modalExists: !!modal});
    })()""".replace("{CID}", str(cid))
    ok, res, log = shot(a.base + "/?v=w59-peer", SHOTS / "w59-5-ajeno.png",
                        js=js_peer, wait=700)
    d = jparse(res)
    step("perfil ajeno (lateral): avatar sobre portada y sin recorte",
         d.get("sideExists") and (d.get("side") or {}).get("overlap", 0) >= 24 and
         not (d.get("side") or {}).get("clipped") and
         "pp-body" in ((d.get("side") or {}).get("parent") or ""), d)
    step("perfil ajeno (modal): avatar sobre portada y sin recorte",
         d.get("modalExists") and (d.get("modal") or {}).get("overlap", 0) >= 24 and
         not (d.get("modal") or {}).get("clipped"), d)

    # ---------------- descargas: defaults + app-only + exportar ----------------
    print("→ descargas")
    js_prefs = """(async () => {
      localStorage.removeItem('fm.dl.auto'); localStorage.removeItem('fm.dlauto.v');
      const fresh = __fm.dl.autoDlPrefs();
      const old = {}; __fm.dl.types.forEach(t => { old[t.id] = {wifi:false,mobile:false}; });
      localStorage.setItem('fm.dl.auto', JSON.stringify(old));
      localStorage.removeItem('fm.dlauto.v');
      const mig = __fm.dl.autoDlPrefs();
      __fm.dl.setAutoDl('image', 'wifi', false);
      const afterSet = __fm.dl.autoDlPrefs();
      const ver = localStorage.getItem('fm.dlauto.v');
      // volver a Wi-Fi activo para la prueba automática
      __fm.dl.setAutoDl('image', 'wifi', true);
      return JSON.stringify({
        ids: __fm.dl.types.map(t=>t.id),
        fresh: __fm.dl.types.map(t=>[fresh[t.id].wifi, fresh[t.id].mobile]),
        mig: __fm.dl.types.map(t=>[mig[t.id].wifi, mig[t.id].mobile]),
        afterSet: afterSet.image.wifi,
        ver: ver
      });
    })()"""
    ok, res, log = shot(a.base + "/?v=w59-prefs", SHOTS / "w59-6-prefs.png",
                        js=js_prefs, wait=500)
    d = jparse(res)
    step("descargas: Wi-Fi activo y móvil apagado por defecto",
         ok and all(x == [True, False] for x in (d.get("fresh") or [])), d)
    step("descargas: migración W58 vuelve a activar Wi-Fi",
         ok and all(x == [True, False] for x in (d.get("mig") or [])), d)
    step("descargas: una elección explícita no se pisa",
         d.get("afterSet") is False and d.get("ver") == "2", d)

    # Auto: borrar copias, defaults, abrir el chat y esperar.
    shot(a.base + "/?v=w59-autoprep", SHOTS / "w59-7-autoprep.png",
         js="(async()=>{localStorage.removeItem('fm.dl.auto');"
            "localStorage.removeItem('fm.dlauto.v');await __fm.dl.clearDownloads();"
            "return 'ok';})()", wait=500)
    js_auto = """(async () => {
      const sleep = ms => new Promise(r => setTimeout(r, ms));
      const wait = async (fn, ms=30000) => { const t=Date.now(); while(Date.now()-t<ms){const v=fn(); if(v) return v; await sleep(150);} return null; };
      const calls={begin:0,open:0};
      window.FoxinixAndroid={storagePermission:()=> 'granted',
        permissionState:()=> 'granted', requestPermissionFor:()=> 'granted',
        permission:()=> 'granted',
        beginSave:()=>{calls.begin++;return 'ok';}, appendSave:()=>true,
        finishSave:()=> 'ok:x', cancelSave:()=>{}, insets:()=> '0,0,0,0'};
      window.open=function(){calls.open++;return null;};
      const t0=Date.now(); while(Date.now()-t0<25000 && window.__fm && __fm.store.booting) await sleep(150);
      const item=await wait(()=>document.querySelector('.chat-item[data-chat-id="{CID}"]'),15000);
      if(!item) return 'FAIL sin chat';
      item.click();
      const n=await wait(()=>{const k=Object.keys(__fm.store.dlSaved||{}).length; return k>=2?k:null;},35000);
      const texts=Array.from(document.querySelectorAll('.msgs .msg .b-dl-state')).map(e=>e.textContent.trim());
      return JSON.stringify({saved:n, begin:calls.begin, open:calls.open,
        states:texts.length, downloaded:texts.filter(x=>x.indexOf('Descargado')===0).length,
        anchors:document.querySelectorAll('.msgs .msg a[download]').length});
    })()""".replace("{CID}", str(cid))
    ok, res, log = shot(a.base + "/?v=w59-auto", SHOTS / "w59-8-autodl.png",
                        js=js_auto, wait=900)
    d = jparse(res)
    step("automático: guarda en la app sin exportar al dispositivo",
         ok and (d.get("saved") or 0) >= 2 and d.get("begin") == 0, d or log[-400:])
    step("automático: no abre pestañas ni deja botones antiguos",
         d.get("open") == 0 and d.get("anchors") == 0, d)
    step("automático: el estado visible es Descargado y hay un control por mensaje",
         (d.get("downloaded") or 0) >= 2 and (d.get("states") or 0) >= 2, d)

    js_manual = """(async () => {
      const sleep = ms => new Promise(r => setTimeout(r, ms));
      const wait = async (fn, ms=20000) => { const t=Date.now(); while(Date.now()-t<ms){const v=fn(); if(v) return v; await sleep(120);} return null; };
      const calls={begin:0,append:0,finish:0,open:0};
      window.FoxinixAndroid={storagePermission:()=> 'granted',
        permissionState:()=> 'granted', requestPermissionFor:()=> 'granted',
        permission:()=> 'granted',
        beginSave:()=>{calls.begin++;return 'ok';}, appendSave:()=>{calls.append++;return true;},
        finishSave:()=>{calls.finish++;return 'ok:w59.png';}, cancelSave:()=>{},
        insets:()=> '0,0,0,0'};
      window.open=function(){calls.open++;return null;};
      const off={}; __fm.dl.types.forEach(t=>{off[t.id]={wifi:false,mobile:false};});
      localStorage.setItem('fm.dl.auto',JSON.stringify(off));
      localStorage.setItem('fm.dlauto.v','2');
      const t0=Date.now(); while(Date.now()-t0<20000 && window.__fm && __fm.store.booting) await sleep(150);
      const item=await wait(()=>document.querySelector('.chat-item[data-chat-id="{CID}"]'),12000);
      if(!item) return 'FAIL sin chat';
      item.click();
      await wait(()=>document.querySelector('.msgs .msg'),10000);
      const beforeIds=new Set((__fm.store.msgs[{CID}]||[]).map(m=>m.id));
      const beforeKeys=Object.keys(__fm.store.dlSaved||{});
      let st=0;
      for(let i=0;i<5;i++){
        const r=await fetch('/api/chats/{CID}/messages',{method:'POST',
          headers:{'Content-Type':'application/json','Authorization':'Bearer {BT}'},
          body:JSON.stringify({kind:'image',body:'',media_id:{MID},client_msg_id:'w59-'+Date.now()})});
        st=r.status; if(st===201)break; if(st!==429)break; await sleep(1200);
      }
      const nm=await wait(()=>{const arr=__fm.store.msgs[{CID}]||[];
        return arr.find(m=>!beforeIds.has(m.id)&&m.media&&m.media.id==={MID})||null;},12000);
      if(!nm) return 'FAIL mensaje nuevo';
      const el=document.querySelector('.msg[data-msg-id="'+nm.id+'"] .b-dl-state');
      if(!el) return 'FAIL estado';
      const beforeTxt=el.textContent.trim();
      el.click();
      const key=await wait(()=>{const ks=Object.keys(__fm.store.dlSaved||{});
        return ks.find(k=>beforeKeys.indexOf(k)<0)||null;},20000);
      const appCalls={begin:calls.begin,open:calls.open};
      const exp=key?await __fm.dl.saveDownloadToDevice(key,'w59.png','image/png'):null;
      return JSON.stringify({st:st,before:beforeTxt,key:key,appCalls:appCalls,
        exp:exp,exportCalls:{begin:calls.begin,append:calls.append,finish:calls.finish},
        open:calls.open,states:document.querySelectorAll('.msgs .msg .b-dl-state').length,
        msgs:document.querySelectorAll('.msgs .msg').length,
        anchors:document.querySelectorAll('.msgs .msg a[download]').length});
    })()""".replace("{CID}", str(cid)).replace("{BT}", B["access"]).replace("{MID}", str(m2["id"]))
    ok, res, log = shot(a.base + "/?v=w59-manual", SHOTS / "w59-9-manual.png",
                        js=js_manual, wait=900)
    d = jparse(res)
    step("manual: Descargar guarda solo en la app",
         ok and d.get("key") and (d.get("appCalls") or {}).get("begin") == 0 and
         (d.get("appCalls") or {}).get("open") == 0, d or log[-400:])
    step("manual: Guardar en el dispositivo es la única exportación",
         (d.get("exp") or {}).get("native") is True and
         (d.get("exportCalls") or {}).get("begin") == 1 and
         (d.get("exportCalls") or {}).get("finish") == 1, d)
    step("adjuntos: un solo control y sin enlaces de descarga",
         (d.get("states") == d.get("msgs")) and d.get("anchors") == 0, d)

    # Lightbox: tampoco exporta al dispositivo.
    js_lb = """(async () => {
      const sleep=ms=>new Promise(r=>setTimeout(r,ms));
      const wait=async(fn,ms=12000)=>{const t=Date.now();while(Date.now()-t<ms){const v=fn();if(v)return v;await sleep(120);}return null;};
      const calls={begin:0,open:0};
      window.FoxinixAndroid={storagePermission:()=> 'granted',
        permissionState:()=> 'granted', requestPermissionFor:()=> 'granted',
        permission:()=> 'granted',
        beginSave:()=>{calls.begin++;return 'ok';},appendSave:()=>true,
        finishSave:()=> 'ok:x',cancelSave:()=>{},insets:()=> '0,0,0,0'};
      window.open=function(){calls.open++;return null;};
      const t0=Date.now(); while(Date.now()-t0<20000 && window.__fm && __fm.store.booting) await sleep(150);
      const item=await wait(()=>document.querySelector('.chat-item[data-chat-id="{CID}"]'),12000);
      if(!item) return 'FAIL sin chat';
      item.click();
      const frame=await wait(()=>document.querySelector('.msgs .msg .mframe'),10000);
      if(!frame) return 'FAIL sin imagen';
      frame.click();
      const lb=await wait(()=>document.querySelector('.lightbox'),6000);
      if(!lb) return 'FAIL sin visor';
      const b=lb.querySelector('.lb-dl');
      if(!b) return 'FAIL sin botón';
      b.click(); await sleep(700);
      return JSON.stringify({begin:calls.begin,open:calls.open});
    })()"""
    ok, res, log = shot(a.base + "/?v=w59-lb", SHOTS / "w59-10-visor.png",
                        js=js_lb.replace("{CID}", str(cid)), wait=700)
    d = jparse(res)
    step("visor: descargar no exporta al dispositivo",
         ok and d.get("begin") == 0, d or log[-400:])

    # ---------------- botón bajar / áreas seguras móviles ----------------
    print("→ móvil")
    js_mobile = """(async () => {
      const sleep=ms=>new Promise(r=>setTimeout(r,ms));
      const wait=async(fn,ms=12000)=>{const t=Date.now();while(Date.now()-t<ms){const v=fn();if(v)return v;await sleep(120);}return null;};
      document.documentElement.style.setProperty('--sab','34px');
      const t0=Date.now(); while(Date.now()-t0<20000 && window.__fm && __fm.store.booting) await sleep(150);
      const item=await wait(()=>document.querySelector('.chat-item[data-chat-id="{CID}"]'),12000);
      if(!item) return 'FAIL sin chat';
      item.click();
      await wait(()=>document.querySelector('.msgs .msg'),10000);
      const b=document.querySelector('.msgs .msg .b-act[title="Responder"]');
      if(b) b.click();
      await wait(()=>document.querySelector('.reply-bar'),5000);
      const msgs=document.querySelector('.msgs');
      if (msgs && msgs.scrollHeight <= msgs.clientHeight + 40) {
        for (let i = 0; i < 8; i++) {
          const d = document.createElement('div');
          d.className = 'msg';
          d.innerHTML = '<div class="bubble"><div class="b-text">relleno W59 ' + i + '</div></div>';
          msgs.appendChild(d);
        }
        await sleep(120);
      }
      if(msgs) msgs.scrollTop=0;
      await sleep(700);
      const jump=document.querySelector('.jump-bottom');
      const comp=document.querySelector('.composer');
      const input=document.querySelector('.composer textarea.composer-input');
      const reply=document.querySelector('.reply-bar');
      const r=el=>{if(!el)return null;const x=el.getBoundingClientRect();return {top:Math.round(x.top),bottom:Math.round(x.bottom),left:Math.round(x.left),right:Math.round(x.right)};};
      return JSON.stringify({ih:innerHeight,sab:getComputedStyle(document.documentElement).getPropertyValue('--sab').trim(),
        jump:r(jump),comp:r(comp),input:r(input),reply:r(reply),jumpVisible:!!jump,replyVisible:!!reply});
    })()""".replace("{CID}", str(cid))
    ok, res, log = shot(a.base + "/?v=w59-mobile", SHOTS / "w59-11-movil.png",
                        js=js_mobile, wait=900, width=390, height=844, viewport=True)
    d = jparse(res)
    ih = d.get("ih") or 844
    jump, comp, inp = d.get("jump"), d.get("comp"), d.get("input")
    step("móvil: el botón de bajar queda por encima del compositor",
         ok and jump and comp and jump["bottom"] <= comp["top"] - 4, d or log[-400:])
    step("móvil: el botón de bajar no entra en la barra de navegación",
         jump and jump["bottom"] <= ih - 34, d)
    step("móvil: el campo de texto queda sobre el área de gestos",
         inp and inp["bottom"] <= ih - 34, d)
    step("móvil: la barra de respuesta no tapa el botón de bajar",
         d.get("replyVisible") and jump and d.get("reply") and jump["bottom"] <= d["reply"]["top"] - 4, d)

    js_tabs = """(async () => {
      const sleep=ms=>new Promise(r=>setTimeout(r,ms));
      const wait=async(fn,ms=15000)=>{const t=Date.now();while(Date.now()-t<ms){const v=fn();if(v)return v;await sleep(120);}return null;};
      document.documentElement.style.setProperty('--sab','34px');
      await wait(()=>window.__fm && !__fm.store.booting,20000);
      const tabs=await wait(()=>document.querySelector('.mobile-tabs'),8000);
      const btns=tabs?Array.from(tabs.querySelectorAll('.mt-btn')):[];
      const r=el=>{const x=el.getBoundingClientRect();return {top:Math.round(x.top),bottom:Math.round(x.bottom)};};
      // un aviso flotante no debe caer dentro del área de navegación
      const tst=document.createElement('div'); tst.className='toasts';
      tst.innerHTML='<div class="toast">W59</div>'; document.body.appendChild(tst);
      const cb=document.createElement('div'); cb.className='callbox'; document.body.appendChild(cb);
      const tRect=r(tst), cRect=r(cb);
      tst.remove(); cb.remove();
      return JSON.stringify({ih:innerHeight,sab:getComputedStyle(document.documentElement).getPropertyValue('--sab').trim(),
        tabs:tabs?r(tabs):null,btns:btns.map(r),toasts:tRect,callbox:cRect});
    })()"""
    ok, res, log = shot(a.base + "/?v=w59-tabs", SHOTS / "w59-12-tabs.png",
                        js=js_tabs, wait=700, width=390, height=844, viewport=True)
    d = jparse(res)
    ih = d.get("ih") or 844
    step("móvil: los botones de la barra inferior quedan sobre la navegación",
         ok and d.get("btns") and all(b["bottom"] <= ih - 34 for b in d["btns"]), d)
    step("móvil: avisos y llamada no cruzan el área de navegación",
         (d.get("toasts") or {}).get("bottom", ih) <= ih - 34 and
         (d.get("callbox") or {}).get("bottom", ih) <= ih - 34, d)

    # ---------------- tema Android ----------------
    js_theme = """(async () => {
      const sleep=ms=>new Promise(r=>setTimeout(r,ms));
      const calls=[]; window.FoxinixAndroid={setSystemBars:v=>calls.push(!!v),
        insets:()=> '0,34,0,0'};
      __fm.theme('light'); await sleep(120);
      const light=Array.from(document.querySelectorAll('meta[name="theme-color"]')).map(m=>m.content);
      __fm.theme('dark'); await sleep(120);
      const dark=Array.from(document.querySelectorAll('meta[name="theme-color"]')).map(m=>m.content);
      return JSON.stringify({calls:calls,light:light,dark:dark});
    })()"""
    ok, res, log = shot(a.base + "/?v=w59-theme", SHOTS / "w59-13-tema.png",
                        js=js_theme, wait=500)
    d = jparse(res)
    step("Android: tema claro pide iconos oscuros y oscuro claros",
         ok and d.get("calls") and d["calls"][-1] is False and True in d["calls"], d)
    step("la meta theme-color sigue al tema",
         (d.get("light") or [""])[0].lower() == "#f2f3f5" and
         (d.get("dark") or [""])[0].lower() == "#2b2d31", d)

    print(f"W59: {_pass[0]} bien, {_fail[0]} mal")
    return 0 if _fail[0] == 0 else 1


if __name__ == "__main__":
    code = 1
    try:
        code = main()
    finally:
        ok = ct.cleanup_db()
        print("· datos de prueba eliminados de la DB local" if ok else "· WARN limpieza")
    raise SystemExit(code)
