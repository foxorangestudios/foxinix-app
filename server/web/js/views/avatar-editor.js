/* Foxinix — W27: editor de foto de perfil. Antes de aplicar la foto se
   puede ENCUADRAR (arrastrando) y ROTAR en pasos de 90°. La vista previa
   y la salida final se pintan con la MISMA función de canvas, así que lo
   que ves es exactamente lo que se sube. */

const SQ = 220;      // lado lógico de la vista previa
const OUT = 512;     // lado de la imagen que se sube

/* Pinta la foto en un cuadro de `side` px con el estado dado.
   st: {rot: 0..3, zoom: 1..3, tx, ty} — tx/ty en fracciones del lado. */
function drawInto(ctx, side, img, st) {
  const base = Math.max(side / img.naturalWidth, side / img.naturalHeight) * st.zoom;
  ctx.save();
  ctx.clearRect(0, 0, side, side);
  ctx.translate(side / 2 + st.tx * side, side / 2 + st.ty * side);
  ctx.rotate(st.rot * Math.PI / 2);
  ctx.scale(base, base);
  ctx.drawImage(img, -img.naturalWidth / 2, -img.naturalHeight / 2,
    img.naturalWidth, img.naturalHeight);
  ctx.restore();
}

/* El encuadre nunca puede dejar huecos: limita tx/ty a que la foto (ya
   rotada) siga cubriendo el cuadro. */
function clampPan(st, img, side) {
  const base = Math.max(side / img.naturalWidth, side / img.naturalHeight) * st.zoom;
  const swap = st.rot % 2 === 1;
  const dw = (swap ? img.naturalHeight : img.naturalWidth) * base;
  const dh = (swap ? img.naturalWidth : img.naturalHeight) * base;
  const mx = Math.max(0, (dw - side) / (2 * side));
  const my = Math.max(0, (dh - side) / (2 * side));
  if (st.tx < -mx) st.tx = -mx;
  if (st.tx > mx) st.tx = mx;
  if (st.ty < -my) st.ty = -my;
  if (st.ty > my) st.ty = my;
}

export const AvatarEditor = {
  name: 'AvatarEditor',
  props: {
    src: { type: String, required: true },
    /* W27b: encuadre previamente aplicado (rot/zoom/tx/ty). El padre lo
       pasa al REEDITAR para restaurar la posición guardada en sesión. */
    initial: { type: Object, default: null },
  },
  setup: function (props, ctx) {
    const cv = Vue.ref(null);
    const rot = Vue.ref(0);
    const zoom = Vue.ref(1);
    const tx = Vue.ref(0);
    const ty = Vue.ref(0);
    const ready = Vue.ref(false);
    let img = null;

    const state = function () {
      return { rot: rot.value, zoom: zoom.value, tx: tx.value, ty: ty.value };
    };

    const draw = function () {
      const el = cv.value;
      if (!el || !img) return;
      const st = state();
      clampPan(st, img, SQ);
      if (st.tx !== tx.value) tx.value = st.tx;
      if (st.ty !== ty.value) ty.value = st.ty;
      drawInto(el.getContext('2d'), SQ, img, state());
    };

    const load = function (src) {
      ready.value = false;
      rot.value = 0;
      zoom.value = 1;
      tx.value = 0;
      ty.value = 0;
      const im = new Image();
      im.onload = function () {
        img = im;
        /* restaura el encuadre guardado (la foto puede haber cambiado:
           clampPan evita huecos) */
        const ini = props.initial;
        if (ini) {
          const r = Math.round(ini.rot || 0) % 4;
          rot.value = r < 0 ? r + 4 : r;
          const z = Number(ini.zoom);
          zoom.value = z >= 1 && z <= 3 ? z : 1;
          tx.value = Number(ini.tx) || 0;
          ty.value = Number(ini.ty) || 0;
        }
        ready.value = true;
        draw();
      };
      im.onerror = function () {
        img = null;
        ready.value = false;
      };
      im.src = src;
    };
    load(props.src);
    Vue.watch(function () { return props.src; }, function (v) {
      if (v) load(v);
    });

    /* ---- encuadre con el ratón/dedo ---- */
    let dragging = false;
    let lx = 0;
    let ly = 0;
    const down = function (e) {
      if (!img) return;
      dragging = true;
      lx = e.clientX;
      ly = e.clientY;
      if (e.target.setPointerCapture) {
        try { e.target.setPointerCapture(e.pointerId); } catch (err) { /* nada */ }
      }
    };
    const move = function (e) {
      if (!dragging) return;
      const el = cv.value;
      if (!el) return;
      const r = el.getBoundingClientRect();
      const k = SQ / (r.width || SQ);   // si CSS encoge el canvas, escalar
      tx.value += (e.clientX - lx) * k / SQ;
      ty.value += (e.clientY - ly) * k / SQ;
      lx = e.clientX;
      ly = e.clientY;
      draw();
      e.preventDefault();
    };
    const up = function () {
      dragging = false;
    };

    const rotate = function () {
      rot.value = (rot.value + 1) % 4;
      draw();
    };
    const reset = function () {
      rot.value = 0;
      zoom.value = 1;
      tx.value = 0;
      ty.value = 0;
      draw();
    };

    /* Compón la salida en 512 px y devuélvela como Blob (PNG: FF78 no
       codifica WebP; el server la recodifica a WebP igual que el resto).
       El estado viaja junto al blob: el padre lo guarda para restaurarlo
       si se vuelve a editar (W27b). */
    const apply = function () {
      if (!img) return;
      const off = document.createElement('canvas');
      off.width = OUT;
      off.height = OUT;
      const st = state();
      clampPan(st, img, OUT);
      drawInto(off.getContext('2d'), OUT, img, st);
      off.toBlob(function (b) {
        if (b) ctx.emit('confirm', b, state());
      }, 'image/png');
    };
    const cancel = function () {
      ctx.emit('cancel');
    };

    return { cv, zoom, ready, draw, down, move, up, rotate, reset, apply, cancel };
  },
  template: `
    <div class="av-ed" role="group" :aria-label="t('Ajustar foto')">
      <p class="av-ed-hint">{{ t('Arrastra para encuadrar') }}</p>
      <canvas class="av-ed-cv" ref="cv" width="220" height="220"
        :aria-label="t('Arrastra para encuadrar')"
        @pointerdown="down" @pointermove="move" @pointerup="up"
        @pointercancel="up"></canvas>
      <div class="av-ed-zoom">
        <input type="range" class="wp-range" min="1" max="3" step="0.05"
          v-model.number="zoom" :aria-label="t('Zoom')" @input="draw">
      </div>
      <div class="av-ed-row">
        <button class="btn btn-ghost" type="button" @click="rotate">
          <svg class="ic ic-sm"><use href="#i-refresh"></use></svg>{{ t('Girar') }}
        </button>
        <button class="btn btn-ghost" type="button" @click="reset">{{ t('Restablecer') }}</button>
      </div>
      <div class="av-ed-row">
        <button class="btn btn-ghost" type="button" @click="cancel">{{ t('Cancelar') }}</button>
        <button class="btn" type="button" :disabled="!ready" @click="apply">{{ t('Aplicar') }}</button>
      </div>
    </div>`,
};
