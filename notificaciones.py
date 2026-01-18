"""
Modulo de notificaciones - SMS para USA, WhatsApp para Cuba
USA (Cliente/Admin): SMS - confiable, siempre llega
Cuba (Repartidor/Beneficiario): WhatsApp con opcion de envio manual
"""
from twilio.rest import Client
from flask import current_app
from urllib.parse import quote
import logging

logger = logging.getLogger(__name__)


def detectar_pais(telefono):
    """
    Detecta el pais basado en el prefijo del telefono

    Returns:
        'usa' para +1, 'cuba' para +53, 'otro' para otros
    """
    if not telefono:
        return 'otro'

    telefono = telefono.strip()
    if telefono.startswith('+1'):
        return 'usa'
    elif telefono.startswith('+53'):
        return 'cuba'
    return 'otro'


def enviar_sms(telefono, mensaje):
    """
    Envia SMS usando Twilio - Para USA (confiable)

    Args:
        telefono: Numero con codigo de pais (+1...)
        mensaje: Texto del mensaje

    Returns:
        dict con 'exito' (bool) y 'mensaje' o 'error'
    """
    try:
        account_sid = current_app.config.get('TWILIO_ACCOUNT_SID')
        auth_token = current_app.config.get('TWILIO_AUTH_TOKEN')
        from_number = current_app.config.get('TWILIO_SMS_FROM', '+18573251393')

        if not all([account_sid, auth_token]):
            logger.warning("Credenciales de Twilio no configuradas")
            return {
                'exito': False,
                'error': 'Credenciales de Twilio no configuradas'
            }

        client = Client(account_sid, auth_token)

        message = client.messages.create(
            body=mensaje,
            from_=from_number,
            to=telefono
        )

        logger.info(f"SMS enviado a {telefono}: {message.sid}")
        return {
            'exito': True,
            'mensaje': f'SMS enviado: {message.sid}'
        }

    except Exception as e:
        logger.error(f"Error enviando SMS: {str(e)}")
        return {
            'exito': False,
            'error': str(e)
        }


def enviar_whatsapp(telefono, mensaje):
    """
    Envia WhatsApp usando Twilio - Para Cuba
    Puede fallar por conectividad, retorna link manual como respaldo

    Args:
        telefono: Numero con codigo de pais (+53...)
        mensaje: Texto del mensaje

    Returns:
        dict con 'exito', 'mensaje'/'error', y 'link_manual' si falla
    """
    try:
        account_sid = current_app.config.get('TWILIO_ACCOUNT_SID')
        auth_token = current_app.config.get('TWILIO_AUTH_TOKEN')
        from_number = current_app.config.get('TWILIO_WHATSAPP_FROM')

        if not all([account_sid, auth_token, from_number]):
            link = generar_link_whatsapp(telefono, mensaje)
            return {
                'exito': False,
                'error': 'Credenciales no configuradas',
                'link_manual': link
            }

        # Formatear numeros para WhatsApp
        telefono_wa = f'whatsapp:{telefono}' if not telefono.startswith('whatsapp:') else telefono
        from_wa = f'whatsapp:{from_number}' if not from_number.startswith('whatsapp:') else from_number

        client = Client(account_sid, auth_token)

        message = client.messages.create(
            body=mensaje,
            from_=from_wa,
            to=telefono_wa
        )

        logger.info(f"WhatsApp enviado a {telefono}: {message.sid}")
        return {
            'exito': True,
            'mensaje': f'WhatsApp enviado: {message.sid}'
        }

    except Exception as e:
        logger.error(f"Error enviando WhatsApp: {str(e)}")
        link = generar_link_whatsapp(telefono, mensaje)
        return {
            'exito': False,
            'error': str(e),
            'link_manual': link
        }


