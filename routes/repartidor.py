"""
Panel simplificado para repartidores
"""
from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify
from flask_login import login_required, current_user
from models import db, Remesa, MovimientoEfectivo
from notificaciones import enviar_whatsapp, notificar_entrega_admin, generar_link_whatsapp, notificar_admin_cambio_estado
from push_notifications import push_remesa_entregada_admin
from datetime import datetime
from werkzeug.utils import secure_filename
import os

repartidor_bp = Blueprint('repartidor', __name__, url_prefix='/repartidor')

UPLOAD_FOLDER = 'static/fotos_entrega'


@repartidor_bp.route('/panel')
@login_required
def panel():
    """Panel principal del repartidor"""
    if current_user.rol != 'repartidor':
        flash('Acceso no autorizado', 'error')
        return redirect(url_for('auth.login'))

    # Obtener remesas asignadas al repartidor
    pendientes = Remesa.query.filter_by(
        repartidor_id=current_user.id,
        estado='pendiente'
    ).order_by(Remesa.fecha_creacion.desc()).all()

    en_camino = Remesa.query.filter_by(
        repartidor_id=current_user.id,
        estado='en_proceso'
    ).order_by(Remesa.fecha_creacion.desc()).all()

    entregadas_hoy = Remesa.query.filter_by(
        repartidor_id=current_user.id,
        estado='entregada'
    ).filter(
        db.func.date(Remesa.fecha_entrega) == datetime.now().date()
    ).all()

    return render_template('repartidor/panel.html',
                         pendientes=pendientes,
                         en_camino=en_camino,
                         entregadas_hoy=entregadas_hoy)


@repartidor_bp.route('/en-camino/<int:id>', methods=['POST'])
@login_required
def marcar_en_camino(id):
    """Marca una remesa como en camino"""
    remesa = Remesa.query.get_or_404(id)

    if remesa.repartidor_id != current_user.id:
        return jsonify({'error': 'No autorizado'}), 403

    remesa.estado = 'en_proceso'
    db.session.commit()

    # Notificar al beneficiario
    if remesa.beneficiario_telefono:
        mensaje = f"""*REMESA EN CAMINO*

Hola {remesa.beneficiario_nombre},

Tu remesa esta en camino!
Codigo: {remesa.codigo}
Monto: ${remesa.monto_entrega:,.2f} {remesa.moneda_entrega}

El repartidor llegara pronto.

Happy Remesitas"""
        enviar_whatsapp(remesa.beneficiario_telefono, mensaje)

    return jsonify({'success': True, 'mensaje': 'Remesa marcada en camino'})


@repartidor_bp.route('/entregar/<int:id>', methods=['POST'])
@login_required
def marcar_entregada(id):
    """Marca una remesa como entregada"""
    remesa = Remesa.query.get_or_404(id)

    if remesa.repartidor_id != current_user.id:
        return jsonify({'error': 'No autorizado'}), 403

    # Guardar foto si se envio
    foto = request.files.get('foto')
    if foto and foto.filename:
        os.makedirs(UPLOAD_FOLDER, exist_ok=True)
        filename = f"{remesa.codigo}_{datetime.now().strftime('%Y%m%d%H%M%S')}.jpg"
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        foto.save(filepath)
        remesa.foto_entrega = filename

    remesa.estado = 'entregada'
    remesa.fecha_entrega = datetime.now()

    # Descontar del saldo del repartidor automaticamente
    monto_entrega = remesa.monto_entrega
    moneda = remesa.moneda_entrega  # CUP o USD

    if moneda == 'USD':
        saldo_anterior = current_user.saldo_usd or 0
        current_user.saldo_usd = saldo_anterior - monto_entrega
        saldo_nuevo = current_user.saldo_usd
    else:  # CUP
        saldo_anterior = current_user.saldo_cup or 0
        current_user.saldo_cup = saldo_anterior - monto_entrega
        saldo_nuevo = current_user.saldo_cup

    # Registrar movimiento de efectivo
    movimiento = MovimientoEfectivo(
        repartidor_id=current_user.id,
        tipo='entrega',
        moneda=moneda,
        monto=monto_entrega,
        saldo_anterior=saldo_anterior,
        saldo_nuevo=saldo_nuevo,
        remesa_id=remesa.id,
        notas=f'Entrega {remesa.codigo} a {remesa.beneficiario_nombre}',
        registrado_por=current_user.id
    )
    db.session.add(movimiento)

    db.session.commit()

    # Enviar Push Notification a admins
    try:
        push_remesa_entregada_admin(remesa)
    except Exception as e:
        print(f"Error enviando push: {e}")

    # Notificar al remitente
    if remesa.remitente_telefono:
        mensaje = f"""*REMESA ENTREGADA*

Hola {remesa.remitente_nombre},

Tu remesa ha sido entregada exitosamente!

Codigo: {remesa.codigo}
Beneficiario: {remesa.beneficiario_nombre}
Monto entregado: ${remesa.monto_entrega:,.2f} {remesa.moneda_entrega}

Gracias por usar Happy Remesitas!"""
        enviar_whatsapp(remesa.remitente_telefono, mensaje)

    # Notificar al admin - generar link de WhatsApp
    resultado_admin = notificar_admin_cambio_estado(remesa, 'en_proceso', 'entregada', current_user)
    link_admin = resultado_admin.get('link_manual', '')

    return jsonify({
        'success': True,
        'mensaje': 'Remesa entregada',
        'link_admin': link_admin
    })


@repartidor_bp.route('/historial')
@login_required
def historial():
    """Historial de entregas del repartidor"""
    if current_user.rol != 'repartidor':
        return redirect(url_for('auth.login'))

    entregas = Remesa.query.filter_by(
        repartidor_id=current_user.id,
        estado='entregada'
    ).order_by(Remesa.fecha_entrega.desc()).limit(50).all()

    return render_template('repartidor/historial.html', entregas=entregas)
