"""Límite de frecuencia por usuario en memoria (W11).

Token bucket por usuario: admite una pequeña RÁFAGA y después sostiene un
ritmo bajo (por defecto ~3 eventos cada 5 s). Si no hay cupo se devuelve la
espera en segundos para responder 429 con `retry_after`, formato que el
cliente ya entiende ("Espera Ns antes de reintentar").

Sin dependencias y sin estado persistente: se pierde al reiniciar el
servicio, que para un chat de una instancia está bien.
"""
from __future__ import annotations

import time


class TokenBucket:
    def __init__(self, burst: int, rate: float) -> None:
        """rate = tokens por segundo (0.6 → 3 cada 5 s)."""
        self.burst = float(burst)
        self.rate = float(rate)
        # uid -> [tokens disponibles, última actualización]
        self._state: dict[int, list[float]] = {}

    def take(self, uid: int) -> float:
        """Consume 1 token. Devuelve 0.0 si pasó, o la espera en segundos."""
        now = time.monotonic()
        st = self._state.get(uid)
        if st is None:
            st = [self.burst, now]
            self._state[uid] = st
        st[0] = min(self.burst, st[0] + (now - st[1]) * self.rate)
        st[1] = now
        if st[0] >= 1.0:
            st[0] -= 1.0
            return 0.0
        return (1.0 - st[0]) / self.rate

    def prune(self) -> None:
        """Suelta cuentas con la bolsa llena y sin actividad (memoria)."""
        if len(self._state) < 4096:
            return
        now = time.monotonic()
        full_after = self.burst / self.rate  # tiempo en rellenarse del todo
        stale = [k for k, v in self._state.items() if now - v[1] > full_after + 60]
        for k in stale:
            del self._state[k]


# Mensajes de texto/media: ráfaga de 5 y ~3 por 5 s sostenidos (W11).
MESSAGES = TokenBucket(burst=5, rate=0.6)

# W27: solicitudes de amistad — ráfaga de 5 y ~1 cada 5 s (el disco no es
# caro aquí, pero el spam de solicitudes sí molesta).
REQUESTS = TokenBucket(burst=5, rate=0.2)


class SpamBlock:
    """Bloqueo anti-spam escalonado por usuario (W18).

    El token bucket (MESSAGES) ya responde 429 al exceso; este bloqueo
    castiga el INSISTIR: cada rechazo del bucket suma un punto y desde
    el quinto punto seguido la cuenta queda bloqueada para enviar
    mensajes 5 min, duplicándose con cada punto nuevo (10, 20, 40…,
    tope 24 h). Cada 30 min sin volver a exceder el bucket se descuenta
    un punto ("disminuye poco a poco si dejas de hacer spam"). Enviar
    estando bloqueado NO suma puntos: el bloqueo ya es el castigo.

    WARN_HITS=4 deja que una ráfaga accidental (~9 envíos muy seguidos:
    los 5 del bucket + 4 rechazos) solo muestre el aviso y se recupere
    sola; el bloqueo es para el que sigue martillando.
    """

    WARN_HITS = 4          # los primeros rechazos solo avisan (overlay)
    BASE_SEC = 5 * 60      # primer bloqueo: 5 minutos
    MAX_SEC = 24 * 3600    # tope: 24 horas
    DECAY_SEC = 30 * 60    # un punto menos por cada 30 min sin spam

    def __init__(self) -> None:
        # uid -> [puntos, último_punto(ts), bloqueado_hasta(ts)]
        self._state: dict[int, list[float]] = {}

    def remaining(self, uid: int) -> float:
        """Segundos que faltan de bloqueo activo (0 si no está bloqueado)."""
        st = self._state.get(uid)
        if not st:
            return 0.0
        now = time.time()
        return st[2] - now if st[2] > now else 0.0

    def hit(self, uid: int) -> float:
        """Registra un rechazo del bucket. Devuelve los segundos de
        bloqueo aplicados (0.0 = solo aviso, sin bloqueo todavía)."""
        now = time.time()
        st = self._state.get(uid)
        if st is None:
            st = [0.0, now, 0.0]
            self._state[uid] = st
        if st[1] < now:                       # decadencia "poco a poco"
            off = int((now - st[1]) / self.DECAY_SEC)
            if off:
                st[0] = max(0.0, st[0] - off)
                st[1] += off * self.DECAY_SEC
        st[0] += 1.0
        st[1] = now
        if st[0] <= self.WARN_HITS:
            return 0.0                        # 1er aviso: sin bloqueo
        extra = int(st[0]) - self.WARN_HITS   # 1 → 5 min, 2 → 10 min…
        secs = min(self.BASE_SEC * (2 ** (extra - 1)), float(self.MAX_SEC))
        st[2] = now + secs
        return secs

    def prune(self) -> None:
        """Suelta estados viejos (sin bloqueo y sin spam reciente)."""
        if len(self._state) < 4096:
            return
        now = time.time()
        stale = [k for k, v in self._state.items()
                 if v[2] < now and now - v[1] > self.DECAY_SEC * 4]
        for k in stale:
            del self._state[k]


SPAM = SpamBlock()

# W14 (endurecimiento): "escribiendo…" ~1 por 2 s sostenidos (se descarta
# en silencio el exceso: no rompe la UX ni amplifica broadcasts).
TYPING = TokenBucket(burst=3, rate=0.5)
# Reacciones: ráfaga de 8 y ~2 por s (el exceso recibe 429).
REACTIONS = TokenBucket(burst=8, rate=2.0)
# Crear DMs/grupos y agregar miembros: ~1 por minuto sostenido.
# W37f: ahora SÍ se aplica (antes estaba declarada sin usarse). Ráfaga 6
# para cubrir creaciones legítimas seguidas (una suite crea dm+grupo+
# miembro+grupo con el mismo usuario) sin perder el techo de abuso.
CREATIONS = TokenBucket(burst=6, rate=1 / 60)
# Subidas de archivo: ráfaga de 5 y ~1 cada 5 s (el disco es caro).
UPLOADS = TokenBucket(burst=5, rate=0.2)
# W35c: vistas previas de enlaces (unfurl). Ráfaga generosa porque un
# mensaje puede traer varios links; sostenido, 1 cada 5 s por usuario.
LINKPREVIEWS = TokenBucket(burst=15, rate=0.2)
# W36k: marcar/quitar GIFs favoritos (ligero, 2 cada segundo).
FAVORITES = TokenBucket(burst=10, rate=2.0)
