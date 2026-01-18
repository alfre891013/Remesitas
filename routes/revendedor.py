"""
Panel para revendedores
"""
from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify
from flask_login import login_required, current_user
from models import db, Remesa, Usuario, TasaCambio, PagoRevendedor
from datetime import datetime
from functools import wraps
from sqlalchemy import func
from notificaciones import notificar_admin_nueva_remesa, generar_link_whatsapp

revendedor_bp = Blueprint('revendedor', __name__, url_prefix='/revendedor')


def revendedor_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if current_user.rol != 'revendedor':
            flash('Acceso no autorizado', 'error')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function


@revendedor_bp.route('/panel')
@login_required
@revendedor_required
def panel():
    """Dashboard del revendedor"""
    # Estadisticas
    mis_remesas = Remesa.query.filter_by(revendedor_id=current_user.id)

    total_remesas = mis_remesas.count()
    pendientes = mis_remesas.filter_by(estado='pendiente').count()
    en_proceso = mis_remesas.filter_by(estado='en_proceso').count()
    entregadas = mis_remesas.filter_by(estado='entregada').count()

    # Montos
    total_enviado = db.session.query(func.sum(Remesa.monto_envio)).filter(
        Remesa.revendedor_id == current_user.id,
        Remesa.estado != 'cancelada'
    ).scalar() or 0

    total_comision_plataforma = db.session.query(func.sum(Remesa.comision_plataforma)).filter(
        Remesa.revendedor_id == current_user.id,
        Remesa.estado != 'cancelada'
    ).scalar() or 0

    # Ultimas remesas
    ultimas_remesas = mis_remesas.order_by(Remesa.fecha_creacion.desc()).limit(10).all()

    return render_template('revendedor/panel.html',
                         total_remesas=total_remesas,
                         pendientes=pendientes,
                         en_proceso=en_proceso,
                         entregadas=entregadas,
                         total_enviado=total_enviado,
                         total_comision_plataforma=total_comision_plataforma,
                         saldo_pendiente=current_user.saldo_pendiente,
                         comision=current_user.comision_revendedor,
                         usa_logistica=current_user.usa_logistica,
                         ultimas_remesas=ultimas_remesas)


@revendedor_bp.route('/nueva', methods=['GET', 'POST'])
@login_required
@revendedor_required
def nueva_remesa():
    """Crear nueva remesa como revendedor"""
    tasa_usd = TasaCambio.query.filter_by(moneda_origen='USD', activa=True).first()
    tasa_actual = tasa_usd.tasa if tasa_usd else 435

    if request.method == 'POST':
        remitente_nombre = request.form.get('remitente_nombre', '').strip()
        remitente_telefono = request.form.get('remitente_telefono', '').strip()
        beneficiario_nombre = request.form.get('beneficiario_nombre', '').strip()
        beneficiario_telefono = request.form.get('beneficiario_telefono', '').strip()
        beneficiario_direccion = request.form.get('beneficiario_direccion', '').strip()
        monto_envio = float(request.form.get('monto_envio', 0))
        tipo_entrega = request.form.get('tipo_entrega', 'MN')

        if not all([remitente_nombre, beneficiario_nombre, monto_envio]):
            flash('Complete todos los campos obligatorios', 'error')
            return render_template('revendedor/nueva.html', tasa_actual=tasa_actual)

        # Calcular montos
        if tipo_entrega == 'USD':
            # Para USD, el beneficiario recibe lo mismo (sin conversion)
            monto_entrega = monto_envio
            moneda_entrega = 'USD'
            tasa_aplicada = 1.0
        else:
            # Para MN, convertir a CUP
            tasa_aplicada = tasa_actual
            monto_entrega = monto_envio * tasa_aplicada
            moneda_entrega = 'CUP'

        # Comision de la plataforma (lo que cobra Happy Remesitas al revendedor)
        comision_plataforma = monto_envio * (current_user.comision_revendedor / 100)

        nueva = Remesa(
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
            comision_plataforma=comision_plataforma,
            total_cobrado=monto_envio,  # El revendedor cobra lo que quiera a su cliente
            estado='pendiente',
            creado_por=current_user.id,
            revendedor_id=current_user.id
        )

        db.session.add(nueva)

        # Actualizar saldo pendiente del revendedor
        if current_user.usa_logistica:
            # Usa logistica de Happy Remesitas: paga monto + comision
            total_a_pagar = monto_envio + comision_plataforma
            mensaje = f'Remesa {nueva.codigo} creada. Debes pagar: ${total_a_pagar:.2f} (${monto_envio:.2f} + ${comision_plataforma:.2f} comision)'
        else:
            # Solo usa plataforma: paga solo comision
            total_a_pagar = comision_plataforma
            mensaje = f'Remesa {nueva.codigo} creada. Comision plataforma: ${total_a_pagar:.2f}'

        current_user.saldo_pendiente += total_a_pagar
        db.session.commit()

        flash(mensaje, 'success')

        # Generar link de WhatsApp para notificar al admin
        resultado_admin = notificar_admin_nueva_remesa(nueva)
        if resultado_admin.get('link_manual'):
            flash(f'Notificar al Admin: <a href="{resultado_admin["link_manual"]}" target="_blank" class="btn btn-sm btn-success"><i class="fab fa-whatsapp"></i> Enviar WhatsApp</a>', 'whatsapp')

        # Link para notificar al beneficiario
        if beneficiario_telefono:
            msg_beneficiario = f"""*Remesa en Camino*

Hola {beneficiario_nombre},

Tiene una remesa pendiente:
Codigo: {nueva.codigo}
Monto: {nueva.monto_entrega:.2f} {nueva.moneda_entrega}
De: {remitente_nombre}

Pronto sera entregada."""
            link_beneficiario = generar_link_whatsapp(beneficiario_telefono, msg_beneficiario)
            flash(f'Notificar a {beneficiario_nombre}: <a href="{link_beneficiario}" target="_blank" class="btn btn-sm btn-success"><i class="fab fa-whatsapp"></i> WhatsApp</a>', 'whatsapp')

        return redirect(url_for('revendedor.panel'))

    return render_template('revendedor/nueva.html',
                         tasa_actual=tasa_actual,
                         comision=current_user.comision_revendedor,
                         usa_logistica=current_user.usa_logistica)


