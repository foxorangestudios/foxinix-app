#!/usr/bin/env python3
"""E2E W61: perfiles en llamadas, portada reposicionable, globo de llamada
arrastrable, bios de 300 con "Ver más", visor de portada/avatar, mensajes
de 3000 con autoarchivo y biblioteca de GIFs/stickers (máx. 10 por tipo).

Uso: server/.venv/bin/python tests/w61_test.py [--base http://127.0.0.1:8899]
"""
import argparse
import asyncio
import json
import shutil
import sqlite3
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
MEDIA_DIR = ROOT / "server" / "data" / "media"
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


def accept_friend(base, a, b):
    uid = a["user"]["id"]
    st, rq = ct.http("POST", base + "/api/people/requests",
                     {"username": b["user"]["username"]}, token=a["access"])
    st2, ppl = ct.http("GET", base + "/api/people", token=b["access"])
    rid = None
    for row in (ppl.get("received") or []):
        u = row.get("user") or {}
        if u.get("id") == uid or row.get("id") == uid:
            rid = row.get("id") or row.get("request_id") or u.get("id")
            break
    if rid is None:
        return False
    st3, _ = ct.http("POST", base + f"/api/people/requests/{rid}/accept",
                     {}, token=b["access"])
    return st in (200, 201) and st3 in (200, 201)


def clone_media(owner_id, source_id, count, tag):
    """Clona filas de media ya subidas para probar el tope sin gastar la
    ráfaga de subidas (1 cada 5 s). El test corre contra la DB local."""
    con = sqlite3.connect(str(ROOT / "server" / "data" / "foxmsg.db"), timeout=15)
    con.row_factory = sqlite3.Row
    row = con.execute("SELECT path, mime, size, name, width, height FROM media"
                      " WHERE id = ?", (source_id,)).fetchone()
    if not row:
        con.close()
        return []
    src = MEDIA_DIR / row["path"]
    ext = src.suffix or ".bin"
    out = []
    for i in range(count):
        rel = f"{owner_id}/w61-clone-{tag}-{i}{ext}"
        dest = MEDIA_DIR / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
        cur = con.execute(
            "INSERT INTO media (owner_id, path, mime, size, name, slug,"
            " width, height, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (owner_id, rel, row["mime"], row["size"],
             f"w61-clone-{tag}-{i}{ext}", uuid.uuid4().hex,
             row["width"], row["height"], int(time.time())),
        )
        out.append(int(cur.lastrowid))
    con.commit()
    con.close()
    return out


