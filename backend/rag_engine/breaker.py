import time
import logging
import redis
from django.conf import settings

logger = logging.getLogger(__name__)

class EstadoBreaker:
    CERRADO = "CERRADO"          # Tráfico fluye normalmente
    ABIERTO = "ABIERTO"          # Tráfico bloqueado completamente
    MEDIO_ABIERTO = "MEDIO_ABIERTO" # Deja pasar 1 petición de prueba

class CircuitOpenException(Exception):
    """Excepción lanzada cuando el circuito rechaza tráfico para proteger el sistema."""
    pass

class GestorCircuitBreaker:
    """
    Estructura modular para gestionar la tolerancia a fallos de servicios externos.
    Diseñado para operar de forma distribuida usando Redis.
    """
    def __init__(self, servicio, umbral_fallos=3, ttl_abierto=60):
        self.servicio = servicio
        self.umbral_fallos = umbral_fallos
        self.ttl_abierto = ttl_abierto
        
        # Conexión directa al pool de Redis configurado en el entorno
        self.redis = redis.StrictRedis.from_url(settings.CELERY_BROKER_URL, decode_responses=True)
        
        self.key_estado = f"breaker:estado:{servicio}"
        self.key_fallos = f"breaker:fallos:{servicio}"
        self.key_timeout = f"breaker:timeout:{servicio}"

    def allow_request(self, request_id="N/A"):
        """Evalúa si la petición puede pasar hacia el servicio externo."""
        estado_actual = self.redis.get(self.key_estado) or EstadoBreaker.CERRADO

        if estado_actual == EstadoBreaker.ABIERTO:
            # Verifica si ya pasó el tiempo de castigo (TTL)
            if not self.redis.exists(self.key_timeout):
                self.redis.set(self.key_estado, EstadoBreaker.MEDIO_ABIERTO)
                logger.info(f"[{request_id}] Breaker {self.servicio} cambia a MEDIO_ABIERTO. Probando conexión.")
                return True
            logger.warning(f"[{request_id}] Breaker {self.servicio} ABIERTO. Petición rechazada en capa de red.")
            raise CircuitOpenException(f"El servicio {self.servicio} está temporalmente inactivo.")
        
        return True

    def registrar_fallo(self, request_id="N/A"):
        """Registra un fallo. Si supera el umbral, abre el circuito."""
        fallos = self.redis.incr(self.key_fallos)
        
        if fallos >= self.umbral_fallos:
            self.redis.set(self.key_estado, EstadoBreaker.ABIERTO)
            self.redis.setex(self.key_timeout, self.ttl_abierto, "bloqueado")
            logger.critical(f"[{request_id}] Breaker {self.servicio} ABIERTO tras {fallos} fallos consecutivos.")

    def registrar_exito(self, request_id="N/A"):
        """Resetea los contadores de fallo al detectar una conexión exitosa."""
        estado_actual = self.redis.get(self.key_estado)
        if estado_actual != EstadoBreaker.CERRADO:
            logger.info(f"[{request_id}] Breaker {self.servicio} recuperado. Cambiando a CERRADO.")
        
        self.redis.set(self.key_estado, EstadoBreaker.CERRADO)
        self.redis.delete(self.key_fallos)
        self.redis.delete(self.key_timeout)

        