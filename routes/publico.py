"""
Rutas publicas para clientes - Solicitar remesas
"""
from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify
from models import db, Remesa, TasaCambio, Usuario
from notificaciones import enviar_whatsapp, notificar_admin_nueva_solicitud
from push_notifications import push_nueva_solicitud_admin
from datetime import datetime

publico_bp = Blueprint('publico', __name__)

# Configuracion de comisiones
COMISION_USD = 0.05  # 5%
DESCUENTO_MN = 15    # 15 CUP menos por dolar


@publico_bp.route('/solicitar', methods=['GET', 'POST'])
def solicitar_remesa():
    """Formulario publico para solicitar remesa"""
    
    # Obtener tasas actuales
    tasa_usd = TasaCambio.query.filter_by(moneda_origen='USD', activa=True).first()
    tasa_actual = tasa_usd.tasa if tasa_usd else 435
    
    if request.method == 'POST':
        # Datos del formulario
        remitente_nombre = request.form.get('remitente_nombre', '').strip()
        remitente_telefono = request.form.get('remitente_telefono', '').strip()
        beneficiario_nombre = request.form.get('beneficiario_nombre', '').strip()
        beneficiario_telefono = request.form.get('beneficiario_telefono', '').strip()
        beneficiario_direccion = request.form.get('beneficiario_direccion', '').strip()
        monto_envio = float(request.form.get('monto_envio', 0))
        tipo_entrega = request.form.get('tipo_entrega', 'MN')
        
        # Validaciones
        if not all([remitente_nombre, remitente_telefono, beneficiario_nombre, monto_envio]):
            flash('Por favor complete todos los campos obligatorios', 'error')
            return render_template('publico/solicitar.html', tasa_actual=tasa_actual)
        
        # Calcular montos segun tipo
        if tipo_entrega == 'USD':
            # USD: 5% comision
            comision = monto_envio * COMISION_USD
            monto_entrega = monto_envio - comision
            moneda_entrega = 'USD'
            tasa_aplicada = 1.0
        else:
            # MN: tasa - 15 CUP
            tasa_aplicada = tasa_actual - DESCUENTO_MN
            monto_entrega = monto_envio * tasa_aplicada
            moneda_entrega = 'CUP'
            comision = DESCUENTO_MN * monto_envio  # valor aproximado de la comision
        
        # Crear solicitud (sin creado_por porque es publico)
        # Usamos el admin por defecto
        admin = Usuario.query.filter_by(rol='admin').first()
        
        nueva_remesa = Remesa(
            remitente_nombre=remitente_nombre,
            remitente_telefono=remitente_telefono,
            beneficiario_nombre=beneficiario_nombre,
            beneficiario_telefono=beneficiario_telefono,
            beneficiario_direccion=beneficiario_direccion,
            tipo_entrega=tipo_entrega,
            monto_envio=monto_envio,
            tasa_cambio=tasa_aplicada,
            monto_entrega=monto_entrega,
            moneda_entrega=moneda_entrega,
            comision_porcentaje=COMISION_USD * 100 if tipo_entrega == 'USD' else 0,
            comision_fija=0 if tipo_entrega == 'USD' else DESCUENTO_MN,
            total_comision=comision,
            total_cobrado=monto_envio,
            estado='solicitud',  # Estado especial para solicitudes
            es_solicitud=True,
            creado_por=admin.id if admin else 1
        )
        
        db.session.add(nueva_remesa)
        db.session.commit()

        # Enviar Push Notification a admins
        try:
            push_nueva_solicitud_admin(nueva_remesa)
        except Exception as e:
            print(f"Error enviando push: {e}")

        # Notificar al admin por WhatsApp
        admin_con_tel = Usuario.query.filter_by(rol='admin', activo=True).filter(
            Usuario.telefono.isnot(None)
        ).first()
        
        if admin_con_tel:
            mensaje = f"""*NUEVA SOLICITUD DE REMESA*

Codigo: {nueva_remesa.codigo}
Remitente: {remitente_nombre}
Tel: {remitente_telefono}

Beneficiario: {beneficiario_nombre}
Direccion: {beneficiario_direccion or 'No especificada'}

Monto: ${monto_envio} USD
Entrega: ${monto_entrega:,.2f} {moneda_entrega}
Tipo: {tipo_entrega}

Revisa el panel para aprobar o modificar."""
            enviar_whatsapp(admin_con_tel.telefono, mensaje)
        
        return render_template('publico/solicitud_enviada.html', 
                             remesa=nueva_remesa,
                             monto_entrega=monto_entrega,
                             moneda_entrega=moneda_entrega)
    
    return render_template('publico/solicitar.html', 
                         tasa_actual=tasa_actual,
                         comision_usd=COMISION_USD * 100,
                         descuento_mn=DESCUENTO_MN)



