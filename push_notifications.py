"""
Modulo de Push Notifications para PWA
Usa Web Push Protocol con VAPID para enviar notificaciones a navegadores
"""
import json
import logging
import base64
import os
import tempfile
from flask import current_app

logger = logging.getLogger(__name__)

# Cache para el archivo PEM
_vapid_pem_path = None


def _get_vapid_pem_path():
    """
    Convierte la clave VAPID privada raw a formato PEM y la guarda en un archivo.
    Retorna la ruta al archivo PEM.
    """
    global _vapid_pem_path

    # Siempre recrear para evitar problemas de cache
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives import serialization

    vapid_private = current_app.config.get('VAPID_PRIVATE_KEY')
    if not vapid_private:
        logger.error("VAPID_PRIVATE_KEY no está configurada")
        return None

    logger.info(f"VAPID_PRIVATE_KEY: {vapid_private[:20]}...")

    try:
        # Decodificar la clave base64url
        key_b64 = vapid_private
        padding = 4 - len(key_b64) % 4
        if padding != 4:
            key_b64 += '=' * padding
        key_bytes = base64.urlsafe_b64decode(key_b64)
        logger.info(f"Clave decodificada: {len(key_bytes)} bytes")

        # Crear la clave privada EC
        private_value = int.from_bytes(key_bytes, 'big')
        private_key = ec.derive_private_key(private_value, ec.SECP256R1(), default_backend())
        logger.info("Clave EC creada correctamente")

        # Serializar a PEM
        pem_bytes = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        )
        logger.info(f"PEM generado: {len(pem_bytes)} bytes")

        # Guardar en archivo dentro del proyecto
        pem_path = os.path.join(current_app.root_path, 'vapid_private.pem')
        with open(pem_path, 'wb') as f:
            f.write(pem_bytes)

        logger.info(f"VAPID PEM guardado en: {pem_path}")
        return pem_path

    except Exception as e:
        logger.error(f"Error creando VAPID PEM: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None


def enviar_push(suscripcion, titulo, mensaje, url=None, icono=None):
    """
    Envia una notificacion push a una suscripcion especifica

    Args:
        suscripcion: Objeto SuscripcionPush o dict con endpoint, p256dh, auth
        titulo: Titulo de la notificacion
        mensaje: Cuerpo del mensaje
        url: URL a abrir al hacer click (opcional)
        icono: URL del icono (opcional, usa default si no se especifica)

    Returns:
        dict con 'exito' (bool) y 'mensaje' o 'error'
    """
    try:
        from pywebpush import webpush
    except ImportError:
        logger.error("pywebpush no esta instalado")
        return {'exito': False, 'error': 'pywebpush no disponible'}

    vapid_pem_path = _get_vapid_pem_path()
    vapid_email = current_app.config.get('VAPID_EMAIL', 'admin@example.com')

    if not vapid_pem_path:
        logger.warning("VAPID_PRIVATE_KEY no configurada o invalida")
        return {'exito': False, 'error': 'VAPID no configurado'}

    # Obtener datos de suscripcion
    if hasattr(suscripcion, 'endpoint'):
        subscription_info = {
            "endpoint": suscripcion.endpoint,
            "keys": {
                "p256dh": suscripcion.p256dh,
                "auth": suscripcion.auth
            }
        }
    else:
        subscription_info = suscripcion

    # Construir payload
    payload = {
        "title": titulo,
        "body": mensaje,
        "icon": icono or "/static/images/icon-192x192.png",
        "badge": "/static/images/icon-72x72.png",
        "url": url or "/"
    }

    try:
        import time
        import jwt
        import requests
        import http_ece
        import os as _os
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.backends import default_backend
        from cryptography.hazmat.primitives import serialization

        # Crear clave EC desde la clave raw
        vapid_raw = current_app.config.get('VAPID_PRIVATE_KEY')

        key_b64 = vapid_raw
        padding = 4 - len(key_b64) % 4
        if padding != 4:
            key_b64 += '=' * padding
        key_bytes = base64.urlsafe_b64decode(key_b64)

        private_value = int.from_bytes(key_bytes, 'big')
        private_key = ec.derive_private_key(private_value, ec.SECP256R1(), default_backend())
        public_key = private_key.public_key()

        # Extraer audience del endpoint
        endpoint = subscription_info["endpoint"]
        if "fcm.googleapis.com" in endpoint:
            aud = "https://fcm.googleapis.com"
        else:
            parts = endpoint.split("/")
            aud = f"{parts[0]}//{parts[2]}"

        # Crear JWT VAPID manualmente
        now = int(time.time())
        claims = {
            "sub": f"mailto:{vapid_email}",
            "aud": aud,
            "exp": now + 43200  # 12 horas (FCM limite es 24h)
        }

        # Firmar JWT con ES256
        token = jwt.encode(claims, private_key, algorithm="ES256")
        logger.info(f"JWT VAPID creado para: {aud}")

        # Obtener clave pública en formato no comprimido para el header
        public_numbers = public_key.public_numbers()
        x_bytes = public_numbers.x.to_bytes(32, 'big')
        y_bytes = public_numbers.y.to_bytes(32, 'big')
        public_bytes = b'\x04' + x_bytes + y_bytes
        public_b64 = base64.urlsafe_b64encode(public_bytes).rstrip(b'=').decode()

        # Decodificar claves de suscripción
        p256dh = subscription_info["keys"]["p256dh"]
        auth = subscription_info["keys"]["auth"]

        # Añadir padding si es necesario
        p256dh_padded = p256dh + '=' * (4 - len(p256dh) % 4) if len(p256dh) % 4 else p256dh
        auth_padded = auth + '=' * (4 - len(auth) % 4) if len(auth) % 4 else auth

        receiver_key = base64.urlsafe_b64decode(p256dh_padded)
        auth_secret = base64.urlsafe_b64decode(auth_padded)

        # Generar salt aleatorio
        salt = _os.urandom(16)

        # Encriptar el payload usando http_ece
        data = json.dumps(payload).encode('utf-8')
        encrypted = http_ece.encrypt(
            data,
            salt=salt,
            private_key=ec.generate_private_key(ec.SECP256R1(), default_backend()),
            dh=receiver_key,
            auth_secret=auth_secret,
            version="aes128gcm"
        )

        # Headers para la petición
        headers = {
            "Authorization": f"vapid t={token}, k={public_b64}",
            "Content-Type": "application/octet-stream",
            "Content-Encoding": "aes128gcm",
            "TTL": "86400"
        }

        # Enviar push usando requests
        response = requests.post(
            endpoint,
            data=encrypted,
            headers=headers,
            timeout=30
        )

        if response.status_code in [200, 201, 202]:
            logger.info(f"Push enviado: {titulo}")
            return {'exito': True, 'mensaje': 'Notificacion enviada'}
        else:
            logger.error(f"Push fallo: {response.status_code} - {response.text}")
            return {'exito': False, 'error': f"HTTP {response.status_code}: {response.text}"}

    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error enviando push: {error_msg}")

        # Si la suscripcion expiro o es invalida, marcarla como inactiva
        if '410' in error_msg or '404' in error_msg:
            if hasattr(suscripcion, 'activa'):
                from models import db
                suscripcion.activa = False
                db.session.commit()
                logger.info(f"Suscripcion {suscripcion.id} marcada como inactiva")

        return {'exito': False, 'error': error_msg}


def notificar_usuario_push(usuario_id, titulo, mensaje, url=None):
    """
    Envia push a todas las suscripciones activas de un usuario

    Args:
        usuario_id: ID del usuario
        titulo: Titulo de la notificacion
        mensaje: Cuerpo del mensaje
        url: URL a abrir (opcional)

    Returns:
        dict con cantidad de exitos y fallos
    """
    from models import SuscripcionPush

    suscripciones = SuscripcionPush.query.filter_by(
        usuario_id=usuario_id,
        activa=True
    ).all()

    if not suscripciones:
        return {'exitos': 0, 'fallos': 0, 'mensaje': 'Usuario sin suscripciones push'}

    exitos = 0
    fallos = 0
    errores = []

    for sus in suscripciones:
        resultado = enviar_push(sus, titulo, mensaje, url)
        if resultado['exito']:
            exitos += 1
        else:
            fallos += 1
            errores.append(resultado.get('error', 'Error desconocido'))

    respuesta = {
        'exitos': exitos,
        'fallos': fallos,
        'mensaje': f'Enviado a {exitos}/{len(suscripciones)} dispositivos'
    }

    if errores:
        respuesta['errores'] = errores

    return respuesta


def notificar_admins_push(titulo, mensaje, url=None):
    """
    Envia push a todos los administradores activos

    Args:
        titulo: Titulo de la notificacion
        mensaje: Cuerpo del mensaje
        url: URL a abrir (opcional)

    Returns:
        dict con cantidad de exitos y fallos
    """
    from models import Usuario, SuscripcionPush

    # Obtener IDs de admins activos
    admins = Usuario.query.filter_by(rol='admin', activo=True).all()
    admin_ids = [a.id for a in admins]

    if not admin_ids:
        return {'exitos': 0, 'fallos': 0, 'mensaje': 'No hay admins activos'}

    # Obtener suscripciones de todos los admins
    suscripciones = SuscripcionPush.query.filter(
        SuscripcionPush.usuario_id.in_(admin_ids),
        SuscripcionPush.activa == True
    ).all()

    if not suscripciones:
        return {'exitos': 0, 'fallos': 0, 'mensaje': 'Admins sin suscripciones push'}

    exitos = 0
    fallos = 0

    for sus in suscripciones:
        resultado = enviar_push(sus, titulo, mensaje, url)
        if resultado['exito']:
            exitos += 1
        else:
            fallos += 1

    return {
        'exitos': exitos,
        'fallos': fallos,
        'mensaje': f'Notificado a {exitos} dispositivos de admins'
    }


def notificar_repartidor_push(repartidor_id, titulo, mensaje, url=None):
    """
    Envia push a un repartidor especifico

    Args:
        repartidor_id: ID del repartidor
        titulo: Titulo de la notificacion
        mensaje: Cuerpo del mensaje
        url: URL a abrir (opcional)

    Returns:
        dict con resultado
    """
    return notificar_usuario_push(repartidor_id, titulo, mensaje, url)


# ==========================================
# FUNCIONES DE NOTIFICACION POR EVENTO
# ==========================================

def push_nueva_remesa_admin(remesa):
    """Notifica a admins sobre nueva remesa creada"""
    titulo = "Nueva Remesa"
    mensaje = f"{remesa.codigo} - {remesa.beneficiario_nombre} (${remesa.monto_envio:.2f} USD)"
    url = f"/remesas/{remesa.id}"
    return notificar_admins_push(titulo, mensaje, url)


def push_remesa_asignada(remesa):
    """Notifica al repartidor que tiene nueva remesa asignada"""
    if not remesa.repartidor_id:
        return {'exitos': 0, 'mensaje': 'Sin repartidor asignado'}

    titulo = "Nueva Entrega Asignada"
    mensaje = f"{remesa.codigo} - {remesa.beneficiario_nombre}\n{remesa.monto_entrega:.2f} {remesa.moneda_entrega}"
    url = "/repartidor/panel"
    return notificar_repartidor_push(remesa.repartidor_id, titulo, mensaje, url)


def push_remesa_entregada_admin(remesa):
    """Notifica a admins que una remesa fue entregada"""
    repartidor_nombre = remesa.repartidor.nombre if remesa.repartidor else "Sistema"
    titulo = "Remesa Entregada"
    mensaje = f"{remesa.codigo} entregada por {repartidor_nombre}"
    url = f"/remesas/{remesa.id}"
    return notificar_admins_push(titulo, mensaje, url)


def push_nueva_solicitud_admin(remesa):
    """Notifica a admins sobre nueva solicitud de cliente"""
    titulo = "Nueva Solicitud"
    mensaje = f"Solicitud de {remesa.remitente_nombre} - ${remesa.monto_envio:.2f} USD"
    url = "/dashboard"
    return notificar_admins_push(titulo, mensaje, url)
