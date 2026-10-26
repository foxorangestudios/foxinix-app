#!/usr/bin/env python3
"""E2E W62/W64: sala de grupo drop-in en malla (3 participantes).

Cubre que la sala se pueda abrir sin nadie más conectado, que no suene
ninguna llamada, que quien llega después vea el botón verde con el aforo,
que pueda entrar y salir cuando quiera, y que la sala sobreviva a la
marcha de quien la abrió. También revisa el menú móvil "Entrar en la
llamada - [persona] N", la ventana arrastrable/acotada, pantalla completa,
compartir pantalla 480p/20 fps, menú por participante y limpieza de pistas.

También cubre W63: tonos de mensaje reales, previsualización al elegir en
Ajustes y enlace externo de tonos.

Uso: server/.venv/bin/python tests/w62_test.py [--base http://127.0.0.1:8899]

Requiere Firefox, `websockets` (venv del server) y el servidor local.
"""
import argparse
import asyncio
import base64
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

import websockets

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
import chat_ui_test as ct  # noqa: E402

SHOTS = Path("/tmp/opencode")
READY_JS = (
    "document.readyState === 'complete' && window.__fm && "
    "!document.querySelector('.boot') && "
    "document.querySelector('#app') && "
    "!!document.querySelector('#app').firstElementChild"
)
OK = [0]
FAIL = [0]


def step(name, ok, detail=""):
    if ok:
        OK[0] += 1
        print(f"  ✓ {name}")
    else:
        FAIL[0] += 1
        print(f"  ✗ {name}: {str(detail)[:600]}")


def jparse(res):
    try:
        return json.loads(res) if isinstance(res, str) and res.startswith("{") else {}
    except Exception:
        return {}


def sess_js(user):
    sess = json.dumps({
        "access": user["access"], "refresh": user["refresh"],
        "user": user["user"], "pendingEmail": "",
    })
    return sess.replace("\\", "\\\\").replace("'", "\\'")


class BiDi:
    def __init__(self, ws, name):
        self.ws = ws
        self.name = name
        self.mid = 0
        self.logs = []

    def _note(self, msg):
        if msg.get("method") != "log.entryAdded":
            return
        p = msg.get("params", {}) or {}
        e = p.get("entry", p)
        lvl = e.get("level") or e.get("method") or ""
        if lvl not in ("error", "warning", "warn"):
            return
        text = e.get("text")
        if not text:
            text = " ".join(str((a or {}).get("value", a))
                            for a in (e.get("args") or []))
        self.logs.append(f"[{lvl}] {text}")

    async def send(self, method, params=None, timeout=45):
        self.mid += 1
        wid = self.mid
        await self.ws.send(json.dumps({
            "id": wid, "method": method, "params": params or {},
        }))
        deadline = time.time() + timeout
        while True:
            left = deadline - time.time()
            if left <= 0:
                raise RuntimeError(f"{self.name}: timeout en {method}")
            raw = await asyncio.wait_for(self.ws.recv(), left)
            msg = json.loads(raw)
            if msg.get("id") == wid:
                if "error" in msg:
                    raise RuntimeError(
                        f"{self.name}: {method}: {json.dumps(msg['error'])[:400]}")
                return msg.get("result", {})
            self._note(msg)

    async def evaluate(self, expr, await_promise=True, timeout=45):
        r = await self.send("script.evaluate", {
            "expression": expr,
            "target": {"context": self.ctx},
            "awaitPromise": await_promise,
            "resultOwnership": "none",
        }, timeout=timeout)
        if r.get("type") == "exception":
            d = r.get("exceptionDetails") or {}
            raise RuntimeError(f"{self.name}: JS: {d.get('text') or d}")
        res = r.get("result", {})
        if "value" in res:
            return res["value"]
        return res.get("description")

    async def wait_js(self, expr, timeout=30, interval=0.2):
        deadline = time.time() + timeout
        last = None
        while time.time() < deadline:
            try:
                v = await self.evaluate(expr)
                last = v
                if v is True:
                    return True
            except Exception as e:
                last = str(e)
            await asyncio.sleep(interval)
        raise RuntimeError(f"{self.name}: timeout esperando {expr} ({last})")

    async def navigate(self, url):
        await self.send("browsingContext.navigate", {
            "context": self.ctx, "url": url, "wait": "complete",
        })

    async def screenshot(self, path):
        shot = await self.send("browsingContext.captureScreenshot", {
            "context": self.ctx, "format": {"type": "image/png"},
        })
        Path(path).write_bytes(base64.b64decode(shot["data"]))

    async def close(self):
        try:
            await asyncio.wait_for(self.send("browser.close", timeout=5), 7)
        except Exception:
            pass
        try:
            await self.ws.close()
            await self.ws.wait_closed()
        except Exception:
            pass


