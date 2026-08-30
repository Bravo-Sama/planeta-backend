import json
import logging
import time

logger = logging.getLogger("planeta.breaker")


class CircuitOpenException(RuntimeError):
    """Se lanza cuando un servicio está en estado ABIERTO y se rechaza la consulta."""


class GestorCircuitBreaker:
    """Circuit Breaker centralizado respaldado por Redis para servicios externos."""

    CERRADO = "CERRADO"
    ABIERTO = "ABIERTO"
    MEDIO_ABIERTO = "MEDIO_ABIERTO"

    def __init__(self, redis_client, key_prefix="planeta:breaker", ttl_segundos=30, max_fallos=3):
        self.redis = redis_client
        self.key_prefix = key_prefix
        self.ttl_segundos = ttl_segundos
        self.max_fallos = max_fallos

    def _estado_key(self, servicio):
        return f"{self.key_prefix}:{servicio}:estado"

    def _fallos_key(self, servicio):
        return f"{self.key_prefix}:{servicio}:fallos"

    def _snapshot_key(self, servicio):
        return f"{self.key_prefix}:{servicio}:snapshot"

    def _abierto_ts_key(self, servicio):
        return f"{self.key_prefix}:{servicio}:abierto_ts"

    def _estado_clúster(self):
        servicios = ["ollama", "qdrant", "telegram", "redis", "mariadb"]
        estado = {}
        for servicio in servicios:
            estado[servicio] = self.redis.get(self._estado_key(servicio)) or self.CERRADO
        return estado

    def allow_request(self, servicio):
        """Retorna True si se puede continuar. Si el circuito está abierto, lanza excepción."""
        estado = self.redis.get(self._estado_key(servicio)) or self.CERRADO
        if estado == self.ABIERTO:
            ts_abierto = self.redis.get(self._abierto_ts_key(servicio))
            try:
                ts_abierto = float(ts_abierto) if ts_abierto is not None else 0.0
            except (TypeError, ValueError):
                ts_abierto = 0.0
            if (time.time() - ts_abierto) < self.ttl_segundos:
                logger.critical(
                    "Circuit breaker OPEN. servicio=%s estado=%s clúster=%s ttl_segundos=%s",
                    servicio,
                    estado,
                    self._estado_clúster(),
                    self.ttl_segundos,
                )
                raise CircuitOpenException(f"Circuito abierto para {servicio}")
            self.redis.set(self._estado_key(servicio), self.MEDIO_ABIERTO, ex=self.ttl_segundos)
            logger.warning(
                "Circuit breaker transicionó a MEDIO_ABIERTO. servicio=%s clúster=%s",
                servicio,
                self._estado_clúster(),
            )
            return True

        if estado == self.MEDIO_ABIERTO:
            logger.warning(
                "Circuit breaker en MEDIO_ABIERTO. servicio=%s clúster=%s",
                servicio,
                self._estado_clúster(),
            )
            return True

        return True

    def registrar_fallo(self, servicio):
        """Incrementa el contador de fallos y abre el circuito si excede el umbral."""
        contador = int(self.redis.get(self._fallos_key(servicio)) or 0) + 1
        self.redis.set(self._fallos_key(servicio), contador, ex=self.ttl_segundos)

        if contador >= self.max_fallos:
            self.redis.set(self._estado_key(servicio), self.ABIERTO, ex=self.ttl_segundos)
            self.redis.set(self._abierto_ts_key(servicio), time.time(), ex=self.ttl_segundos)
            logger.critical(
                "Circuit breaker abierto por fallos consecutivos. servicio=%s contador=%s clúster=%s",
                servicio,
                contador,
                self._estado_clúster(),
            )
        else:
            logger.warning(
                "Fallo registrado. servicio=%s fallos=%s clúster=%s",
                servicio,
                contador,
                self._estado_clúster(),
            )

    def registrar_exito(self, servicio):
        """Reinicia el contador de fallos y devuelve el servicio a CERRADO."""
        self.redis.delete(self._fallos_key(servicio))
        self.redis.set(self._estado_key(servicio), self.CERRADO, ex=self.ttl_segundos)
        self.redis.delete(self._abierto_ts_key(servicio))
        logger.info(
            "Circuit breaker cerrado. servicio=%s clúster=%s",
            servicio,
            self._estado_clúster(),
        )

    def get_state(self, servicio):
        return self.redis.get(self._estado_key(servicio)) or self.CERRADO

    def should_bounce(self, servicio, ok):
        if not ok:
            self.registrar_fallo(servicio)
            return True
        self.registrar_exito(servicio)
        return False


class CircuitBreaker(GestorCircuitBreaker):
    """Alias de compatibilidad para código previo al refactor."""

    def __init__(self, redis_client, key_prefix="planeta:breaker", ttl_seconds=30, max_fallos=3):
        super().__init__(redis_client, key_prefix=key_prefix, ttl_segundos=ttl_seconds, max_fallos=max_fallos)

    def allow_request(self, servicio=None):
        if servicio is None:
            servicio = "rag"
        return super().allow_request(servicio)

    def record_failure(self, qdrant_ok, ollama_ok):
        for servicio, ok in {"qdrant": qdrant_ok, "ollama": ollama_ok}.items():
            if not ok:
                self.registrar_fallo(servicio)

    def record_success(self):
        for servicio in ("qdrant", "ollama"):
            self.registrar_exito(servicio)

    def set_half_open(self):
        for servicio in ("qdrant", "ollama"):
            self.redis.set(self._estado_key(servicio), self.MEDIO_ABIERTO, ex=self.ttl_segundos)

    def should_bounce(self, qdrant_ok, ollama_ok):
        if not qdrant_ok or not ollama_ok:
            self.record_failure(qdrant_ok, ollama_ok)
            return True
        self.record_success()
        return False