def generar_link_whatsapp(telefono, mensaje):
    """
    Genera un link wa.me para envio manual de WhatsApp
    Util cuando falla el envio automatico (comun en Cuba)

    Args:
        telefono: Numero con codigo de pais
        mensaje: Texto del mensaje

    Returns:
        URL de WhatsApp listo para abrir
    """
    # Limpiar telefono (solo numeros)
    telefono_limpio = ''.join(c for c in telefono if c.isdigit())
    mensaje_encoded = quote(mensaje)
    return f"https://wa.me/{telefono_limpio}?text={mensaje_encoded}"


def enviar_notificacion(telefono, mensaje):
    """
    Funcion inteligente que selecciona SMS o WhatsApp segun el pais

    USA (+1): SMS - siempre confiable
    Cuba (+53): WhatsApp con link manual de respaldo

    Returns:
        dict con resultado y link_manual si aplica
    """
    pais = detectar_pais(telefono)

    if pais == 'usa':
        # USA: usar SMS (confiable)
        resultado = enviar_sms(telefono, mensaje)
        resultado['metodo'] = 'sms'
        return resultado
    else:
        # Cuba y otros: usar WhatsApp
        resultado = enviar_whatsapp(telefono, mensaje)
        resultado['metodo'] = 'whatsapp'
        return resultado


# ==========================================
# FUNCIONES DE NOTIFICACION POR EVENTO
# ==========================================

def notificar_nueva_remesa(repartidor, remesa):
    """
    Notifica a un repartidor (Cuba) sobre nueva remesa asignada
    Usa WhatsApp con link manual de respaldo
    """
    if not repartidor.telefono:
        logger.warning(f"Repartidor {repartidor.nombre} sin telefono")
        return {'exito': False, 'error': 'Sin telefono configurado'}

    mensaje = f"""*Nueva Remesa Asignada*

Codigo: {remesa.codigo}
Beneficiario: {remesa.beneficiario_nombre}
Telefono: {remesa.beneficiario_telefono or 'No disponible'}
Direccion: {remesa.beneficiario_direccion or 'No especificada'}

Monto a entregar: {remesa.monto_entrega:.2f} {remesa.moneda_entrega}

{remesa.notas if remesa.notas else ''}"""

    # Repartidor en Cuba -> WhatsApp
    return enviar_whatsapp(repartidor.telefono, mensaje)


def notificar_remesa_cancelada(repartidor, remesa):
    """Notifica al repartidor (Cuba) que una remesa fue cancelada"""
    if not repartidor.telefono:
        return {'exito': False, 'error': 'Sin telefono'}

    mensaje = f"""*Remesa Cancelada*

La remesa {remesa.codigo} ha sido cancelada.
Beneficiario: {remesa.beneficiario_nombre}"""

    return enviar_whatsapp(repartidor.telefono, mensaje)


def notificar_remitente(remesa):
    """
    Notifica al remitente/cliente (USA) que su remesa fue creada
    Usa SMS - siempre confiable
    """
    if not remesa.remitente_telefono:
        logger.warning(f"Remesa {remesa.codigo}: remitente sin telefono")
        return {'exito': False, 'error': 'Remitente sin telefono'}

    repartidor_nombre = remesa.repartidor.nombre if remesa.repartidor else 'Por asignar'

    mensaje = f"""HAPPY REMESITAS - Remesa Confirmada

Codigo: {remesa.codigo}
Beneficiario: {remesa.beneficiario_nombre}
Monto a entregar: {remesa.monto_entrega:.2f} {remesa.moneda_entrega}
Total cobrado: ${remesa.total_cobrado:.2f} USD

Repartidor: {repartidor_nombre}

Gracias por usar nuestro servicio."""

    # Cliente en USA -> SMS
    return enviar_sms(remesa.remitente_telefono, mensaje)