def ws_call_profile(base, a_tok, b_tok, cid):
    """Dos WS reales: B debe recibir la oferta con el perfil completo."""
    import websockets

    async def run():
        url = base.replace("http://", "ws://").replace("https://", "wss://") + "/api/ws"
        wb = await websockets.connect(url, subprotocols=["foxinix", b_tok],
                                      open_timeout=12)
        wa = await websockets.connect(url, subprotocols=["foxinix", a_tok],
                                      open_timeout=12)
        try:
            await asyncio.sleep(0.25)
            await wa.send(json.dumps({
                "type": "call_offer", "chat_id": cid,
                "sdp": "v=0\r\no=- 1 1 IN IP4 127.0.0.1\r\n", "video": True,
            }))
            for _ in range(20):
                raw = await asyncio.wait_for(wb.recv(), timeout=6)
                msg = json.loads(raw)
                if msg.get("type") == "call_offer":
                    return msg
            return None
        finally:
            await wa.close()
            await wb.close()

    return asyncio.run(run())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8899")
    a = ap.parse_args()
    SHOTS.mkdir(parents=True, exist_ok=True)
    tag = uuid.uuid4().hex[:6]

    print("→ preparar usuarios, perfiles y conversación")
    A = ct.register(a.base, f"w61a{tag}@t.fi", f"w61a{tag}")
    B = ct.register(a.base, f"w61b{tag}@t.fi", f"w61b{tag}")
    AU, BU = A["user"]["username"], B["user"]["username"]
    AID = A["user"]["id"]

    # Portada con tres franjas: el object-position se puede comprobar a ojo
    # y mediante el estilo calculado.
    banner = SHOTS / f"w61-bn-{tag}.png"
    im = Image.new("RGB", (900, 300))
    dr = ImageDraw.Draw(im)
    dr.rectangle((0, 0, 900, 99), fill=(30, 170, 90))
    dr.rectangle((0, 100, 900, 199), fill=(245, 245, 245))
    dr.rectangle((0, 200, 900, 300), fill=(120, 60, 200))
    im.save(banner)
    av = SHOTS / f"w61-av-{tag}.png"
    Image.new("RGB", (256, 256), (255, 120, 0)).save(av)

    av_m = ct.upload(a.base, A["access"], av)
    bn_a = ct.upload(a.base, A["access"], banner)
    bio_a = ("A " + "La portada se puede mover y la bio larga se recorta con "
                    "Ver más. " * 8)[:300]
    st, r = ct.http("PUT", a.base + "/api/auth/profile",
                    {"display_name": "Ana W61", "bio": bio_a,
                     "banner_position": 12,
                     "avatar_media_id": av_m["id"],
                     "banner_media_id": bn_a["id"]}, token=A["access"])
    if st != 200:
        raise SystemExit(f"✗ perfil A: {st} {r}")
    A["user"] = r["user"]

    bbn = ct.upload(a.base, B["access"], banner)
    bav = ct.upload(a.base, B["access"], av)
    bio_b = ("B " + "Texto de presentación bastante largo para probar el "
                    "enlace Ver más. " * 5)[:120]
    st, r = ct.http("PUT", a.base + "/api/auth/profile",
                    {"display_name": "Beto W61", "bio": bio_b,
                     "banner_position": 70, "avatar_media_id": bav["id"],
                     "banner_media_id": bbn["id"]}, token=B["access"])
    if st != 200:
        raise SystemExit(f"✗ perfil B: {st} {r}")
    B["user"] = r["user"]

    # Límites de perfil y posición.
    st, r = ct.http("PUT", a.base + "/api/auth/profile",
                    {"bio": "x" * 301}, token=A["access"])
    step("bio: el servidor rechaza 301 caracteres", st in (400, 422), (st, r))
    st, me = ct.http("GET", a.base + "/api/users/me", token=A["access"])
    step("bio: 300 caracteres persisten", st == 200 and
         len((me.get("user") or {}).get("bio", "")) == 300, me)
    st, r = ct.http("PUT", a.base + "/api/auth/profile",
                    {"banner_position": 101}, token=A["access"])
    step("portada: posición fuera de 0–100 rechazada", st in (400, 422), (st, r))
    st, pu = ct.http("GET", a.base + f"/api/users/{AU}", token=B["access"])
    step("perfil público incluye banner_position",
         st == 200 and (pu.get("user") or {}).get("banner_position") == 12, pu)

    step("amistad A-B", accept_friend(a.base, A, B))
    st, dm = ct.http("POST", a.base + "/api/chats/dm",
                     {"username": BU}, token=A["access"])
    cid = (dm.get("chat") or {}).get("id")
    step("DM creada", st in (200, 201) and bool(cid), dm)
    if not cid:
        raise SystemExit("sin DM")

    # Límite de cuerpo: 3000 entra, 3001 lo rechaza Pydantic.
    body3000 = "a" * 3000
    m3000 = ct.send(a.base, A["access"], cid, {
        "kind": "text", "body": body3000,
        "client_msg_id": str(uuid.uuid4())})
    step("mensaje: 3000 caracteres aceptados",
         len(m3000.get("body", "")) == 3000, len(m3000.get("body", "")))
    st, r = ct.http("POST", a.base + f"/api/chats/{cid}/messages",
                    {"kind": "text", "body": "a" * 3001,
                     "client_msg_id": str(uuid.uuid4())},
                    token=A["access"])
    step("mensaje: 3001 caracteres rechazados por el servidor",
         st in (400, 422), (st, r))

    # Archivos de la biblioteca.
    sticker_file = SHOTS / f"w61-sticker-{tag}.png"
    sim = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    sd = ImageDraw.Draw(sim)
    sd.ellipse((12, 12, 244, 244), fill=(240, 30, 180, 255))
    sd.rectangle((88, 88, 168, 168), fill=(255, 255, 255, 255))
    sim.save(sticker_file)
    sticker_m = ct.upload(a.base, A["access"], sticker_file)

    gif_file = SHOTS / f"w61-gif-{tag}.gif"
    frames = []
    for color in ((255, 0, 0), (0, 160, 255)):
        fr = Image.new("RGB", (240, 240), color)
        frames.append(fr)
    frames[0].save(gif_file, save_all=True, append_images=frames[1:],
                   duration=120, loop=0)
    gif_m = ct.upload(a.base, A["access"], gif_file)

    st, r = ct.http("POST", a.base + "/api/assets",
                    {"kind": "sticker", "media_id": sticker_m["id"]},
                    token=A["access"])
    ast = (r.get("asset") or {}) if st == 201 else {}
    step("biblioteca: sticker propio guardado",
         st == 201 and ast.get("media_id") == sticker_m["id"] and
         (ast.get("mime") or "").startswith("image/"), (st, r))
    st, r2 = ct.http("POST", a.base + "/api/assets",
                     {"kind": "sticker", "media_id": sticker_m["id"]},
                     token=A["access"])
    step("biblioteca: guardar dos veces no duplica",
         st == 201 and (r2.get("asset") or {}).get("id") == ast.get("id"), r2)
    st, r = ct.http("POST", a.base + "/api/assets",
                    {"kind": "gif", "media_id": sticker_m["id"]},
                    token=A["access"])
    step("biblioteca: un PNG no entra como GIF",
         st == 400 and "GIF" in json.dumps(r), (st, r))
    st, r = ct.http("POST", a.base + "/api/assets",
                    {"kind": "otro", "media_id": sticker_m["id"]},
                    token=A["access"])
    step("biblioteca: tipo inválido rechazado", st == 400, (st, r))

    # B no puede guardar un archivo privado de A que aún no se envió.
    st, r = ct.http("POST", a.base + "/api/assets",
                    {"kind": "sticker", "media_id": bn_a["id"]},
                    token=B["access"])
    step("biblioteca: un archivo ajeno no enviado no se puede guardar",
         st == 404, (st, r))

    st, r = ct.http("POST", a.base + "/api/assets",
                    {"kind": "gif", "media_id": gif_m["id"]},
                    token=A["access"])
    gif_asset = (r.get("asset") or {}) if st == 201 else {}
    step("biblioteca: GIF propio guardado",
         st == 201 and gif_asset.get("media_id") == gif_m["id"] and
         gif_asset.get("mime") == "image/gif", (st, r))

    # A envía el sticker; B lo guarda y lo reenvía (sin subirlo de nuevo).
    emoji_msg = ct.send(a.base, A["access"], cid, {
        "kind": "text", "body": "😂😂😂",
        "client_msg_id": str(uuid.uuid4())})
    step("emojis: mensaje de 3 se guarda como texto",
         emoji_msg.get("body") == "😂😂😂", emoji_msg.get("body"))
    sticker_msg = ct.send(a.base, A["access"], cid, {
        "kind": "sticker", "body": "", "media_id": sticker_m["id"],
        "client_msg_id": str(uuid.uuid4())})
    step("sticker: se envía una imagen como sticker",
         sticker_msg.get("kind") == "sticker" and
         (sticker_msg.get("media") or {}).get("id") == sticker_m["id"],
         sticker_msg)

    st, r = ct.http("POST", a.base + "/api/assets",
                    {"kind": "sticker", "media_id": sticker_m["id"]},
                    token=B["access"])
    b_sticker_asset = (r.get("asset") or {}) if st == 201 else {}
    step("biblioteca: B guarda un sticker recibido",
         st == 201 and b_sticker_asset.get("media_id") == sticker_m["id"],
         (st, r))

    resent = ct.send(a.base, B["access"], cid, {
        "kind": "sticker", "body": "", "media_id": sticker_m["id"],
        "client_msg_id": str(uuid.uuid4())})
    step("biblioteca: B reenvía el sticker guardado de A",
         (resent.get("sender") or {}).get("username") == BU and
         (resent.get("media") or {}).get("id") == sticker_m["id"], resent)

    b_gif = ct.upload(a.base, B["access"], gif_file)
    st, r = ct.http("POST", a.base + "/api/assets",
                    {"kind": "gif", "media_id": b_gif["id"]},
                    token=B["access"])
    step("biblioteca: B guarda un GIF propio",
         st == 201 and (r.get("asset") or {}).get("media_id") == b_gif["id"],
         (st, r))
    b_gif_resent = ct.send(a.base, B["access"], cid, {
        "kind": "image", "body": "", "media_id": b_gif["id"],
        "client_msg_id": str(uuid.uuid4())})
    step("biblioteca: B reenvía su GIF guardado",
         (b_gif_resent.get("media") or {}).get("mime") == "image/gif",
         b_gif_resent)

    # Tope de 10 GIFs y 10 stickers: los clones evitan 18 esperas de subida.
    gif_clones = clone_media(B["user"]["id"], b_gif["id"], 10, f"g{tag}")
    for mid in gif_clones[:9]:
        st, r = ct.http("POST", a.base + "/api/assets",
                        {"kind": "gif", "media_id": mid}, token=B["access"])
        if st != 201:
            break
    st, r = ct.http("POST", a.base + "/api/assets",
                    {"kind": "gif", "media_id": gif_clones[9]},
                    token=B["access"])
    step("biblioteca: máximo 10 GIFs validado en el servidor",
         st == 400 and "Máximo 10 GIFs" in (r.get("detail") or ""), (st, r))
    st, lib = ct.http("GET", a.base + "/api/assets", token=B["access"])
    step("biblioteca: el listado devuelve 10 GIFs",
         st == 200 and len(lib.get("gifs") or []) == 10, len(lib.get("gifs") or []))

    st_clones = clone_media(B["user"]["id"], sticker_m["id"], 10, f"s{tag}")
    for mid in st_clones[:9]:
        st, r = ct.http("POST", a.base + "/api/assets",
                        {"kind": "sticker", "media_id": mid}, token=B["access"])
        if st != 201:
            break
    st, r = ct.http("POST", a.base + "/api/assets",
                    {"kind": "sticker", "media_id": st_clones[9]},
                    token=B["access"])
    step("biblioteca: máximo 10 stickers validado en el servidor",
         st == 400 and "Máximo 10 stickers" in (r.get("detail") or ""), (st, r))

    st, _ = ct.http("POST", a.base + "/api/assets",
                    {"kind": "gif", "media_id": b_gif["id"]},
                    token=B["access"])
    step("biblioteca: repetir un GIF ya guardado no falla al estar lleno",
         st == 201, st)

    # ---------------- preparar navegador ----------------
    shot(a.base + "/", SHOTS / "w61-0-prep.png",
         js="(async()=>{try{const rs=await navigator.serviceWorker.getRegistrations();"
            "for(const r of rs)await r.unregister();}catch(e){};"
            "try{const ks=await caches.keys();for(const k of ks)await caches.delete(k);}catch(e){};"
            "localStorage.removeItem('fm.session');return 'ok';})()",
         wait=300)
    ok, res, log = shot(a.base + "/", SHOTS / "w61-1-sesion.png",
                        js=sess_js(A), wait=300)
    step("sesión de A inyectada", ok and res == "sesión inyectada",
         res or log[-400:])

    # ---------------- perfil propio: bio, visor y portada ----------------
    js_profile = """(async () => {
      const sleep = ms => new Promise(r => setTimeout(r, ms));
      const wait = async (fn, ms=15000) => { const t=Date.now(); while(Date.now()-t<ms){const v=fn(); if(v) return v; await sleep(100);} return null; };
      await wait(() => window.__fm && !__fm.store.booting, 20000);
      __fm.store.meProfileOpen = true;
      const mp = await wait(() => document.querySelector('.modal.meprof'), 8000);
      if (!mp) return JSON.stringify({err:'sin perfil'});
      await sleep(300);
      const out = {};
      const bimg = mp.querySelector('.pf-banner img');
      out.objectPos = bimg ? getComputedStyle(bimg).objectPosition : '';
      const bio = mp.querySelector('.pf-bio-wrap .pp-bio');
      const more = mp.querySelector('.pf-bio-more');
      out.bioBefore = bio ? bio.textContent.trim().length : 0;
      out.moreText = more ? more.textContent.trim() : '';
      if (more) more.click();
      await sleep(250);
      out.bioAfter = bio ? Array.from(bio.textContent.trim()).length : 0;
      out.lessText = (mp.querySelector('.pf-bio-more')||{}).textContent || '';
      // visor: portada y avatar deben pedir el original, sin ?thumb=1
      if (bimg) bimg.click();
      await wait(() => document.querySelector('.lightbox'), 5000);
      out.lbBanner = __fm.store.lb ? {url:__fm.store.lb.url, orig:__fm.store.lb.orig} : null;
      const x = document.querySelector('.lightbox .lb-close'); if (x) x.click();
      await sleep(200);
      const av = mp.querySelector('.pf-avwrap img');
      if (av) av.click();
      await wait(() => document.querySelector('.lightbox'), 5000);
      out.lbAvatar = __fm.store.lb ? {url:__fm.store.lb.url, orig:__fm.store.lb.orig} : null;
      const x2 = document.querySelector('.lightbox .lb-close'); if (x2) x2.click();
      await sleep(200);
      // editor de portada: barra, arrastre y guardado
      const edit = Array.from(mp.querySelectorAll('button')).find(b => b.textContent.indexOf('Editar perfil') >= 0);
      if (!edit) return JSON.stringify(Object.assign(out, {err:'sin editar'}));
      edit.click();
      const em = await wait(() => document.querySelector('.modal.meprof.mp-edit'), 8000);
      const range = em && em.querySelector('.pf-pos-range');
      out.rangeStart = range ? range.value : '';
      out.hint = !!(em && em.querySelector('.pf-pos-hint'));
      const eb = em && em.querySelector('.pf-edit-banner-img');
      const eimg = em && eb && eb.querySelector('img');
      out.editPosStart = eimg ? getComputedStyle(eimg).objectPosition : '';
      if (eb) {
        const br = eb.getBoundingClientRect();
        const y = br.top + br.height / 2;
        eb.dispatchEvent(new PointerEvent('pointerdown', {bubbles:true, clientX:br.left+20, clientY:y, button:0, pointerId:4, isPrimary:true, pointerType:'mouse'}));
        window.dispatchEvent(new PointerEvent('pointermove', {bubbles:true, clientX:br.left+20, clientY:y-18, button:0, pointerId:4, isPrimary:true, pointerType:'mouse'}));
        window.dispatchEvent(new PointerEvent('pointerup', {bubbles:true, clientX:br.left+20, clientY:y-18, button:0, pointerId:4, isPrimary:true, pointerType:'mouse'}));
        await sleep(150);
        out.editPosDragged = eimg ? getComputedStyle(eimg).objectPosition : '';
      }
      if (range) {
        range.value = '65';
        range.dispatchEvent(new Event('input', {bubbles:true}));
      }
      await sleep(200);
      out.editPos65 = eimg ? getComputedStyle(eimg).objectPosition : '';
      out.range65 = range ? range.value : '';
      const save = em && em.querySelector('.m-foot .btn:not(.btn-ghost)');
      if (save) save.click();
      const closed = await wait(() => (__fm.store.user||{}).banner_position === 65 &&
        !document.querySelector('.modal.meprof.mp-edit'), 12000);
      out.userPos = (__fm.store.user||{}).banner_position;
      out.editClosed = !!closed;
      return JSON.stringify(out);
    })()"""
    ok, res, log = shot(a.base + "/?v=w61-profile", SHOTS / "w61-2-perfil.png",
                        js=js_profile, wait=700)
    d = jparse(res)
    step("perfil: portada con la posición guardada",
         ok and d.get("objectPos") == "50% 12%", d or log[-400:])
    step("bio: 300 caracteres se recortan con Ver más",
         d.get("bioBefore", 0) < 120 and d.get("moreText") == "Ver más" and
         d.get("bioAfter") == 300 and d.get("lessText") == "Ver menos", d)
    step("visor: portada y avatar sin miniatura ?thumb=1",
         "thumb=1" not in ((d.get("lbBanner") or {}).get("url") or "") and
         "thumb=1" not in ((d.get("lbBanner") or {}).get("orig") or "") and
         "thumb=1" not in ((d.get("lbAvatar") or {}).get("url") or "") and
         "thumb=1" not in ((d.get("lbAvatar") or {}).get("orig") or ""), d)
    step("portada: editor con arrastre, barra y vista previa",
         d.get("rangeStart") == "12" and d.get("hint") and
         d.get("editPosStart") == "50% 12%" and
         d.get("editPosDragged") != "50% 12%" and
         d.get("editPos65") == "50% 65%" and d.get("range65") == "65", d)
    step("portada: la posición se guarda en el perfil",
         d.get("userPos") == 65 and d.get("editClosed"), d)
    st, me = ct.http("GET", a.base + "/api/users/me", token=A["access"])
    step("portada: /users/me devuelve 65",
         st == 200 and (me.get("user") or {}).get("banner_position") == 65, me)

    # ---------------- chat: emojis, biblioteca y perfil ajeno ----------------
    js_chat = """(async () => {
      const sleep = ms => new Promise(r => setTimeout(r, ms));
      const wait = async (fn, ms=15000) => { const t=Date.now(); while(Date.now()-t<ms){const v=fn(); if(v) return v; await sleep(100);} return null; };
      const cid = {CID};
      await wait(() => window.__fm && !__fm.store.booting, 20000);
      const item = await wait(() => document.querySelector('.chat-item[data-chat-id="' + cid + '"]'), 12000);
      if (!item) return JSON.stringify({err:'sin chat'});
      item.click();
      await wait(() => (__fm.store.msgs[cid]||[]).length > 0, 12000);
      await sleep(900);
      const out = {assetsAtBoot: {
        stickers: __fm.store.userAssets.stickers.length,
        gifs: __fm.store.userAssets.gifs.length}};
      const emo = await import('/static/js/emoji.js');
      out.emo = {
        one: emo.isEmojiBurst('😂'),
        three: emo.isEmojiBurst('😂😂😍'),
        spaced: emo.isEmojiBurst('😂 😂'),
        four: emo.isEmojiBurst('😂😂😂😂'),
        family: emo.isEmojiBurst('👨‍👩‍👧‍👦'),
        text: emo.isEmojiBurst('hola 😂')
      };
      out.emoBig = document.querySelectorAll('.msgs .bubble.emo-big').length;
      const srow = document.querySelector('.msgs .msg .b-sticker-img');
      out.stickerImg = !!srow;
      const simg = srow && srow.querySelector('img');
      out.stickerLoaded = !!(simg && simg.complete && simg.naturalWidth > 0);
      const sacts = srow ? Array.from(srow.closest('.msg').querySelectorAll('.b-act[title]')) : [];
      const sStar = sacts.find(x => /favorit|stickers/i.test(x.getAttribute('title')||''));
      out.starTitle = sStar ? sStar.getAttribute('title') : '';
      const pick = document.querySelector('.comp-emo'); if (pick) pick.click();
      const panel = await wait(() => document.querySelector('.st-panel'), 6000);
      out.tabs = panel ? Array.from(panel.querySelectorAll('.ep-tab')).map(x=>x.textContent.trim()) : [];
      const tab = txt => {
        const b = panel ? Array.from(panel.querySelectorAll('.ep-tab')).find(x=>x.textContent.trim()===txt) : null;
        if (b) b.click();
        return !!b;
      };
      tab('Stickers'); await sleep(500);
      out.stCount = ((panel||document).querySelector('.st-count')||{}).textContent || '';
      out.stTile = !!(panel && panel.querySelector('.st-g.st-sticker img'));
      tab('GIFs'); await sleep(500);
      out.gifCount = ((panel||document).querySelector('.st-count')||{}).textContent || '';
      out.gifTile = !!(panel && panel.querySelector('.st-g img'));
      if (pick) pick.click();
      await sleep(200);
      // perfil de B desde la cabecera
      __fm.store.infoOpen = true;
      const col = document.querySelector('.chat-head .ch-col');
      if (col) col.click();
      const modal = await wait(() => document.querySelector('.modal.pmodal'), 8000);
      if (modal) {
        const bim = modal.querySelector('.pf-banner img');
        out.peerPos = bim ? getComputedStyle(bim).objectPosition : '';
        const bb = modal.querySelector('.pf-bio-wrap .pp-bio');
        const bm = modal.querySelector('.pf-bio-more');
        out.peerBioBefore = bb ? bb.textContent.trim().length : 0;
        if (bm) bm.click(); await sleep(200);
        out.peerBioAfter = bb ? Array.from(bb.textContent.trim()).length : 0;
      }
      return JSON.stringify(out);
    })()""".replace("{CID}", str(cid))
    ok, res, log = shot(a.base + "/?v=w61-chat", SHOTS / "w61-3-chat.png",
                        js=js_chat, wait=700)
    d = jparse(res)
    step("chat: biblioteca cargada al arrancar (estrella de sticker rellena)",
         ok and d.get("assetsAtBoot", {}).get("stickers") == 1 and
         d.get("starTitle") == "Quitar de favoritos", d or log[-400:])
    step("emojis: 1–3 grandes, 4 no, compuestos cuentan como uno",
         d.get("emo", {}).get("one") is True and
         d.get("emo", {}).get("three") is True and
         d.get("emo", {}).get("spaced") is True and
         d.get("emo", {}).get("four") is False and
         d.get("emo", {}).get("family") is True and
         d.get("emo", {}).get("text") is False and
         d.get("emoBig", 0) >= 1, d)
    step("sticker: la imagen se pinta sin marco y se carga",
         d.get("stickerImg") and d.get("stickerLoaded"), d)
    step("biblioteca: selector con contadores y miniaturas propias",
         d.get("tabs") == ["Emojis", "Stickers", "GIFs"] and
         d.get("stCount") == "1/10" and d.get("stTile") and
         d.get("gifCount") == "1/10" and d.get("gifTile"), d)
    step("perfil ajeno: portada en su posición y bio con Ver más",
         d.get("peerPos") == "50% 70%" and d.get("peerBioBefore", 0) < 120 and
         d.get("peerBioAfter") == 120, d)

    # ---------------- texto largo: autoarchivo ----------------
    js_long = """(async () => {
      const sleep = ms => new Promise(r => setTimeout(r, ms));
      const wait = async (fn, ms=30000) => { const t=Date.now(); while(Date.now()-t<ms){const v=fn(); if(v) return v; await sleep(120);} return null; };
      const cid = {CID};
      await wait(() => window.__fm && !__fm.store.booting, 20000);
      const item = await wait(() => document.querySelector('.chat-item[data-chat-id="' + cid + '"]'), 12000);
      if (!item) return JSON.stringify({err:'sin chat'});
      item.click();
      await wait(() => (__fm.store.msgs[cid]||[]).length > 0, 12000);
      await sleep(300);
      const ta = document.querySelector('.composer-input');
      if (!ta) return JSON.stringify({err:'sin input'});
      ta.value = 'x'.repeat(3001);
      ta.dispatchEvent(new Event('input', {bubbles:true}));
      await sleep(300);
      const hint = document.querySelector('.composer-long');
      const out = {hint: hint ? hint.textContent.replace(/\\s+/g,' ').trim() : ''};
      const before = (__fm.store.msgs[cid]||[]).length;
      const send = document.querySelector('.send-btn'); if (send) send.click();
      const lm = await wait(() => {
        const arr = __fm.store.msgs[cid] || [];
        const m = arr.length > before ? arr[arr.length-1] : null;
        return m && !m.pending && m.media && m.media.name === 'mensaje.txt' ? m : null;
      }, 30000);
      out.kind = lm ? lm.kind : '';
      out.pending = !!(lm && lm.pending);
      out.name = lm && lm.media ? lm.media.name : '';
      out.mime = lm && lm.media ? lm.media.mime : '';
      out.size = lm && lm.media ? lm.media.size : 0;
      out.draft = ta.value.length;
      out.hintAfter = !!document.querySelector('.composer-long');
      out.rowTxt = (document.querySelector('.msgs .msg:last-child .bubble')||{}).textContent || '';
      return JSON.stringify(out);
    })()""".replace("{CID}", str(cid))
    ok, res, log = shot(a.base + "/?v=w61-long", SHOTS / "w61-4-largo.png",
                        js=js_long, wait=900)
    d = jparse(res)
    step("texto largo: el compositor avisa 3001/3000",
         ok and "3001/3000" in (d.get("hint") or ""), d or log[-400:])
    step("texto largo: se envía como mensaje.txt real",
         d.get("kind") == "file" and not d.get("pending") and
         d.get("name") == "mensaje.txt" and d.get("mime") == "text/plain" and
         d.get("size") == 3001, d)
    step("texto largo: se limpia el compositor y el aviso",
         d.get("draft") == 0 and not d.get("hintAfter"), d)

    st, msgs = ct.http("GET", a.base + f"/api/chats/{cid}/messages?limit=30",
                       token=A["access"])
    last_file = None
    for m in (msgs.get("messages") or []):
        if (m.get("media") or {}).get("name") == "mensaje.txt":
            last_file = m
    step("texto largo: el servidor guarda mensaje.txt en el chat",
         st == 200 and last_file is not None and
         (last_file.get("media") or {}).get("mime") == "text/plain",
         last_file)

    # ---------------- B: biblioteca con stickers recibidos ----------------
    shot(a.base + "/", SHOTS / "w61-5-sesion-b.png", js=sess_js(B), wait=300)
    js_b = """(async () => {
      const sleep = ms => new Promise(r => setTimeout(r, ms));
      const wait = async (fn, ms=15000) => { const t=Date.now(); while(Date.now()-t<ms){const v=fn(); if(v) return v; await sleep(100);} return null; };
      const cid = {CID};
      await wait(() => window.__fm && !__fm.store.booting, 20000);
      const item = await wait(() => document.querySelector('.chat-item[data-chat-id="' + cid + '"]'), 12000);
      if (!item) return JSON.stringify({err:'sin chat'});
      item.click();
      await wait(() => (__fm.store.msgs[cid]||[]).length > 0, 12000);
      // publicar la clave E2E (abrir el DM la genera si aún no existe)
      const pub = await wait(() => localStorage.getItem('fm.e2e.pub'), 15000);
      await sleep(600);
      const out = {pub: !!pub, stickers: __fm.store.userAssets.stickers.length,
        gifs: __fm.store.userAssets.gifs.length};
      const srow = document.querySelector('.msgs .msg .b-sticker-img');
      out.stickerImg = !!srow;
      const sacts = srow ? Array.from(srow.closest('.msg').querySelectorAll('.b-act[title]')) : [];
      const sStar = sacts.find(x => /favorit|stickers/i.test(x.getAttribute('title')||''));
      out.starTitle = sStar ? sStar.getAttribute('title') : '';
      const pick = document.querySelector('.comp-emo'); if (pick) pick.click();
      const panel = await wait(() => document.querySelector('.st-panel'), 6000);
      const tab = txt => {
        const b = panel ? Array.from(panel.querySelectorAll('.ep-tab')).find(x=>x.textContent.trim()===txt) : null;
        if (b) b.click();
        return !!b;
      };
      tab('Stickers'); await sleep(500);
      out.stCount = ((panel||document).querySelector('.st-count')||{}).textContent || '';
      out.stTile = !!(panel && panel.querySelector('.st-g.st-sticker img'));
      tab('GIFs'); await sleep(700);
      out.gifCount = ((panel||document).querySelector('.st-count')||{}).textContent || '';
      out.gifTile = !!(panel && panel.querySelector('.st-g img'));
      return JSON.stringify(out);
    })()""".replace("{CID}", str(cid))
    ok, res, log = shot(a.base + "/?v=w61-b", SHOTS / "w61-6-b.png",
                        js=js_b, wait=700)
    d = jparse(res)
    step("B: clave E2E publicada y biblioteca completa (10/10)",
         ok and d.get("pub") and d.get("stickers") == 10 and
         d.get("gifs") == 10 and d.get("stCount") == "10/10" and
         d.get("gifCount") == "10/10", d or log[-400:])
    step("B: el sticker recibido aparece con estrella rellena",
         d.get("stickerImg") and d.get("starTitle") == "Quitar de favoritos", d)

    # ---------------- emoji grande en un chat cifrado (A vuelve) ----------------
    shot(a.base + "/", SHOTS / "w61-7-sesion-a2.png", js=sess_js(A), wait=300)
    js_e2e = """(async () => {
      const sleep = ms => new Promise(r => setTimeout(r, ms));
      const wait = async (fn, ms=25000) => { const t=Date.now(); while(Date.now()-t<ms){const v=fn(); if(v) return v; await sleep(120);} return null; };
      const cid = {CID};
      await wait(() => window.__fm && !__fm.store.booting, 20000);
      const item = await wait(() => document.querySelector('.chat-item[data-chat-id="' + cid + '"]'), 12000);
      if (!item) return JSON.stringify({err:'sin chat'});
      item.click();
      const on = await wait(() => (__fm.store.e2e||{})[cid] === 1, 20000);
      if (!on) return JSON.stringify({e2e:false, pend:!!((__fm.store.e2ePend||{})[cid])});
      await wait(() => (__fm.store.msgs[cid]||[]).length > 0, 12000);
      await sleep(300);
      const ta = document.querySelector('.composer-input');
      ta.value = '😂😂😂';
      ta.dispatchEvent(new Event('input', {bubbles:true}));
      await sleep(200);
      const before = (__fm.store.msgs[cid]||[]).length;
      const send = document.querySelector('.send-btn'); if (send) send.click();
      const lm = await wait(() => {
        const arr = __fm.store.msgs[cid] || [];
        return arr.length > before ? arr[arr.length-1] : null;
      }, 25000);
      const row = lm ? document.querySelector('.msg[data-msg-id="' + lm.id + '"] .bubble') : null;
      return JSON.stringify({e2e: on, pending: !!(lm && lm.pending),
        encrypted: !!(lm && lm.e2e), plain: lm && lm._plain,
        body: lm && lm.body, big: !!(row && row.className.indexOf('emo-big') >= 0),
        rowClass: row ? row.className : ''});
    })()""".replace("{CID}", str(cid))
    ok, res, log = shot(a.base + "/?v=w61-e2e", SHOTS / "w61-8-e2e.png",
                        js=js_e2e, wait=700)
    d = jparse(res)
    step("E2E: el DM se cifra y 3 emojis se ven grandes",
         ok and d.get("e2e") and not d.get("pending") and d.get("encrypted") and
         d.get("plain") == "😂😂😂" and d.get("body") != "😂😂😂" and
         d.get("big"), d or log[-400:])

    # ---------------- llamada: perfil completo y globo arrastrable ----------------
    js_call = """(async () => {
      const sleep = ms => new Promise(r => setTimeout(r, ms));
      const wait = async (fn, ms=15000) => { const t=Date.now(); while(Date.now()-t<ms){const v=fn(); if(v) return v; await sleep(100);} return null; };
      const cid = {CID};
      await wait(() => window.__fm && !__fm.store.booting, 20000);
      const item = await wait(() => document.querySelector('.chat-item[data-chat-id="' + cid + '"]'), 12000);
      if (!item) return JSON.stringify({err:'sin chat'});
      item.click();
      await wait(() => (__fm.store.msgs[cid]||[]).length > 0, 12000);
      await sleep(300);
      __fm.store.call = {chatId:cid, peerId:{BID},
        peer:{id:{BID}, username:'{BU}', display_name:'Beto W61'},
        state:'active', video:false, hasCam:false, muted:false, camOff:true,
        startedAt:Date.now(), remote:true, remoteVideo:false, remoteMuted:false};
      const cb = await wait(() => document.querySelector('.callbox'), 8000);
      if (!cb) return JSON.stringify({err:'sin llamada'});
      const filled = await wait(() => {
        const p = __fm.store.call && __fm.store.call.peer;
        return p && p.avatar_url && p.banner_url ? p : null;
      }, 10000);
      await sleep(600);
      const out = {filled: !!filled,
        avatar: !!document.querySelector('.call-tile.peer .call-avatar img'),
        name: (document.querySelector('.call-tile-name')||{}).textContent || '',
        pos: filled ? filled.banner_position : null};
      const min = document.querySelector('.call-min'); if (min) min.click();
      await sleep(300);
      const fab = await wait(() => document.querySelector('.call-fab'), 5000);
      if (!fab) return JSON.stringify(Object.assign(out,{fab:false}));
      const r = fab.getBoundingClientRect();
      out.initial = {left:Math.round(r.left), top:Math.round(r.top),
        bottom:Math.round(r.bottom), ih:innerHeight,
        bottomCss:getComputedStyle(fab).bottom};
      const x0 = r.left + 31, y0 = r.top + 31;
      const ev = (type, x, y) => new PointerEvent(type, {bubbles:true,
        clientX:x, clientY:y, button:0, pointerId:7, isPrimary:true,
        pointerType:'touch'});
      fab.dispatchEvent(ev('pointerdown', x0, y0));
      window.dispatchEvent(ev('pointermove', 130, 130));
      window.dispatchEvent(ev('pointerup', 130, 130));
      await sleep(250);
      const r2 = fab.getBoundingClientRect();
      out.moved = {left:Math.round(r2.left), top:Math.round(r2.top),
        styleLeft:fab.style.left, styleTop:fab.style.top};
      fab.click();
      await sleep(180);
      const panel = document.querySelector('.call-panel');
      out.stillMin = !!document.querySelector('.callbox.minimized') &&
        !!panel && getComputedStyle(panel).display === 'none';
      await sleep(450);
      fab.click();
      await sleep(300);
      const panel2 = document.querySelector('.call-panel');
      out.restored = !!document.querySelector('.callbox:not(.minimized)') &&
        !!panel2 && getComputedStyle(panel2).display !== 'none';
      __fm.store.call = null;
      return JSON.stringify(out);
    })()""".replace("{CID}", str(cid)).replace("{BID}", str(B["user"]["id"])) \
        .replace("{BU}", BU)
    ok, res, log = shot(a.base + "/?v=w61-call", SHOTS / "w61-9-llamada.png",
                        js=js_call, wait=500, width=390, height=844,
                        viewport=True)
    d = jparse(res)
    step("llamada: el peer se completa con avatar, portada y posición",
         ok and d.get("filled") and d.get("avatar") and
         d.get("pos") == 70 and d.get("name") == "Beto W61", d or log[-400:])
    step("llamada móvil: el globo nace sobre la barra inferior",
         (d.get("initial") or {}).get("bottom", 9999) <=
         (d.get("initial") or {}).get("ih", 844) - 34, d)
    step("llamada: el globo se arrastra y no restaura al soltar",
         (d.get("moved") or {}).get("left", 9999) <
         (d.get("initial") or {}).get("left", 0) and
         (d.get("moved") or {}).get("top", 9999) <
         (d.get("initial") or {}).get("top", 0) and
         bool((d.get("moved") or {}).get("styleLeft")) and
         bool((d.get("moved") or {}).get("styleTop")) and
         d.get("stillMin"), d)
    step("llamada: un clic posterior restaura la llamada",
         d.get("restored"), d)

    # ---------------- señalización WS con perfil fresco ----------------
    st, r = ct.http("PUT", a.base + "/api/auth/profile",
                    {"display_name": "Ana W61 fresca", "banner_position": 65},
                    token=A["access"])
    if st == 200:
        A["user"] = r["user"]
    try:
        offer = ws_call_profile(a.base, A["access"], B["access"], cid)
        fr = (offer or {}).get("from") or {}
        step("WS: la oferta de llamada lleva avatar, portada y bio frescos",
             bool(offer) and fr.get("display_name") == "Ana W61 fresca" and
             fr.get("avatar_url") and fr.get("banner_url") and
             fr.get("banner_position") == 65 and len(fr.get("bio") or "") == 300,
             fr)
        step("WS: el perfil de llamada no filtra email",
             bool(offer) and "email" not in fr and "email_verified" not in fr,
             fr)
    except Exception as e:
        step("WS: la oferta de llamada lleva avatar, portada y bio frescos",
             False, repr(e))

    print(f"W61: {_pass[0]} bien, {_fail[0]} mal")
    return 0 if _fail[0] == 0 else 1


if __name__ == "__main__":
    code = 1
    try:
        code = main()
    finally:
        ok = ct.cleanup_db()
        print("· datos de prueba eliminados de la DB local" if ok else "· WARN limpieza")
    raise SystemExit(code)