@revendedor_bp.route('/remesas')
@login_required
@revendedor_required
def mis_remesas():
    """Lista de remesas del revendedor"""
    estado_filtro = request.args.get('estado', '')

    query = Remesa.query.filter_by(revendedor_id=current_user.id)

    if estado_filtro:
        query = query.filter_by(estado=estado_filtro)

    remesas = query.order_by(Remesa.fecha_creacion.desc()).all()

    return render_template('revendedor/remesas.html',
                         remesas=remesas,
                         estado_filtro=estado_filtro)


@revendedor_bp.route('/remesa/<int:id>')
@login_required
@revendedor_required
def detalle_remesa(id):
    """Ver detalle de una remesa"""
    remesa = Remesa.query.get_or_404(id)

    # Verificar que pertenece al revendedor
    if remesa.revendedor_id != current_user.id:
        flash('No autorizado', 'error')
        return redirect(url_for('revendedor.panel'))

    return render_template('revendedor/detalle.html', remesa=remesa)


@revendedor_bp.route('/balance')
@login_required
@revendedor_required
def balance():
    """Ver balance y pagos del revendedor"""
    # Pagos realizados
    pagos = PagoRevendedor.query.filter_by(revendedor_id=current_user.id).order_by(
        PagoRevendedor.fecha.desc()
    ).all()

    total_pagado = db.session.query(func.sum(PagoRevendedor.monto)).filter(
        PagoRevendedor.revendedor_id == current_user.id
    ).scalar() or 0

    # Comisiones generadas
    total_comisiones = db.session.query(func.sum(Remesa.comision_plataforma)).filter(
        Remesa.revendedor_id == current_user.id,
        Remesa.estado != 'cancelada'
    ).scalar() or 0

    return render_template('revendedor/balance.html',
                         pagos=pagos,
                         total_pagado=total_pagado,
                         total_comisiones=total_comisiones,
                         saldo_pendiente=current_user.saldo_pendiente)


@revendedor_bp.route('/api/calcular', methods=['POST'])
@login_required
@revendedor_required
def api_calcular():
    """API para calcular monto a entregar"""
    data = request.get_json()
    monto = float(data.get('monto', 0))
    tipo = data.get('tipo', 'MN')

    tasa_usd = TasaCambio.query.filter_by(moneda_origen='USD', activa=True).first()
    tasa_actual = tasa_usd.tasa if tasa_usd else 435

    if tipo == 'USD':
        entrega = monto
        moneda = 'USD'
    else:
        entrega = monto * tasa_actual
        moneda = 'CUP'

    comision_plataforma = monto * (current_user.comision_revendedor / 100)

    return jsonify({
        'monto_entrega': round(entrega, 2),
        'moneda': moneda,
        'tasa': tasa_actual,
        'comision_plataforma': round(comision_plataforma, 2),
        'porcentaje_comision': current_user.comision_revendedor
    })