def notificar_beneficiario(remesa):
    """
    Notifica al beneficiario/destinatario (Cuba) que tiene remesa en camino
    Usa WhatsApp con link manual de respaldo
    """
    if not remesa.beneficiario_telefono:
        logger.warning(f"Remesa {remesa.codigo}: beneficiario sin telefono")
        return {'exito': False, 'error': 'Beneficiario sin telefono'}

    mensaje = f"""*Remesa en Camino*

Hola {remesa.beneficiario_nombre},

Tiene una remesa pendiente de entrega:

Codigo: {remesa.codigo}
Monto a recibir: {remesa.monto_entrega:.2f} {remesa.moneda_entrega}
Remitente: {remesa.remitente_nombre}

Nuestro repartidor se comunicara con usted pronto.

Gracias."""

    # Beneficiario en Cuba -> WhatsApp
    return enviar_whatsapp(remesa.beneficiario_telefono, mensaje)


def notificar_entrega_admin(remesa, repartidor):
    """
    Notifica a los administradores (USA) que una remesa fue entregada
    Usa SMS - siempre confiable
    """
    from models import Usuario

    admins = Usuario.query.filter_by(rol='admin', activo=True).filter(
        Usuario.telefono.isnot(None),
        Usuario.telefono != ''
    ).all()

    if not admins:
        logger.warning("No hay admins con telefono para notificar")
        return {'exito': False, 'error': 'No hay admins con telefono'}

    mensaje = f"""HAPPY REMESITAS - Remesa Entregada

Codigo: {remesa.codigo}
Beneficiario: {remesa.beneficiario_nombre}
Monto: {remesa.monto_entrega:.2f} {remesa.moneda_entrega}

Entregada por: {repartidor.nombre}
Hora: {remesa.fecha_entrega.strftime('%d/%m/%Y %H:%M')}"""

    resultados = []
    for admin in admins:
        # Admin en USA -> SMS
        resultado = enviar_sms(admin.telefono, mensaje)
        resultados.append({
            'admin': admin.nombre,
            'exito': resultado['exito']
        })

    exitos = sum(1 for r in resultados if r['exito'])
    return {
        'exito': exitos > 0,
        'mensaje': f'Notificado a {exitos}/{len(admins)} admins'
    }


def notificar_entrega_remitente(remesa):
    """
    Notifica al remitente (USA) que su remesa fue entregada
    Usa SMS - siempre confiable
    """
    if not remesa.remitente_telefono:
        return {'exito': False, 'error': 'Remitente sin telefono'}

    mensaje = f"""HAPPY REMESITAS - Remesa Entregada!

Su remesa {remesa.codigo} fue entregada exitosamente.

Beneficiario: {remesa.beneficiario_nombre}
Monto entregado: {remesa.monto_entrega:.2f} {remesa.moneda_entrega}
Fecha: {remesa.fecha_entrega.strftime('%d/%m/%Y %H:%M')}

Gracias por confiar en nosotros!"""

    # Cliente en USA -> SMS
    return enviar_sms(remesa.remitente_telefono, mensaje)


# ==========================================
# NOTIFICACIONES PARA ADMIN (WhatsApp Manual)
# ==========================================

def notificar_admin_nueva_remesa(remesa, es_solicitud=False):
    """
    Genera link de WhatsApp para notificar al admin sobre nueva remesa
    Retorna dict con link_manual para mostrar en la interfaz
    """
    from models import Usuario

    admin = Usuario.query.filter_by(rol='admin', activo=True).filter(
        Usuario.telefono.isnot(None),
        Usuario.telefono != ''
    ).first()

    if not admin or not admin.telefono:
        return {'exito': False, 'error': 'Admin sin telefono configurado'}

    tipo = "SOLICITUD" if es_solicitud else "REMESA"
    creador = remesa.creador.nombre if remesa.creador else "Sistema"

    mensaje = f"""*Nueva {tipo}*

Codigo: {remesa.codigo}
Creada por: {creador}

Remitente: {remesa.remitente_nombre}
Beneficiario: {remesa.beneficiario_nombre}
Telefono: {remesa.beneficiario_telefono or 'No disponible'}
Direccion: {remesa.beneficiario_direccion or 'No especificada'}

Monto envio: ${remesa.monto_envio:.2f} USD
Monto entrega: {remesa.monto_entrega:.2f} {remesa.moneda_entrega}
Total cobrado: ${remesa.total_cobrado:.2f} USD

{remesa.notas if remesa.notas else ''}"""

    link = generar_link_whatsapp(admin.telefono, mensaje)
    return {
        'exito': True,
        'link_manual': link,
        'admin_nombre': admin.nombre,
        'admin_telefono': admin.telefono
    }