class Browser:
    def __init__(self, key, port, width=1280, height=860):
        self.key = key
        self.port = port
        self.width = width
        self.height = height
        self.profile = f"/tmp/opencode/w62-ff-{key}"
        self.proc = None
        self.ws = None
        self.bidi = None
        self.ctx = None

    async def start(self):
        shutil.rmtree(self.profile, ignore_errors=True)
        os.makedirs(self.profile, exist_ok=True)
        with open(os.path.join(self.profile, "user.js"), "w") as f:
            f.write(
                'user_pref("media.navigator.streams.fake", true);\n'
                'user_pref("media.navigator.permission.disabled", true);\n'
                'user_pref("media.autoplay.default", 0);\n'
                'user_pref("media.autoplay.blocking_policy", 0);\n'
                'user_pref("dom.webrtc.enabled", true);\n'
            )
        self.proc = subprocess.Popen([
            "firefox", "--headless", "--profile", self.profile, "-no-remote",
            f"--remote-debugging-port={self.port}",
            f"--window-size={self.width},{self.height}", "about:blank",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                s = socket.create_connection(("127.0.0.1", self.port), 1)
                s.close()
                break
            except OSError:
                await asyncio.sleep(0.2)
        else:
            raise RuntimeError(f"{self.key}: Firefox no abrió el puerto {self.port}")
        self.ws = await websockets.connect(
            f"ws://127.0.0.1:{self.port}/session",
            max_size=128 * 1024 * 1024, open_timeout=12)
        self.bidi = BiDi(self.ws, self.key)
        await self.bidi.send("session.new", {"capabilities": {}})
        try:
            await self.bidi.send("session.subscribe",
                                 {"events": ["log.entryAdded"]})
        except RuntimeError:
            pass
        tree = await self.bidi.send("browsingContext.getTree", {"maxDepth": 0})
        contexts = tree.get("contexts") or []
        if contexts:
            self.ctx = contexts[0]["context"]
        else:
            created = await self.bidi.send("browsingContext.create", {"type": "tab"})
            self.ctx = created["context"]
        try:
            await self.bidi.send("browsingContext.setViewport", {
                "context": self.ctx,
                "viewport": {"width": self.width, "height": self.height},
                "devicePixelRatio": 1,
            })
        except RuntimeError:
            pass
        self.bidi.ctx = self.ctx

    async def eval(self, expr, timeout=45):
        return await self.bidi.evaluate(expr, True, timeout)

    async def wait_js(self, expr, timeout=30):
        return await self.bidi.wait_js(expr, timeout)

    async def screenshot(self, path):
        return await self.bidi.screenshot(path)

    async def viewport(self, width, height):
        await self.bidi.send("browsingContext.setViewport", {
            "context": self.ctx,
            "viewport": {"width": width, "height": height},
            "devicePixelRatio": 1,
        })

    async def bootstrap(self, base, user):
        await self.bidi.navigate(base + "/")
        js = """(async()=>{
          try{const rs=await navigator.serviceWorker.getRegistrations();
            for(const r of rs) await r.unregister();}catch(e){}
          try{const ks=await caches.keys();
            for(const k of ks) await caches.delete(k);}catch(e){}
          localStorage.clear();
          localStorage.setItem('fm.session', 'SESSION');
          return 'ok';
        })()""".replace("SESSION", sess_js(user))
        out = await self.bidi.evaluate(js, True, 20)
        if out != "ok":
            raise RuntimeError(f"{self.key}: no se pudo inyectar sesión: {out}")
        await self.bidi.navigate(base + "/")
        await self.bidi.wait_js(READY_JS, 35)
        await self.bidi.wait_js("window.__fm.store.ws === 'on'", 25)

    async def close(self):
        if self.bidi:
            await self.bidi.close()
        if self.proc:
            try:
                self.proc.wait(timeout=8)
            except Exception:
                try:
                    self.proc.terminate()
                    self.proc.wait(timeout=5)
                except Exception:
                    self.proc.kill()


OPEN_CHAT = """(async()=>{
  const sleep=ms=>new Promise(r=>setTimeout(r,ms));
  const wait=async(fn,ms=15000)=>{const t=Date.now();
    while(Date.now()-t<ms){const v=fn();if(v)return v;await sleep(80);}return null;};
  await wait(()=>window.__fm && !__fm.store.booting, 20000);
  const item=await wait(()=>document.querySelector('.chat-item[data-chat-id="CID"]'),15000);
  if(!item)return JSON.stringify({err:'sin chat'});
  item.click();
  await wait(()=>__fm.store.activeChatId===CID,10000);
  await sleep(250);
  return JSON.stringify({ok:true,cid:__fm.store.activeChatId});
})()"""


def open_chat_js(cid):
    return OPEN_CHAT.replace("CID", str(cid))


ARM_AUDIO = """(()=>{
  window.__audioSrcs=[]; window.__audioPaused=0;
  window.Audio=function(src){
    this.src=String(src||''); this.loop=false; this.volume=1;
    window.__audioSrcs.push(this.src);
    this.play=function(){return Promise.resolve();};
    this.pause=function(){window.__audioPaused++;};
    this.addEventListener=function(){};
  };
  return 'audio armado';
})()"""


START_CALL = """(async()=>{
  const sleep=ms=>new Promise(r=>setTimeout(r,ms));
  const wait=async(fn,ms=15000)=>{const t=Date.now();
    while(Date.now()-t<ms){const v=fn();if(v)return v;await sleep(100);}return null;};
  await wait(()=>window.__fm && !__fm.store.booting, 20000);
  await wait(()=>__fm.store.ws==='on',15000);
  if(__fm.store.activeChatId!==CID){
    const item=await wait(()=>document.querySelector('.chat-item[data-chat-id="CID"]'),12000);
    if(!item)return JSON.stringify({err:'sin chat',cid:CID,
      active:__fm.store.activeChatId,
      chats:(__fm.store.chats||[]).map(c=>c.id),
      items:document.querySelectorAll('.chat-item').length,
      route:__fm.store.route});
    item.click();
    await wait(()=>__fm.store.activeChatId===CID,10000);
  }
  await sleep(250);
  const md=navigator.mediaDevices;
  window.__gum=[];
  const orig=md.getUserMedia.bind(md);
  md.getUserMedia=function(c){
    window.__gum.push(JSON.parse(JSON.stringify(c)));
    return orig(c);
  };
  window.__gdm=[];
  md.getDisplayMedia=async function(c){
    window.__gdm.push(JSON.parse(JSON.stringify(c)));
    const cv=document.createElement('canvas'); cv.width=854; cv.height=480;
    const g=cv.getContext('2d');
    if(window.__gdmTimer)clearInterval(window.__gdmTimer);
    window.__gdmTimer=setInterval(()=>{
      g.fillStyle='rgb('+(Date.now()%255)+',80,130)';
      g.fillRect(0,0,854,480);
      g.fillStyle='#fff'; g.font='40px sans-serif';
      g.fillText('Foxinix screen', 40, 240);
    }, 50);
    const st=cv.captureStream(20);
    window.__gdmStream=st;
    return st;
  };
  // W62: registrar las PeerConnection para poder comprobar que la pista
  // de pantalla reemplaza a la cámara en TODOS los pares de la malla.
  window.__pcs=[];
  if(!window.__pcWrapped){
    const OPC=window.RTCPeerConnection;
    if(OPC){
      window.RTCPeerConnection=function(){
        const p=new OPC(...arguments);
        window.__pcs.push(p);
        return p;
      };
      window.RTCPeerConnection.prototype=OPC.prototype;
      window.__pcWrapped=true;
    }
  }
  const btn=await wait(()=>{
    const bs=document.querySelectorAll('.chat-head .call-action');
    return bs && bs.length>=2 ? bs[1] : null;
  },10000);
  if(!btn)return JSON.stringify({err:'sin boton de llamada',
    active:__fm.store.activeChatId,call:!!__fm.store.call});
  btn.click();
  await wait(()=>__fm.store.call,10000);
  const c=__fm.store.call;
  return JSON.stringify({state:c&&c.state,group:!!(c&&c.group),
    gum:window.__gum,gdm:window.__gdm,chatName:c&&c.chatName});
})()"""


PRESENCE = """(async()=>{
  const sleep=ms=>new Promise(r=>setTimeout(r,ms));
  const wait=async(fn,ms=20000)=>{const t=Date.now();
    while(Date.now()-t<ms){const v=fn();if(v)return v;await sleep(100);}return null;};
  await wait(()=>window.__fm && __fm.store.ws==='on', 20000);
  const p=await wait(()=>{
    const x=__fm.store.groupCalls && __fm.store.groupCalls[CID];
    return x && x.count ? x : null;
  },20000);
  if(!p)return JSON.stringify({err:'sin presencia',
    calls:__fm.store.groupCalls||{}});
  const btn=document.querySelector('.chat-head .call-action.call-live');
  const li=document.querySelector('.chat-item[data-chat-id="CID"] .ci-call-live');
  return JSON.stringify({
    count:p.count,callId:p.callId,video:!!p.video,
    button:!!btn,
    btnCount:btn&&btn.querySelector('.call-count')
      ? btn.querySelector('.call-count').textContent.trim() : '',
    classLive:!!(btn&&btn.classList.contains('call-live')),
    list:!!li,
    listCount:li&&li.querySelector('b')?li.querySelector('b').textContent.trim():'',
    box:!!document.querySelector('.callbox'),
  });
})()"""


JOIN_CALL = """(async()=>{
  const sleep=ms=>new Promise(r=>setTimeout(r,ms));
  const wait=async(fn,ms=15000)=>{const t=Date.now();
    while(Date.now()-t<ms){const v=fn();if(v)return v;await sleep(100);}return null;};
  await wait(()=>window.__fm && __fm.store.ws==='on', 20000);
  const md=navigator.mediaDevices;
  window.__gum=[];
  const orig=md.getUserMedia.bind(md);
  md.getUserMedia=function(c){
    window.__gum.push(JSON.parse(JSON.stringify(c)));
    return orig(c);
  };
  // W64: la entrada es el botón verde con aforo, no una aceptación.
  const btn=await wait(()=>document.querySelector('.chat-head .call-action.call-live'),25000);
  if(!btn)return JSON.stringify({err:'sin boton verde',
    call:__fm.store.call ? {state:__fm.store.call.state,group:__fm.store.call.group} : null,
    calls:__fm.store.groupCalls||{},ring:window.__audioSrcs||[]});
  const presence=__fm.store.groupCalls[CID]||{};
  const btnCount=btn.querySelector('.call-count')
    ? btn.querySelector('.call-count').textContent.trim() : '';
  const ring=window.__audioSrcs ? window.__audioSrcs.slice() : [];
  const incoming=!!document.querySelector('.call-accept');
  btn.click();
  await wait(()=>__fm.store.call && __fm.store.call.group &&
    __fm.store.call.state!=='incoming', 20000);
  const c=__fm.store.call;
  return JSON.stringify({state:c&&c.state,group:!!(c&&c.group),
    callId:c&&c.callId,presenceCount:presence.count,
    presenceCallId:presence.callId,callMatch:!!(c&&presence.callId&&c.callId===presence.callId),
    btnCount:btnCount,incoming:incoming,
    gum:window.__gum,ring:ring,paused:window.__audioPaused||0});
})()"""


REMAIN_CALL = """(async()=>{
  const sleep=ms=>new Promise(r=>setTimeout(r,ms));
  const wait=async(fn,ms=20000)=>{const t=Date.now();
    while(Date.now()-t<ms){const v=fn();if(v)return v;await sleep(100);}return null;};
  const ok=await wait(()=>{
    const c=__fm.store.call;
    return c && c.group && (c.peers||[]).length===1 &&
      (c.peers||[]).every(p=>p.connected);
  },25000);
  const c=__fm.store.call;
  const p=__fm.store.groupCalls && __fm.store.groupCalls[CID];
  return JSON.stringify({ok:!!ok,still:!!c,state:c&&c.state,
    peers:(c&&c.peers||[]).map(x=>({id:x.id,connected:!!x.connected})),
    count:p?p.count:0,box:!!document.querySelector('.callbox')});
})()"""


REMAIN_ALONE = """(async()=>{
  const sleep=ms=>new Promise(r=>setTimeout(r,ms));
  const wait=async(fn,ms=15000)=>{const t=Date.now();
    while(Date.now()-t<ms){const v=fn();if(v)return v;await sleep(100);}return null;};
  const ok=await wait(()=>{
    const c=__fm.store.call;
    return c && c.group && (c.peers||[]).length===0;
  },18000);
  await sleep(1300);
  const c=__fm.store.call;
  const p=__fm.store.groupCalls && __fm.store.groupCalls[CID];
  return JSON.stringify({ok:!!ok,still:!!c,state:c&&c.state,
    peers:(c&&c.peers||[]).length,count:p?p.count:0,
    box:!!document.querySelector('.callbox')});
})()"""


WAIT_GONE = """(async()=>{
  const sleep=ms=>new Promise(r=>setTimeout(r,ms));
  const wait=async(fn,ms=15000)=>{const t=Date.now();
    while(Date.now()-t<ms){const v=fn();if(v)return v;await sleep(100);}return null;};
  const gone=await wait(()=>!(__fm.store.groupCalls||{})[CID],15000);
  return JSON.stringify({gone:!!gone,
    button:!!document.querySelector('.chat-head .call-action.call-live'),
    count:((__fm.store.groupCalls||{})[CID]||{}).count||0});
})()"""


WAIT_COUNT = """(async()=>{
  const sleep=ms=>new Promise(r=>setTimeout(r,ms));
  const wait=async(fn,ms=15000)=>{const t=Date.now();
    while(Date.now()-t<ms){const v=fn();if(v)return v;await sleep(100);}return null;};
  const p=await wait(()=>{
    const x=__fm.store.groupCalls && __fm.store.groupCalls[CID];
    return x && x.count===N ? x : null;
  },15000);
  return JSON.stringify({ok:!!p,count:p?p.count:0,
    callId:p?p.callId:'',calls:__fm.store.groupCalls||{}});
})()"""


MOBILE_MENU = """(async()=>{
  const sleep=ms=>new Promise(r=>setTimeout(r,ms));
  const wait=async(fn,ms=15000)=>{const t=Date.now();
    while(Date.now()-t<ms){const v=fn();if(v)return v;await sleep(100);}return null;};
  const more=await wait(()=>document.querySelector('.chat-more'),10000);
  if(!more)return JSON.stringify({err:'sin menu movil',
    width:innerWidth,items:document.querySelectorAll('.chat-more').length});
  more.click();
  await sleep(250);
  const items=[...document.querySelectorAll('.ctx-menu .ctx-item')];
  const item=items.find(x=>x.textContent.indexOf('Entrar en la llamada')>=0);
  const pill=item?item.querySelector('.ctx-pill'):null;
  const use=pill?pill.querySelector('use'):null;
  const icon=use?(use.getAttribute('href')||use.getAttribute('xlink:href')||''):'';
  const count=pill&&pill.querySelector('b')
    ? pill.querySelector('b').textContent.trim() : '';
  return JSON.stringify({found:!!item,text:item?item.textContent.trim():'',
    pill:!!pill,icon:icon,count:count,
    phone:!!(item&&item.querySelector('.ctx-ic use[href="#i-phone"]')),
    sheet:!!document.querySelector('.ctx-menu.ctx-sheet'),
    items:items.map(x=>x.textContent.trim())});
})()"""


MESH_STATE = """(async()=>{
  const sleep=ms=>new Promise(r=>setTimeout(r,ms));
  const wait=async(fn,ms=40000)=>{const t=Date.now();
    while(Date.now()-t<ms){const v=fn();if(v)return v;await sleep(120);}return null;};
  const ok=await wait(()=>{
    const c=__fm.store.call;
    return c && c.group && c.state==='active' && (c.peers||[]).length>=2 &&
      (c.peers||[]).every(p=>p.connected);
  },40000);
  await wait(()=>{
    const vs=[...document.querySelectorAll('video[data-peer]')];
    return vs.length>=2 && vs.every(v=>v.srcObject &&
      v.srcObject.getVideoTracks().length>0 &&
      v.srcObject.getVideoTracks()[0].readyState==='live');
  },25000);
  const c=__fm.store.call;
  const pip=document.querySelector('.call-pip');
  const locals=[];
  if(pip&&pip.srcObject) locals.push(pip.srcObject);
  window.__preHangLocal=locals[0]||null;
  if(!window.__callLogTimer){
    window.__callLog=[];
    window.__callLogTimer=setInterval(()=>{
      const c=__fm.store.call;
      const sig=c?c.state+':'+((c.peers||[]).length)+':'+(c.screen?'S':'-'):
        'null';
      const last=window.__callLog[window.__callLog.length-1];
      if(!last || last.sig!==sig) window.__callLog.push({t:Date.now(),sig:sig,
        toasts:(__fm.store.toasts||[]).map(x=>x.msg)});
    },200);
  }
  const vids=[...document.querySelectorAll('video[data-peer]')];
  return JSON.stringify({
    ok:!!ok,state:c&&c.state,group:!!(c&&c.group),
    peers:(c&&c.peers||[]).map(p=>({id:p.id,name:p.display_name,
      connected:!!p.connected,video:!!p.video})),
    tiles:document.querySelectorAll('.group-tile').length,
    self:!!document.querySelector('.call-tile.self'),
    selfVideo:!!(pip&&pip.srcObject&&pip.srcObject.getVideoTracks().length),
    remoteVideos:vids.map(v=>({peer:v.getAttribute('data-peer'),
      tracks:v.srcObject?v.srcObject.getVideoTracks().length:0,
      state:v.srcObject&&v.srcObject.getVideoTracks()[0]
        ? v.srcObject.getVideoTracks()[0].readyState : ''})),
    toasts:(__fm.store.toasts||[]).map(x=>x.msg),
    ws:__fm.store.ws,
    active:__fm.store.activeChatId,
  });
})()"""


UI_A = """(async()=>{
  const sleep=ms=>new Promise(r=>setTimeout(r,ms));
  const wait=async(fn,ms=15000)=>{const t=Date.now();
    while(Date.now()-t<ms){const v=fn();if(v)return v;await sleep(100);}return null;};
  const out={};
  const box=document.querySelector('.callbox');
  if(!box)return JSON.stringify({err:'sin callbox',call:__fm.store.call,
    toasts:(__fm.store.toasts||[]).map(x=>x.msg)});
  out.tStart=Date.now();
  out.groupClass=!!document.querySelector('.call-participants.group');
  out.tiles=document.querySelectorAll('.group-tile').length;
  out.self=!!document.querySelector('.call-tile.self');
  const title=document.querySelector('.call-head b');
  out.title=title?title.textContent.trim():'';
  out.count=(document.querySelector('.call-count')||{}).textContent||'';
  // pantalla completa
  const fullBtn=document.querySelector('.call-full');
  if(fullBtn){
    fullBtn.click();
    await wait(()=>document.querySelector('.callbox.full'),4000);
    const r=box.getBoundingClientRect();
    out.full={on:box.classList.contains('full'),
      w:Math.round(r.width),h:Math.round(r.height),
      iw:innerWidth,ih:innerHeight};
    fullBtn.click();
    await wait(()=>!document.querySelector('.callbox.full'),4000);
    out.full.off=!box.classList.contains('full');
  }
  out.tFull=Date.now();
  // arrastre normal
  const head=document.querySelector('.call-head');
  const pe=(type,x,y)=>new PointerEvent(type,{bubbles:true,clientX:x,clientY:y,
    button:0,buttons:1,pointerId:17,isPrimary:true,pointerType:'mouse'});
  const b0=box.getBoundingClientRect();
  let x0=b0.left+70,y0=b0.top+20;
  head.dispatchEvent(pe('pointerdown',x0,y0));
  window.dispatchEvent(pe('pointermove',x0+150,y0+110));
  window.dispatchEvent(pe('pointerup',x0+150,y0+110));
  await sleep(260);
  const b1=box.getBoundingClientRect();
  out.drag={dx:Math.round(b1.left-b0.left),dy:Math.round(b1.top-b0.top),
    inView:b1.left>=0&&b1.top>=0&&b1.right<=innerWidth+1&&
      b1.bottom<=innerHeight+1};
  // acotado al viewport
  x0=b1.left+70; y0=b1.top+20;
  head.dispatchEvent(pe('pointerdown',x0,y0));
  window.dispatchEvent(pe('pointermove',x0+6000,y0+6000));
  window.dispatchEvent(pe('pointerup',x0+6000,y0+6000));
  await sleep(260);
  const b2=box.getBoundingClientRect();
  out.clamp={left:Math.round(b2.left),top:Math.round(b2.top),
    right:Math.round(b2.right),bottom:Math.round(b2.bottom),
    iw:innerWidth,ih:innerHeight,
    inView:b2.left>=0&&b2.top>=0&&b2.right<=innerWidth+1&&
      b2.bottom<=innerHeight+1};
  out.tDrag=Date.now();
  // menú por participante (clic derecho)
  const tile=document.querySelector('.group-tile');
  const tr=tile.getBoundingClientRect();
  tile.dispatchEvent(new MouseEvent('contextmenu',{bubbles:true,
    cancelable:true,clientX:tr.left+40,clientY:tr.top+40,button:2}));
  await sleep(220);
  const menu=document.querySelector('.call-menu');
  out.menu=!!menu;
  out.menuTexts=menu?[...menu.querySelectorAll('button')]
    .map(b=>b.textContent.trim()):[];
  const muteBtn=menu?[...menu.querySelectorAll('button')]
    .find(b=>b.textContent.indexOf('Silenciar para m')>=0):null;
  if(muteBtn){
    muteBtn.click(); await sleep(220);
    const vid=document.querySelector('video[data-peer]');
    out.peerMuted=!!(vid&&vid.muted);
  }
  out.tMenu=Date.now();
  // compartir pantalla
  const scr=document.querySelector('.call-screen');
  out.screenBtn=!!scr;
  if(scr){
    scr.click();
    await wait(()=>__fm.store.call && __fm.store.call.screen,15000);
  }
  out.screen=!!(__fm.store.call&&__fm.store.call.screen);
  out.tScreen=Date.now();
  out.gdm=(window.__gdm||[])[0]||null;
  if(window.__gdmStream){
    const tr=window.__gdmStream.getVideoTracks()[0];
    const s=tr?tr.getSettings():{};
    out.screenTrack={w:s.width,h:s.height,fps:s.frameRate,
      state:tr?tr.readyState:'',live:!!tr&&tr.enabled};
  }
  out.senders=[];
  (window.__pcs||[]).forEach(pc=>{
    try{pc.getSenders().forEach(sn=>{
      if(sn.track&&sn.track.kind==='video'){
        const s=sn.track.getSettings();
        out.senders.push({w:s.width,h:s.height,fps:s.frameRate,
          state:sn.track.readyState});
      }
    });}catch(e){}
  });
  const pip=document.querySelector('.call-pip');
  if(pip&&pip.srcObject&&pip.srcObject.getVideoTracks().length){
    const s=pip.srcObject.getVideoTracks()[0].getSettings();
    out.pip={w:s.width,h:s.height,fps:s.frameRate,
      live:pip.srcObject.getVideoTracks()[0].readyState};
  }
  return JSON.stringify(out);
})()"""


REMOTE_SCREEN = """(async()=>{
  const sleep=ms=>new Promise(r=>setTimeout(r,ms));
  await sleep(1200);
  const vids=[...document.querySelectorAll('video[data-peer]')];
  const c=__fm.store.call;
  return JSON.stringify({
    screen:!!(c&&c.screen),
    remoteVideo:!!(c&&c.remoteVideo),
    call:c?{state:c.state,group:!!c.group,peers:(c.peers||[]).map(p=>({
      id:p.id,connected:!!p.connected,video:!!p.video})),camOff:!!c.camOff,
      screen:!!c.screen}:null,
    box:!!document.querySelector('.callbox'),
    videoCount:vids.length,
    callLog:window.__callLog||[],
    tracks:vids.map(v=>{
      const tr=v.srcObject&&v.srcObject.getVideoTracks()[0];
      const s=tr?tr.getSettings():{};
      return {peer:v.getAttribute('data-peer'),w:s.width,h:s.height,
        fps:s.frameRate,state:tr?tr.readyState:'',
        stream:!!v.srcObject,all:v.srcObject?v.srcObject.getTracks().map(x=>x.kind+':'+x.readyState):[]};
    })
  });
})()"""


HANGUP = """(async()=>{
  const sleep=ms=>new Promise(r=>setTimeout(r,ms));
  const wait=async(fn,ms=20000)=>{const t=Date.now();
    while(Date.now()-t<ms){const v=fn();if(v)return v;await sleep(100);}return null;};
  const local=window.__preHangLocal;
  const hang=document.querySelector('.call-hang');
  if(!hang)return JSON.stringify({err:'sin boton colgar'});
  hang.click();
  const gone=await wait(()=>!__fm.store.call,15000);
  const tracks=local?local.getTracks().map(t=>t.readyState):[];
  return JSON.stringify({gone:!!gone,localTracks:tracks,
    box:!!document.querySelector('.callbox'),
    tiles:document.querySelectorAll('video[data-peer]').length});
})()"""


TONES = """(async()=>{
  const sleep=ms=>new Promise(r=>setTimeout(r,ms));
  const wait=async(fn,ms=15000)=>{const t=Date.now();
    while(Date.now()-t<ms){const v=fn();if(v)return v;await sleep(100);}return null;};
  const out={};
  window.__previewSrcs=[];
  const Old=window.Audio;
  window.Audio=function(src){
    this.src=String(src||''); this.loop=false; this.volume=1;
    window.__previewSrcs.push(this.src);
    this.play=function(){return Promise.resolve();};
    this.pause=function(){};
    this.addEventListener=function(){};
  };
  __fm.store.settingsOpen=true;
  /* W65: los tonos viven en su propia categoría (Notificaciones). */
  __fm.store.settingsTab='notificaciones';
  const sel=await wait(()=>document.querySelectorAll('.tone-select')[0],8000);
  if(!sel)return JSON.stringify({err:'sin selector de tonos'});
  out.options=[...sel.options].map(o=>o.value);
  const callSel=document.querySelectorAll('.tone-select')[1];
  out.callOptions=callSel?[...callSel.options].map(o=>o.value):[];
  sel.value='beep';
  sel.dispatchEvent(new Event('change',{bubbles:true}));
  await sleep(250);
  out.preview=window.__previewSrcs.slice();
  out.saved=localStorage.getItem('fm.p.messageTone');
  // enlace externo: en el APK debe salir al navegador del sistema
  window.__opened='';
  window.FoxinixAndroid={openUrl:function(u){window.__opened=u;}};
  const a=document.querySelector('.tone-note a[href="https://tonosdellamada.es"]');
  if(a){a.dispatchEvent(new MouseEvent('click',{bubbles:true,cancelable:true}));}
  await sleep(150);
  out.opened=window.__opened;
  __fm.store.settingsOpen=false;
  window.Audio=Old;
  // tono de mensaje real: el chat abierto no debe ser el de destino
  window.__msgSrcs=[];
  const Old2=window.Audio;
  window.Audio=function(src){
    this.src=String(src||''); this.loop=false; this.volume=1;
    window.__msgSrcs.push(this.src);
    this.play=function(){return Promise.resolve();};
    this.pause=function(){};
    this.addEventListener=function(){};
  };
  __fm.store.prefs.sound=true;
  __fm.store.prefs.messageTone='beep';
  __fm.store.activeChatId=null;
  out.msgReady=true;
  return JSON.stringify(out);
})()"""


CHECK_MSG_TONE = """(async()=>{
  const sleep=ms=>new Promise(r=>setTimeout(r,ms));
  const wait=async(fn,ms=15000)=>{const t=Date.now();
    while(Date.now()-t<ms){const v=fn();if(v)return v;await sleep(100);}return null;};
  const ok=await wait(()=>window.__msgSrcs && window.__msgSrcs.length,12000);
  return JSON.stringify({ok:!!ok,srcs:window.__msgSrcs||[]});
})()"""


async def run(a):
    tag = uuid.uuid4().hex[:6]
    base = a.base.rstrip("/")
    print(f"· W62 malla {tag}")
    A = ct.register(base, f"w62a{tag}@example.com", f"w62a{tag}")
    B = ct.register(base, f"w62b{tag}@example.com", f"w62b{tag}")
    C = ct.register(base, f"w62c{tag}@example.com", f"w62c{tag}")
    st, res = ct.http("POST", base + "/api/chats/group", {
        "title": f"Malla W62 {tag}",
        "members": [B["user"]["username"], C["user"]["username"]],
    }, token=A["access"])
    if st != 201:
        raise SystemExit(f"✗ no se pudo crear el grupo: {st} {res}")
    cid = res["chat"]["id"]
    print(f"  · grupo {cid}")

    browsers = {
        "A": Browser("A", 9521),
        "B": Browser("B", 9522),
        "C": Browser("C", 9523),
    }
    try:
        # W64: A abre la sala sin que B/C estén siquiera conectados.
        await browsers["A"].start()
        await browsers["A"].bootstrap(base, A)
        out = jparse(await browsers["A"].eval(open_chat_js(cid)))
        if not out.get("ok"):
            raise RuntimeError(f"A: no abrió el grupo: {out}")

        ga = jparse(await browsers["A"].eval(
            START_CALL.replace("CID", str(cid)), timeout=30))
        step("grupo: A abre la videollamada aunque no haya nadie conectado",
             ga.get("group") and ga.get("state") == "active" and
             ga.get("chatName"), ga)
        gcall = {}
        for call in ga.get("gum") or []:
            v = call.get("video")
            if isinstance(v, dict):
                gcall = v
                break
        step("grupo: la cámara pide 854×480 a 20 fps",
             gcall.get("width", {}).get("max") == 854 and
             gcall.get("height", {}).get("max") == 480 and
             gcall.get("frameRate", {}).get("max") == 20,
             ga.get("gum"))

        await asyncio.sleep(2)
        alone = jparse(await browsers["A"].eval(
            "JSON.stringify({call:(__fm.store.call||{}).state||'',"
            "startedAt:(__fm.store.call||{}).startedAt||0,"
            "count:((__fm.store.groupCalls||{})[CID]||{}).count||0})"
            .replace("CID", str(cid))))
        step("grupo: la sala espera sola, activa y sin timeout",
             alone.get("call") == "active" and alone.get("startedAt") and
             alone.get("count") == 1, alone)

        # Ahora entran B y C. Al conectar reciben la presencia existente.
        for key in ("B", "C"):
            await browsers[key].start()
        await asyncio.gather(*[
            browsers[key].bootstrap(base, u)
            for key, u in (("B", B), ("C", C))
        ])
        for key in ("B", "C"):
            out = jparse(await browsers[key].eval(open_chat_js(cid)))
            if not out.get("ok"):
                raise RuntimeError(f"{key}: no abrió el grupo: {out}")

        # B y C siguen con sus tonos armados para detectar cualquier
        # llamada entrante. La sala drop-in no debe hacer sonar nada.
        for key, tone in (("B", "iphone"), ("C", "skype")):
            await browsers[key].eval(f"localStorage.setItem('fm.p.callTone','{tone}');"
                                     f"__fm.store.prefs.callTone='{tone}';"
                                     "localStorage.setItem('fm.p.messageTone','beep');"
                                     "__fm.store.prefs.messageTone='beep';"
                                     "localStorage.setItem('fm.p.sound','1');"
                                     "__fm.store.prefs.sound=true;")
            await browsers[key].eval(ARM_AUDIO)

        pb, pc = await asyncio.gather(
            browsers["B"].eval(PRESENCE.replace("CID", str(cid)), timeout=30),
            browsers["C"].eval(PRESENCE.replace("CID", str(cid)), timeout=30),
        )
        pb, pc = jparse(pb), jparse(pc)
        step("grupo: B ve el botón verde con 1 persona y sin llamada entrante",
             pb.get("count") == 1 and pb.get("button") and
             pb.get("classLive") and pb.get("btnCount") == "1" and
             pb.get("list") and pb.get("listCount") == "1" and
             not pb.get("box"), pb)
        step("grupo: C ve el mismo botón verde con 1 persona",
             pc.get("count") == 1 and pc.get("button") and
             pc.get("classLive") and pc.get("btnCount") == "1" and
             pc.get("list") and pc.get("listCount") == "1" and
             not pc.get("box"), pc)

        # B entra desde el botón verde; no hay aceptación ni tono.
        gb = jparse(await browsers["B"].eval(JOIN_CALL.replace("CID", str(cid)), timeout=55))
        step("grupo: B entra a la llamada con el botón verde",
             gb.get("group") and gb.get("state") in ("connecting", "active") and
             gb.get("callMatch") and gb.get("presenceCount") == 1 and
             gb.get("btnCount") == "1", gb)
        step("grupo: entrar no dispara tono ni pantalla de llamada entrante",
             not gb.get("incoming") and not (gb.get("ring") or []) and
             (gb.get("paused") or 0) == 0, gb)

        a_after_b = jparse(await browsers["A"].eval(WAIT_COUNT.replace(
            "CID", str(cid)).replace("count===N", "count===2"), timeout=20))
        step("grupo: A ve el contador actualizado a 2 al entrar B",
             a_after_b.get("ok") and a_after_b.get("count") == 2, a_after_b)

        c2 = jparse(await browsers["C"].eval(WAIT_COUNT.replace(
            "CID", str(cid)).replace("count===N", "count===2"), timeout=20))
        step("grupo: C ve en vivo que ya hay 2 personas antes de entrar",
             c2.get("ok") and c2.get("count") == 2, c2)

        gc = jparse(await browsers["C"].eval(JOIN_CALL.replace("CID", str(cid)), timeout=55))
        step("grupo: C entra y la malla queda de 3",
             gc.get("group") and gc.get("state") in ("connecting", "active") and
             gc.get("callMatch") and gc.get("presenceCount") == 2 and
             gc.get("btnCount") == "2", gc)
        step("grupo: la entrada de C tampoco suena",
             not gc.get("incoming") and not (gc.get("ring") or []) and
             (gc.get("paused") or 0) == 0, gc)

        try:
            await browsers["A"].wait_js(
                "!!(__fm.store.call && __fm.store.call.state === 'active' && "
                "((__fm.store.call.peers||[]).length >= 2))", 30)
        except Exception as e:
            print(f"  · espera A: {e}")
        ga2 = jparse(await browsers["A"].eval(
            "JSON.stringify({state:(__fm.store.call||{}).state,"
            "peers:((__fm.store.call||{}).peers||[]).length,call:"
            "(__fm.store.call||{}).callId||''})"))
        step("grupo: A sigue activa y suma los dos pares",
             ga2.get("state") == "active" and (ga2.get("peers") or 0) >= 2, ga2)

        ma, mb, mc = await asyncio.gather(*[
            br.eval(MESH_STATE, timeout=70) for br in browsers.values()
        ])
        ma, mb, mc = jparse(ma), jparse(mb), jparse(mc)
        for key, m in (("A", ma), ("B", mb), ("C", mc)):
            if not m.get("ok"):
                print(f"  · {key} estado: {json.dumps(m, ensure_ascii=False)[:800]}")
                logs = browsers[key].bidi.logs[-8:]
                if logs:
                    print(f"  · {key} consola: {logs}")
            step(f"malla: {key} ve 2 pares conectados y 2 vídeos remotos",
                 m.get("ok") and m.get("state") == "active" and
                 len(m.get("peers") or []) == 2 and
                 all(p.get("connected") for p in m.get("peers") or []) and
                 m.get("tiles") == 2 and m.get("self") and
                 m.get("selfVideo") and
                 len(m.get("remoteVideos") or []) == 2 and
                 all(v.get("tracks") for v in m.get("remoteVideos") or []),
                 m)

        ui = jparse(await browsers["A"].eval(UI_A, timeout=50))
        step("grupo: mosaico 2×2 con tú y menú por participante",
             ui.get("groupClass") and ui.get("tiles") == 2 and ui.get("self") and
             ui.get("menu") and
             any("Ver perfil" in x for x in ui.get("menuTexts") or []) and
             any("Silenciar para m" in x for x in ui.get("menuTexts") or []),
             ui)
        step("grupo: silenciar a un participante silencia solo su vídeo",
             ui.get("peerMuted") is True, ui)
        step("grupo: la ventana se arrastra y queda acotada al viewport",
             (ui.get("drag") or {}).get("inView") and
             ((ui.get("drag") or {}).get("dx") or 0) != 0 and
             ((ui.get("drag") or {}).get("dy") or 0) != 0 and
             (ui.get("clamp") or {}).get("inView"),
             {"drag": ui.get("drag"), "clamp": ui.get("clamp")})
        step("grupo: pantalla completa ocupa todo y se puede salir",
             (ui.get("full") or {}).get("on") and
             (ui.get("full") or {}).get("off") and
             (ui.get("full") or {}).get("w") >=
             (ui.get("full") or {}).get("iw", 99999) - 1 and
             (ui.get("full") or {}).get("h") >=
             (ui.get("full") or {}).get("ih", 99999) - 1,
             ui.get("full"))
        step("grupo: compartir pantalla pide 854×480/20 y activa el estado",
             ui.get("screenBtn") and ui.get("screen") and
             (((ui.get("gdm") or {}).get("video") or {}).get("width") or {}
              ).get("max") == 854 and
             (((ui.get("gdm") or {}).get("video") or {}).get("frameRate") or {}
              ).get("max") == 20 and
             (ui.get("screenTrack") or {}).get("w") == 854 and
             (ui.get("screenTrack") or {}).get("h") == 480 and
             (ui.get("screenTrack") or {}).get("state") == "live" and
             any(s.get("w") == 854 and s.get("state") == "live"
                 for s in ui.get("senders") or []),
             {"gdm": ui.get("gdm"), "screenTrack": ui.get("screenTrack"),
              "senders": ui.get("senders")})
        await browsers["A"].screenshot(SHOTS / "w62-1-malla.png")

        ra, rb, rc = await asyncio.gather(*[
            br.eval(REMOTE_SCREEN, timeout=30) for br in browsers.values()
        ])
        ra, rb, rc = jparse(ra), jparse(rb), jparse(rc)
        step("grupo: A comparte pantalla y el vídeo reemplazado llega a B y C",
             ra.get("screen") and rb.get("remoteVideo") and rc.get("remoteVideo") and
             len(rb.get("tracks") or []) == 2 and
             len(rc.get("tracks") or []) == 2 and
             all(v.get("state") == "live" and "video:live" in (v.get("all") or [])
                 for v in rb.get("tracks") or []) and
             all(v.get("state") == "live" and "video:live" in (v.get("all") or [])
                 for v in rc.get("tracks") or []),
             {"A": ra, "B": rb, "C": rc})
        await browsers["A"].screenshot(SHOTS / "w62-2-pantalla.png")
        await browsers["B"].screenshot(SHOTS / "w62-3-B-pantalla.png")
        await browsers["C"].screenshot(SHOTS / "w62-3-C-pantalla.png")

        # W64: A (quien abrió la sala) se va; la llamada sigue para B/C.
        ha = jparse(await browsers["A"].eval(HANGUP, timeout=35))
        step("grupo: A sale y libera sus pistas",
             ha.get("gone") and not ha.get("box") and
             all(s == "ended" for s in ha.get("localTracks") or []), ha)

        a_wait = jparse(await browsers["A"].eval(WAIT_COUNT.replace(
            "CID", str(cid)).replace("count===N", "count===2"), timeout=20))
        pa = jparse(await browsers["A"].eval(
            PRESENCE.replace("CID", str(cid)), timeout=25))
        step("grupo: A ve la sala de B/C con botón verde y 2 personas",
             pa.get("count") == 2 and pa.get("button") and
             pa.get("classLive") and pa.get("btnCount") == "2" and
             pa.get("list") and pa.get("listCount") == "2" and
             not pa.get("box"), pa)

        for key, br in (("B", browsers["B"]), ("C", browsers["C"])):
            out = jparse(await br.eval(REMAIN_CALL.replace("CID", str(cid)),
                                       timeout=35))
            step(f"grupo: {key} sigue en la llamada tras irse el anfitrión",
                 out.get("ok") and out.get("still") and
                 out.get("state") == "active" and out.get("count") == 2 and
                 len(out.get("peers") or []) == 1 and
                 all(p.get("connected") for p in out.get("peers") or []),
                 out)

        # En el teléfono, el menú ⋮ muestra "Entrar en la llamada - 👤 N".
        await browsers["A"].viewport(390, 844)
        mm = jparse(await browsers["A"].eval(
            MOBILE_MENU.replace("CID", str(cid)), timeout=20))
        step("grupo móvil: el menú ofrece Entrar en la llamada con persona y aforo",
             mm.get("found") and mm.get("sheet") and mm.get("pill") and
             mm.get("icon") == "#i-user" and mm.get("count") == "2" and
             mm.get("phone") and
             "Entrar en la llamada" in (mm.get("text") or ""), mm)
        await browsers["A"].viewport(1280, 860)
        await browsers["A"].eval("__fm.store.ctx=null;'ok'")

        # B se va: C queda solo y la sala sigue esperando sin timeout.
        hb = jparse(await browsers["B"].eval(HANGUP, timeout=35))
        step("grupo: B sale y libera sus pistas",
             hb.get("gone") and not hb.get("box") and
             all(s == "ended" for s in hb.get("localTracks") or []), hb)
        cb = jparse(await browsers["C"].eval(
            REMAIN_ALONE.replace("CID", str(cid)), timeout=30))
        step("grupo: C sigue sola en la sala sin que se corte",
             cb.get("ok") and cb.get("still") and cb.get("state") == "active" and
             cb.get("peers") == 0 and cb.get("count") == 1 and cb.get("box"), cb)
        a1 = jparse(await browsers["A"].eval(WAIT_COUNT.replace(
            "CID", str(cid)).replace("count===N", "count===1"), timeout=20))
        step("grupo: el contador baja a 1 para quien está fuera",
             a1.get("ok") and a1.get("count") == 1, a1)

        # C se va: última persona → la sala desaparece y el botón verde no.
        hc = jparse(await browsers["C"].eval(HANGUP, timeout=35))
        step("grupo: C sale y libera sus pistas",
             hc.get("gone") and not hc.get("box") and
             all(s == "ended" for s in hc.get("localTracks") or []), hc)
        gone = jparse(await browsers["A"].eval(
            WAIT_GONE.replace("CID", str(cid)), timeout=20))
        step("grupo: al irse la última persona la sala termina",
             gone.get("gone") and not gone.get("button") and
             gone.get("count") == 0, gone)

        # W63: tonos en Ajustes + enlace externo + tono de mensaje real.
        tones = jparse(await browsers["A"].eval(TONES, timeout=35))
        step("tonos: los selectores traen los 5 mensajes y 11 llamadas",
             len(tones.get("options") or []) == 6 and
             len(tones.get("callOptions") or []) == 12,
             tones)
        step("tonos: elegir previsualiza el archivo y guarda la preferencia",
             any("tonos/Mensaje/Beep.mp3" in s
                 for s in tones.get("preview") or []) and
             tones.get("saved") == "beep", tones)
        step("tonos: el enlace de tonos abre el navegador en el APK",
             tones.get("opened") == "https://tonosdellamada.es", tones)

        # B manda un mensaje al grupo sin que A lo tenga abierto.
        msg = ct.send(base, B["access"], cid, {"kind": "text",
                                               "body": "tono w62"})
        check = jparse(await browsers["A"].eval(CHECK_MSG_TONE, timeout=20))
        step("tonos: el mensaje entrante usa el tono de mensaje elegido",
             check.get("ok") and
             any("tonos/Mensaje/Beep.mp3" in s for s in check.get("srcs") or []),
             {"msg": (msg or {}).get("id"), "tones": check})

    finally:
        for br in browsers.values():
            try:
                await br.close()
            except Exception:
                pass
        for name in ("A", "B", "C"):
            shutil.rmtree(f"/tmp/opencode/w62-ff-{name}", ignore_errors=True)
        ct.cleanup_db()

    print(f"W62: {OK[0]} bien, {FAIL[0]} mal")
    return 1 if FAIL[0] else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8899")
    args = ap.parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