@publico_bp.route('/repetir/<int:id>')
def repetir_remesa(id):
    """Pre-llena el formulario con datos de una remesa anterior"""
    remesa = Remesa.query.get_or_404(id)
    
    tasa_usd = TasaCambio.query.filter_by(moneda_origen='USD', activa=True).first()
    tasa_actual = tasa_usd.tasa if tasa_usd else 435
    
    return render_template('publico/solicitar.html',
                         tasa_actual=tasa_actual,
                         comision_usd=COMISION_USD * 100,
                         descuento_mn=DESCUENTO_MN,
                         remesa_anterior=remesa)


@publico_bp.route('/api/calcular-entrega', methods=['POST'])
def api_calcular_entrega():
    """API para calcular monto a entregar en tiempo real"""
    data = request.get_json()
    monto = float(data.get('monto', 0))
    tipo = data.get('tipo', 'MN')
    
    tasa_usd = TasaCambio.query.filter_by(moneda_origen='USD', activa=True).first()
    tasa_actual = tasa_usd.tasa if tasa_usd else 435
    
    if tipo == 'USD':
        comision = monto * COMISION_USD
        entrega = monto - comision
        moneda = 'USD'
    else:
        tasa_aplicada = tasa_actual - DESCUENTO_MN
        entrega = monto * tasa_aplicada
        moneda = 'CUP'
    
    return jsonify({
        'monto_entrega': round(entrega, 2),
        'moneda': moneda,
        'tasa': tasa_actual if tipo == 'MN' else 1,
        'aproximado': True
    })


@publico_bp.route('/mis-remesas', methods=['GET', 'POST'])
def mis_remesas():
    """Permite al cliente ver sus remesas con su telefono"""
    remesas = []
    telefono = None
    error = None
    
    if request.method == 'POST':
        telefono = request.form.get('telefono', '').strip()
        
        if telefono:
            # Buscar remesas donde el telefono coincida con remitente
            from models import Remesa
            remesas = Remesa.query.filter(
                Remesa.remitente_telefono.ilike(f'%{telefono[-10:]}%')
            ).order_by(Remesa.fecha_creacion.desc()).all()
            
            if not remesas:
                error = 'No encontramos remesas con ese numero. Verifica que sea el mismo numero con el que solicitaste.'
        else:
            error = 'Ingresa tu numero de telefono'
    
    return render_template('publico/mis_remesas.html', 
                         remesas=remesas, 
                         telefono=telefono,
                         error=error)


@publico_bp.route('/api/cliente-datos', methods=['POST'])
def api_cliente_datos():
    """Retorna datos del cliente basado en su telefono (ultima remesa)"""
    data = request.get_json()
    telefono = data.get('telefono', '').strip()
    
    if not telefono or len(telefono) < 8:
        return jsonify({'encontrado': False})
    
    # Buscar ultima remesa del cliente
    remesa = Remesa.query.filter(
        Remesa.remitente_telefono.ilike(f'%{telefono[-10:]}%')
    ).order_by(Remesa.fecha_creacion.desc()).first()
    
    if remesa:
        return jsonify({
            'encontrado': True,
            'remitente_nombre': remesa.remitente_nombre,
            'remitente_telefono': remesa.remitente_telefono,
            'beneficiarios': obtener_beneficiarios_frecuentes(telefono)
        })
    
    return jsonify({'encontrado': False})


def obtener_beneficiarios_frecuentes(telefono):
    """Obtiene los beneficiarios mas frecuentes de un remitente"""
    remesas = Remesa.query.filter(
        Remesa.remitente_telefono.ilike(f'%{telefono[-10:]}%')
    ).order_by(Remesa.fecha_creacion.desc()).limit(10).all()
    
    beneficiarios = {}
    for r in remesas:
        key = r.beneficiario_nombre.lower()
        if key not in beneficiarios:
            beneficiarios[key] = {
                'nombre': r.beneficiario_nombre,
                'telefono': r.beneficiario_telefono or '',
                'direccion': r.beneficiario_direccion or ''
            }
    
    return list(beneficiarios.values())[:5]


@publico_bp.route('/api/historial-cliente', methods=['POST'])
def api_historial_cliente():
    """Retorna historial de remesas del cliente"""
    data = request.get_json()
    telefono = data.get('telefono', '').strip()
    
    if not telefono or len(telefono) < 8:
        return jsonify({'remesas': []})
    
    remesas = Remesa.query.filter(
        Remesa.remitente_telefono.ilike(f'%{telefono[-10:]}%')
    ).order_by(Remesa.fecha_creacion.desc()).limit(10).all()
    
    estados_color = {
        'entregada': 'success',
        'en_proceso': 'primary', 
        'pendiente': 'warning',
        'solicitud': 'info',
        'cancelada': 'danger'
    }
    
    return jsonify({
        'remesas': [{
            'id': r.id,
            'codigo': r.codigo,
            'beneficiario': r.beneficiario_nombre,
            'monto': str(r.monto_envio),
            'fecha': r.fecha_creacion.strftime('%d/%m/%Y'),
            'estado': r.estado.replace('_', ' ').title(),
            'estado_color': estados_color.get(r.estado, 'secondary')
        } for r in remesas]
    })