def notificar_admin_cambio_estado(remesa, estado_anterior, estado_nuevo, usuario_cambio=None):
    """
    Genera link de WhatsApp para notificar al admin sobre cambio de estado
    """
    from models import Usuario

    admin = Usuario.query.filter_by(rol='admin', activo=True).filter(
        Usuario.telefono.isnot(None),
        Usuario.telefono != ''
    ).first()

    if not admin or not admin.telefono:
        return {'exito': False, 'error': 'Admin sin telefono configurado'}

    estados_texto = {
        'pendiente': 'Pendiente',
        'en_proceso': 'En Proceso',
        'entregada': 'Entregada',
        'cancelada': 'Cancelada',
        'solicitud': 'Solicitud'
    }

    usuario = usuario_cambio.nombre if usuario_cambio else "Sistema"

    mensaje = f"""*Cambio de Estado*

Remesa: {remesa.codigo}
Beneficiario: {remesa.beneficiario_nombre}

Estado anterior: {estados_texto.get(estado_anterior, estado_anterior)}
Estado nuevo: {estados_texto.get(estado_nuevo, estado_nuevo)}

Cambiado por: {usuario}
Monto: {remesa.monto_entrega:.2f} {remesa.moneda_entrega}"""

    link = generar_link_whatsapp(admin.telefono, mensaje)
    return {
        'exito': True,
        'link_manual': link,
        'admin_nombre': admin.nombre
    }


def notificar_admin_nueva_solicitud(remesa):
    """
    Genera link de WhatsApp para notificar al admin sobre nueva solicitud de cliente
    """
    return notificar_admin_nueva_remesa(remesa, es_solicitud=True)


def obtener_links_notificacion_remesa(remesa, repartidor=None):
    """
    Genera todos los links de WhatsApp necesarios para una remesa
    Util para mostrar en la interfaz despues de crear/modificar una remesa

    Returns:
        dict con links para: admin, repartidor, beneficiario
    """
    links = {}

    # Link para admin
    admin_result = notificar_admin_nueva_remesa(remesa)
    if admin_result.get('link_manual'):
        links['admin'] = {
            'nombre': admin_result.get('admin_nombre', 'Admin'),
            'link': admin_result['link_manual']
        }

    # Link para repartidor
    if repartidor and repartidor.telefono:
        mensaje_repartidor = f"""*Nueva Remesa Asignada*

Codigo: {remesa.codigo}
Beneficiario: {remesa.beneficiario_nombre}
Telefono: {remesa.beneficiario_telefono or 'No disponible'}
Direccion: {remesa.beneficiario_direccion or 'No especificada'}

Monto a entregar: {remesa.monto_entrega:.2f} {remesa.moneda_entrega}

{remesa.notas if remesa.notas else ''}"""
        links['repartidor'] = {
            'nombre': repartidor.nombre,
            'link': generar_link_whatsapp(repartidor.telefono, mensaje_repartidor)
        }

    # Link para beneficiario
    if remesa.beneficiario_telefono:
        mensaje_beneficiario = f"""*Remesa en Camino*

Hola {remesa.beneficiario_nombre},

Tiene una remesa pendiente de entrega:

Codigo: {remesa.codigo}
Monto a recibir: {remesa.monto_entrega:.2f} {remesa.moneda_entrega}
Remitente: {remesa.remitente_nombre}

Nuestro repartidor se comunicara con usted pronto.

Gracias."""
        links['beneficiario'] = {
            'nombre': remesa.beneficiario_nombre,
            'link': generar_link_whatsapp(remesa.beneficiario_telefono, mensaje_beneficiario)
        }

    return links
