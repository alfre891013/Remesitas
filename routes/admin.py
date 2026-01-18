from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from models import db, Usuario, TasaCambio, Comision, Configuracion, MovimientoEfectivo
from functools import wraps
from datetime import datetime
from tasas_externas import obtener_tasa_actual as obtener_tasa_externa

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.es_admin():
            flash('No tienes permiso para acceder a esta pagina', 'error')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function


# === USUARIOS ===

@admin_bp.route('/usuarios')
@login_required
@admin_required
def usuarios():
    usuarios = Usuario.query.order_by(Usuario.fecha_creacion.desc()).all()
    return render_template('admin/usuarios.html', usuarios=usuarios)


@admin_bp.route('/usuarios/nuevo', methods=['GET', 'POST'])
@login_required
@admin_required
def usuario_nuevo():
    if request.method == 'POST':
        username = request.form.get('username')
        nombre = request.form.get('nombre')
        password = request.form.get('password')
        rol = request.form.get('rol')
        telefono = request.form.get('telefono')

        if Usuario.query.filter_by(username=username).first():
            flash('El nombre de usuario ya existe', 'error')
        else:
            usuario = Usuario(
                username=username,
                nombre=nombre,
                rol=rol,
                telefono=telefono
            )
            usuario.set_password(password)
            db.session.add(usuario)
            db.session.commit()
            flash(f'Usuario {username} creado exitosamente', 'success')
            return redirect(url_for('admin.usuarios'))

    return render_template('admin/usuario_form.html', usuario=None)


@admin_bp.route('/usuarios/<int:id>/editar', methods=['GET', 'POST'])
@login_required
@admin_required
def usuario_editar(id):
    usuario = Usuario.query.get_or_404(id)

    if request.method == 'POST':
        usuario.nombre = request.form.get('nombre')
        usuario.rol = request.form.get('rol')
        usuario.telefono = request.form.get('telefono')
        usuario.activo = 'activo' in request.form

        password = request.form.get('password')
        if password:
            usuario.set_password(password)

        db.session.commit()
        flash('Usuario actualizado exitosamente', 'success')
        return redirect(url_for('admin.usuarios'))

    return render_template('admin/usuario_form.html', usuario=usuario)


@admin_bp.route('/usuarios/<int:id>/toggle', methods=['POST'])
@login_required
@admin_required
def usuario_toggle(id):
    usuario = Usuario.query.get_or_404(id)
    if usuario.id == current_user.id:
        flash('No puedes desactivarte a ti mismo', 'error')
    else:
        usuario.activo = not usuario.activo
        db.session.commit()
        estado = 'activado' if usuario.activo else 'desactivado'
        flash(f'Usuario {estado}', 'success')
    return redirect(url_for('admin.usuarios'))


@admin_bp.route('/usuarios/<int:id>/reset-password', methods=['POST'])
@login_required
@admin_required
def usuario_reset_password(id):
    usuario = Usuario.query.get_or_404(id)
    usuario.set_password('123456')
    usuario.debe_cambiar_password = True
    db.session.commit()
    flash(f'Contrasena de {usuario.nombre} restablecida a: 123456', 'success')
    return redirect(url_for('admin.usuarios'))


@admin_bp.route('/usuarios/<int:id>/eliminar', methods=['POST'])
@login_required
@admin_required
def usuario_eliminar(id):
    usuario = Usuario.query.get_or_404(id)
    if usuario.id == current_user.id:
        flash('No puedes eliminarte a ti mismo', 'error')
        return redirect(url_for('admin.usuarios'))

    from models import Remesa
    remesas = Remesa.query.filter_by(repartidor_id=id).count()
    if remesas > 0:
        flash(f'No se puede eliminar: {usuario.nombre} tiene {remesas} remesas asignadas', 'error')
        return redirect(url_for('admin.usuarios'))

    nombre = usuario.nombre
    db.session.delete(usuario)
    db.session.commit()
    flash(f'Usuario {nombre} eliminado', 'success')
    return redirect(url_for('admin.usuarios'))


# === TASAS DE CAMBIO ===

@admin_bp.route('/tasas')
@login_required
@admin_required
def tasas():
    tasas = TasaCambio.query.order_by(TasaCambio.fecha_actualizacion.desc()).limit(20).all()

    # Obtener las 3 tasas activas
    tasa_usd = TasaCambio.query.filter_by(moneda_origen='USD', activa=True).first()
    tasa_eur = TasaCambio.query.filter_by(moneda_origen='EUR', activa=True).first()
    tasa_mlc = TasaCambio.query.filter_by(moneda_origen='MLC', activa=True).first()

    return render_template('admin/tasas.html',
        tasas=tasas,
        tasa_usd=tasa_usd.tasa if tasa_usd else 435,
        tasa_eur=tasa_eur.tasa if tasa_eur else 455,
        tasa_mlc=tasa_mlc.tasa if tasa_mlc else 305
    )


@admin_bp.route('/tasas/nueva', methods=['POST'])
@login_required
@admin_required
def tasa_nueva():
    tasa_valor = float(request.form.get('tasa', 0))
    moneda_destino = request.form.get('moneda_destino', 'LOCAL')

    if tasa_valor <= 0:
        flash('La tasa debe ser mayor a 0', 'error')
    else:
        # Desactivar tasas anteriores de la misma moneda
        TasaCambio.query.filter_by(
            moneda_destino=moneda_destino,
            activa=True
        ).update({'activa': False})

        tasa = TasaCambio(
            moneda_origen='USD',
            moneda_destino=moneda_destino,
            tasa=tasa_valor,
            activa=True
        )
        db.session.add(tasa)
        db.session.commit()
        flash(f'Tasa actualizada: 1 USD = {tasa_valor} {moneda_destino}', 'success')

    return redirect(url_for('admin.tasas'))


@admin_bp.route('/tasas/actualizar-todas', methods=['POST'])
@login_required
@admin_required
def tasas_actualizar_todas():
    """Actualiza las 3 tasas (USD, EUR, MLC) manualmente"""
    tasa_usd = float(request.form.get('tasa_usd', 0))
    tasa_eur = float(request.form.get('tasa_eur', 0))
    tasa_mlc = float(request.form.get('tasa_mlc', 0))

    for moneda, valor in [('USD', tasa_usd), ('EUR', tasa_eur), ('MLC', tasa_mlc)]:
        if valor > 0:
            TasaCambio.query.filter_by(moneda_origen=moneda, activa=True).update({'activa': False})
            tasa = TasaCambio(moneda_origen=moneda, moneda_destino='CUP', tasa=valor, activa=True)
            db.session.add(tasa)

    db.session.commit()
    flash('Tasas actualizadas correctamente', 'success')
    return redirect(url_for('admin.tasas'))


@admin_bp.route('/tasas/sincronizar', methods=['POST'])
@login_required
@admin_required
def tasa_sincronizar():
    """Obtiene la tasa de cambio desde El Toque automaticamente"""
    tasa_externa = obtener_tasa_externa()

    if tasa_externa and 'USD' in tasa_externa:
        tasa_valor = tasa_externa['USD']
        fuente = tasa_externa.get('fuente', 'Externa')

        # Desactivar tasas anteriores
        TasaCambio.query.filter_by(
            moneda_destino='CUP',
            activa=True
        ).update({'activa': False})

        tasa = TasaCambio(
            moneda_origen='USD',
            moneda_destino='CUP',
            tasa=tasa_valor,
            activa=True
        )
        db.session.add(tasa)
        db.session.commit()

        flash(f'Tasa sincronizada desde {fuente}: 1 USD = {tasa_valor} CUP', 'success')
    else:
        flash('No se pudo obtener la tasa. Intenta mas tarde o ingresala manualmente.', 'error')

    return redirect(url_for('admin.tasas'))


@admin_bp.route('/api/tasa-externa')
@login_required
@admin_required
def api_tasa_externa():
    """API para obtener la tasa externa sin guardarla"""
    tasa = obtener_tasa_externa()
    if tasa:
        return jsonify(tasa)
    return jsonify({'error': 'No se pudo obtener la tasa'}), 503


# === COMISIONES ===

@admin_bp.route('/comisiones')
@login_required
@admin_required
def comisiones():
    comisiones = Comision.query.order_by(Comision.rango_minimo).all()
    return render_template('admin/comisiones.html', comisiones=comisiones)


@admin_bp.route('/comisiones/nueva', methods=['GET', 'POST'])
@login_required
@admin_required
def comision_nueva():
    if request.method == 'POST':
        comision = Comision(
            nombre=request.form.get('nombre'),
            rango_minimo=float(request.form.get('rango_minimo', 0)),
            rango_maximo=float(request.form.get('rango_maximo')) if request.form.get('rango_maximo') else None,
            porcentaje=float(request.form.get('porcentaje', 0)),
            monto_fijo=float(request.form.get('monto_fijo', 0)),
            activa='activa' in request.form
        )
        db.session.add(comision)
        db.session.commit()
        flash('Comision creada exitosamente', 'success')
        return redirect(url_for('admin.comisiones'))

    return render_template('admin/comision_form.html', comision=None)


@admin_bp.route('/comisiones/<int:id>/editar', methods=['GET', 'POST'])
@login_required
@admin_required
def comision_editar(id):
    comision = Comision.query.get_or_404(id)

    if request.method == 'POST':
        comision.nombre = request.form.get('nombre')
        comision.rango_minimo = float(request.form.get('rango_minimo', 0))
        comision.rango_maximo = float(request.form.get('rango_maximo')) if request.form.get('rango_maximo') else None
        comision.porcentaje = float(request.form.get('porcentaje', 0))
        comision.monto_fijo = float(request.form.get('monto_fijo', 0))
        comision.activa = 'activa' in request.form
        db.session.commit()
        flash('Comision actualizada', 'success')
        return redirect(url_for('admin.comisiones'))

    return render_template('admin/comision_form.html', comision=comision)


@admin_bp.route('/comisiones/<int:id>/eliminar', methods=['POST'])
@login_required
@admin_required
def comision_eliminar(id):
    comision = Comision.query.get_or_404(id)
    db.session.delete(comision)
    db.session.commit()
    flash('Comision eliminada', 'success')
    return redirect(url_for('admin.comisiones'))


# === SOLICITUDES DE CLIENTES ===

@admin_bp.route('/solicitudes')
@login_required
@admin_required
def solicitudes():
    """Lista las solicitudes de remesas pendientes de aprobacion"""
    from models import Remesa
    solicitudes = Remesa.query.filter_by(es_solicitud=True, estado='solicitud').order_by(
        Remesa.fecha_creacion.desc()
    ).all()
    return render_template('admin/solicitudes.html', solicitudes=solicitudes)


@admin_bp.route('/solicitudes/<int:id>')
@login_required
@admin_required
def solicitud_detalle(id):
    """Ver detalle de una solicitud para editar antes de aprobar"""
    from models import Remesa
    solicitud = Remesa.query.get_or_404(id)
    repartidores = Usuario.query.filter_by(rol='repartidor', activo=True).all()
    tasa_usd = TasaCambio.query.filter_by(moneda_origen='USD', activa=True).first()
    return render_template('admin/solicitud_detalle.html',
                         solicitud=solicitud,
                         repartidores=repartidores,
                         tasa_actual=tasa_usd.tasa if tasa_usd else 435)


@admin_bp.route('/solicitudes/<int:id>/aprobar', methods=['POST'])
@login_required
@admin_required
def solicitud_aprobar(id):
    """Aprueba una solicitud, opcionalmente editando montos"""
    from models import Remesa
    from notificaciones import enviar_whatsapp

    solicitud = Remesa.query.get_or_404(id)

    # Actualizar datos si fueron editados
    solicitud.monto_envio = float(request.form.get('monto_envio', solicitud.monto_envio))
    solicitud.monto_entrega = float(request.form.get('monto_entrega', solicitud.monto_entrega))
    solicitud.beneficiario_direccion = request.form.get('beneficiario_direccion', solicitud.beneficiario_direccion)

    repartidor_id = request.form.get('repartidor_id')
    if repartidor_id:
        solicitud.repartidor_id = int(repartidor_id)

    # Cambiar estado
    solicitud.estado = 'pendiente'
    solicitud.fecha_aprobacion = datetime.now()

    db.session.commit()

    # Notificar al remitente
    if solicitud.remitente_telefono:
        mensaje = f"""*SOLICITUD APROBADA*

Hola {solicitud.remitente_nombre},

Tu solicitud de remesa ha sido aprobada!

Codigo: {solicitud.codigo}
Monto a enviar: ${solicitud.monto_envio} USD
Beneficiario recibira: ${solicitud.monto_entrega:,.2f} {solicitud.moneda_entrega}

Por favor envia ${solicitud.monto_envio} USD a:
Zelle: 7865359229
(Sin notas ni comentarios)

Cuando envies, responde este mensaje con la confirmacion.

Happy Remesitas"""
        enviar_whatsapp(solicitud.remitente_telefono, mensaje)

    flash(f'Solicitud {solicitud.codigo} aprobada', 'success')
    return redirect(url_for('admin.solicitudes'))


@admin_bp.route('/solicitudes/<int:id>/rechazar', methods=['POST'])
@login_required
@admin_required
def solicitud_rechazar(id):
    """Rechaza una solicitud"""
    from models import Remesa
    from notificaciones import enviar_whatsapp

    solicitud = Remesa.query.get_or_404(id)
    motivo = request.form.get('motivo', 'No especificado')

    solicitud.estado = 'cancelada'
    solicitud.notas = f'Rechazada: {motivo}'
    db.session.commit()

    # Notificar al remitente
    if solicitud.remitente_telefono:
        mensaje = f"""*SOLICITUD NO APROBADA*

Hola {solicitud.remitente_nombre},

Tu solicitud de remesa {solicitud.codigo} no pudo ser procesada.

Motivo: {motivo}

Contactanos para mas informacion.

Happy Remesitas"""
        enviar_whatsapp(solicitud.remitente_telefono, mensaje)

    flash(f'Solicitud {solicitud.codigo} rechazada', 'info')
    return redirect(url_for('admin.solicitudes'))


# === REVENDEDORES ===

@admin_bp.route('/revendedores')
@login_required
@admin_required
def revendedores():
    """Lista todos los revendedores"""
    from models import Remesa
    from sqlalchemy import func

    revendedores = Usuario.query.filter_by(rol='revendedor').order_by(Usuario.nombre).all()

    # Calcular estadisticas por revendedor
    stats = {}
    for r in revendedores:
        total_remesas = Remesa.query.filter_by(revendedor_id=r.id).count()
        total_enviado = db.session.query(func.sum(Remesa.monto_envio)).filter(
            Remesa.revendedor_id == r.id,
            Remesa.estado != 'cancelada'
        ).scalar() or 0
        stats[r.id] = {
            'total_remesas': total_remesas,
            'total_enviado': total_enviado
        }

    return render_template('admin/revendedores.html', revendedores=revendedores, stats=stats)


@admin_bp.route('/revendedores/nuevo', methods=['GET', 'POST'])
@login_required
@admin_required
def revendedor_nuevo():
    """Crear nuevo revendedor"""
    if request.method == 'POST':
        username = request.form.get('username')
        nombre = request.form.get('nombre')
        password = request.form.get('password')
        telefono = request.form.get('telefono')
        comision = float(request.form.get('comision', 2.0))
        usa_logistica = request.form.get('usa_logistica') == '1'

        if Usuario.query.filter_by(username=username).first():
            flash('El nombre de usuario ya existe', 'error')
        else:
            usuario = Usuario(
                username=username,
                nombre=nombre,
                rol='revendedor',
                telefono=telefono,
                comision_revendedor=comision,
                usa_logistica=usa_logistica
            )
            usuario.set_password(password)
            db.session.add(usuario)
            db.session.commit()
            flash(f'Revendedor {nombre} creado con comision {comision}%', 'success')
            return redirect(url_for('admin.revendedores'))

    return render_template('admin/revendedor_form.html', revendedor=None)


@admin_bp.route('/revendedores/<int:id>/editar', methods=['GET', 'POST'])
@login_required
@admin_required
def revendedor_editar(id):
    """Editar revendedor"""
    revendedor = Usuario.query.get_or_404(id)

    if request.method == 'POST':
        revendedor.nombre = request.form.get('nombre')
        revendedor.telefono = request.form.get('telefono')
        revendedor.comision_revendedor = float(request.form.get('comision', 2.0))
        revendedor.usa_logistica = request.form.get('usa_logistica') == '1'
        revendedor.activo = 'activo' in request.form

        password = request.form.get('password')
        if password:
            revendedor.set_password(password)

        db.session.commit()
        flash('Revendedor actualizado', 'success')
        return redirect(url_for('admin.revendedores'))

    return render_template('admin/revendedor_form.html', revendedor=revendedor)


@admin_bp.route('/revendedores/<int:id>/balance')
@login_required
@admin_required
def revendedor_balance(id):
    """Ver balance y pagos de un revendedor"""
    from models import Remesa, PagoRevendedor
    from sqlalchemy import func

    revendedor = Usuario.query.get_or_404(id)

    # Pagos realizados
    pagos = PagoRevendedor.query.filter_by(revendedor_id=id).order_by(
        PagoRevendedor.fecha.desc()
    ).all()

    total_pagado = db.session.query(func.sum(PagoRevendedor.monto)).filter(
        PagoRevendedor.revendedor_id == id
    ).scalar() or 0

    # Comisiones generadas
    total_comisiones = db.session.query(func.sum(Remesa.comision_plataforma)).filter(
        Remesa.revendedor_id == id,
        Remesa.estado != 'cancelada'
    ).scalar() or 0

    # Remesas del revendedor
    remesas = Remesa.query.filter_by(revendedor_id=id).order_by(
        Remesa.fecha_creacion.desc()
    ).limit(20).all()

    return render_template('admin/revendedor_balance.html',
                         revendedor=revendedor,
                         pagos=pagos,
                         total_pagado=total_pagado,
                         total_comisiones=total_comisiones,
                         remesas=remesas)


@admin_bp.route('/revendedores/<int:id>/pago', methods=['POST'])
@login_required
@admin_required
def revendedor_registrar_pago(id):
    """Registrar pago de un revendedor"""
    from models import PagoRevendedor

    revendedor = Usuario.query.get_or_404(id)
    monto = float(request.form.get('monto', 0))
    metodo = request.form.get('metodo_pago', '')
    referencia = request.form.get('referencia', '')
    notas = request.form.get('notas', '')

    if monto <= 0:
        flash('El monto debe ser mayor a 0', 'error')
        return redirect(url_for('admin.revendedor_balance', id=id))

    pago = PagoRevendedor(
        revendedor_id=id,
        monto=monto,
        metodo_pago=metodo,
        referencia=referencia,
        notas=notas,
        registrado_por=current_user.id
    )
    db.session.add(pago)

    # Actualizar saldo pendiente
    revendedor.saldo_pendiente = max(0, revendedor.saldo_pendiente - monto)
    db.session.commit()

    flash(f'Pago de ${monto:.2f} registrado. Nuevo saldo: ${revendedor.saldo_pendiente:.2f}', 'success')
    return redirect(url_for('admin.revendedor_balance', id=id))


@admin_bp.route('/revendedores/<int:id>/toggle', methods=['POST'])
@login_required
@admin_required
def revendedor_toggle(id):
    """Activa o desactiva un revendedor"""
    revendedor = Usuario.query.get_or_404(id)
    revendedor.activo = not revendedor.activo
    db.session.commit()
    
    estado = 'activado' if revendedor.activo else 'desactivado'
    flash(f'Revendedor {revendedor.nombre} {estado}', 'success')
    return redirect(url_for('admin.revendedores'))


@admin_bp.route('/revendedores/<int:id>/reset-password', methods=['POST'])
@login_required
@admin_required
def revendedor_reset_password(id):
    """Restablece la clave de un revendedor a 123456"""
    revendedor = Usuario.query.get_or_404(id)
    revendedor.set_password('123456')
    revendedor.debe_cambiar_password = True
    db.session.commit()
    
    flash(f'Clave de {revendedor.nombre} restablecida a: 123456', 'success')
    return redirect(url_for('admin.revendedores'))


@admin_bp.route('/revendedores/<int:id>/eliminar', methods=['POST'])
@login_required
@admin_required
def revendedor_eliminar(id):
    """Elimina un revendedor"""
    from models import Remesa

    revendedor = Usuario.query.get_or_404(id)

    # Verificar si tiene remesas asociadas
    remesas = Remesa.query.filter_by(revendedor_id=id).count()
    if remesas > 0:
        flash(f'No se puede eliminar: {revendedor.nombre} tiene {remesas} remesas asociadas. Desactivalo en su lugar.', 'error')
        return redirect(url_for('admin.revendedores'))

    nombre = revendedor.nombre
    db.session.delete(revendedor)
    db.session.commit()

    flash(f'Revendedor {nombre} eliminado', 'success')
    return redirect(url_for('admin.revendedores'))


# === CONTROL DE EFECTIVO REPARTIDORES ===

@admin_bp.route('/efectivo')
@login_required
@admin_required
def efectivo():
    """Panel de control de efectivo de repartidores"""
    repartidores = Usuario.query.filter_by(rol='repartidor', activo=True).order_by(Usuario.nombre).all()

    # Calcular totales
    total_usd = sum(r.saldo_usd or 0 for r in repartidores)
    total_cup = sum(r.saldo_cup or 0 for r in repartidores)

    return render_template('admin/efectivo.html',
                         repartidores=repartidores,
                         total_usd=total_usd,
                         total_cup=total_cup)


@admin_bp.route('/efectivo/<int:id>')
@login_required
@admin_required
def efectivo_repartidor(id):
    """Ver detalle de efectivo de un repartidor"""
    repartidor = Usuario.query.get_or_404(id)

    # Ultimos movimientos
    movimientos = MovimientoEfectivo.query.filter_by(
        repartidor_id=id
    ).order_by(MovimientoEfectivo.fecha.desc()).limit(50).all()

    return render_template('admin/efectivo_detalle.html',
                         repartidor=repartidor,
                         movimientos=movimientos)


@admin_bp.route('/efectivo/<int:id>/asignar', methods=['POST'])
@login_required
@admin_required
def efectivo_asignar(id):
    """Asignar efectivo a un repartidor"""
    repartidor = Usuario.query.get_or_404(id)

    moneda = request.form.get('moneda', 'USD')
    monto = float(request.form.get('monto', 0))
    notas = request.form.get('notas', '')

    if monto <= 0:
        flash('El monto debe ser mayor a 0', 'error')
        return redirect(url_for('admin.efectivo_repartidor', id=id))

    # Obtener saldo actual
    if moneda == 'USD':
        saldo_anterior = repartidor.saldo_usd or 0
        repartidor.saldo_usd = saldo_anterior + monto
        saldo_nuevo = repartidor.saldo_usd
    else:
        saldo_anterior = repartidor.saldo_cup or 0
        repartidor.saldo_cup = saldo_anterior + monto
        saldo_nuevo = repartidor.saldo_cup

    # Registrar movimiento
    movimiento = MovimientoEfectivo(
        repartidor_id=id,
        tipo='asignacion',
        moneda=moneda,
        monto=monto,
        saldo_anterior=saldo_anterior,
        saldo_nuevo=saldo_nuevo,
        notas=notas,
        registrado_por=current_user.id
    )
    db.session.add(movimiento)
    db.session.commit()

    flash(f'Asignado ${monto:,.2f} {moneda} a {repartidor.nombre}. Nuevo saldo: ${saldo_nuevo:,.2f} {moneda}', 'success')
    return redirect(url_for('admin.efectivo_repartidor', id=id))


@admin_bp.route('/efectivo/<int:id>/retirar', methods=['POST'])
@login_required
@admin_required
def efectivo_retirar(id):
    """Retirar efectivo de un repartidor"""
    repartidor = Usuario.query.get_or_404(id)

    moneda = request.form.get('moneda', 'USD')
    monto = float(request.form.get('monto', 0))
    notas = request.form.get('notas', '')

    if monto <= 0:
        flash('El monto debe ser mayor a 0', 'error')
        return redirect(url_for('admin.efectivo_repartidor', id=id))

    # Obtener saldo actual y verificar
    if moneda == 'USD':
        saldo_anterior = repartidor.saldo_usd or 0
        if monto > saldo_anterior:
            flash(f'No tiene suficiente saldo USD. Disponible: ${saldo_anterior:,.2f}', 'error')
            return redirect(url_for('admin.efectivo_repartidor', id=id))
        repartidor.saldo_usd = saldo_anterior - monto
        saldo_nuevo = repartidor.saldo_usd
    else:
        saldo_anterior = repartidor.saldo_cup or 0
        if monto > saldo_anterior:
            flash(f'No tiene suficiente saldo CUP. Disponible: ${saldo_anterior:,.2f}', 'error')
            return redirect(url_for('admin.efectivo_repartidor', id=id))
        repartidor.saldo_cup = saldo_anterior - monto
        saldo_nuevo = repartidor.saldo_cup

    # Registrar movimiento
    movimiento = MovimientoEfectivo(
        repartidor_id=id,
        tipo='retiro',
        moneda=moneda,
        monto=monto,
        saldo_anterior=saldo_anterior,
        saldo_nuevo=saldo_nuevo,
        notas=notas,
        registrado_por=current_user.id
    )
    db.session.add(movimiento)
    db.session.commit()

    flash(f'Retirado ${monto:,.2f} {moneda} de {repartidor.nombre}. Nuevo saldo: ${saldo_nuevo:,.2f} {moneda}', 'success')
    return redirect(url_for('admin.efectivo_repartidor', id=id))


@admin_bp.route('/efectivo/<int:id>/venta-usd', methods=['POST'])
@login_required
@admin_required
def efectivo_venta_usd(id):
    """Registrar venta de USD (convierte USD a CUP)"""
    repartidor = Usuario.query.get_or_404(id)

    monto_usd = float(request.form.get('monto_usd', 0))
    tasa = float(request.form.get('tasa', 0))
    notas = request.form.get('notas', '')

    if monto_usd <= 0 or tasa <= 0:
        flash('El monto y la tasa deben ser mayores a 0', 'error')
        return redirect(url_for('admin.efectivo_repartidor', id=id))

    saldo_usd_anterior = repartidor.saldo_usd or 0
    if monto_usd > saldo_usd_anterior:
        flash(f'No tiene suficiente USD. Disponible: ${saldo_usd_anterior:,.2f}', 'error')
        return redirect(url_for('admin.efectivo_repartidor', id=id))

    monto_cup = monto_usd * tasa
    saldo_cup_anterior = repartidor.saldo_cup or 0

    # Actualizar saldos
    repartidor.saldo_usd = saldo_usd_anterior - monto_usd
    repartidor.saldo_cup = saldo_cup_anterior + monto_cup

    # Registrar movimiento USD (salida)
    mov_usd = MovimientoEfectivo(
        repartidor_id=id,
        tipo='venta_usd',
        moneda='USD',
        monto=monto_usd,
        saldo_anterior=saldo_usd_anterior,
        saldo_nuevo=repartidor.saldo_usd,
        tasa_cambio=tasa,
        notas=f'Venta USD a {tasa} CUP. {notas}',
        registrado_por=current_user.id
    )

    # Registrar movimiento CUP (entrada)
    mov_cup = MovimientoEfectivo(
        repartidor_id=id,
        tipo='venta_usd',
        moneda='CUP',
        monto=monto_cup,
        saldo_anterior=saldo_cup_anterior,
        saldo_nuevo=repartidor.saldo_cup,
        tasa_cambio=tasa,
        notas=f'Venta de ${monto_usd} USD a {tasa}. {notas}',
        registrado_por=current_user.id
    )

    db.session.add(mov_usd)
    db.session.add(mov_cup)
    db.session.commit()

    flash(f'Venta registrada: ${monto_usd:,.2f} USD = ${monto_cup:,.2f} CUP (tasa {tasa})', 'success')
    return redirect(url_for('admin.efectivo_repartidor', id=id))


@admin_bp.route('/efectivo/<int:id>/recogida', methods=['POST'])
@login_required
@admin_required
def efectivo_recogida(id):
    """Registrar recogida de dinero (suma al saldo del repartidor)"""
    repartidor = Usuario.query.get_or_404(id)

    moneda = request.form.get('moneda', 'USD')
    monto = float(request.form.get('monto', 0))
    notas = request.form.get('notas', '')

    if monto <= 0:
        flash('El monto debe ser mayor a 0', 'error')
        return redirect(url_for('admin.efectivo_repartidor', id=id))

    # Sumar al saldo
    if moneda == 'USD':
        saldo_anterior = repartidor.saldo_usd or 0
        repartidor.saldo_usd = saldo_anterior + monto
        saldo_nuevo = repartidor.saldo_usd
    else:
        saldo_anterior = repartidor.saldo_cup or 0
        repartidor.saldo_cup = saldo_anterior + monto
        saldo_nuevo = repartidor.saldo_cup

    # Registrar movimiento
    movimiento = MovimientoEfectivo(
        repartidor_id=id,
        tipo='recogida',
        moneda=moneda,
        monto=monto,
        saldo_anterior=saldo_anterior,
        saldo_nuevo=saldo_nuevo,
        notas=notas,
        registrado_por=current_user.id
    )
    db.session.add(movimiento)
    db.session.commit()

    flash(f'Recogida registrada: +${monto:,.2f} {moneda}. Nuevo saldo: ${saldo_nuevo:,.2f} {moneda}', 'success')
    return redirect(url_for('admin.efectivo_repartidor', id=id))


# === ELIMINACION DE REMESAS ===

@admin_bp.route('/remesa/<codigo>/eliminar', methods=['POST'])
@login_required
@admin_required
def remesa_eliminar(codigo):
    """
    Elimina una remesa y todos sus registros relacionados.
    Usar con cuidado - para remesas procesadas por error.
    """
    from models import Remesa, MovimientoContable

    remesa = Remesa.query.filter_by(codigo=codigo).first()

    if not remesa:
        flash(f'Remesa {codigo} no encontrada', 'error')
        return redirect(url_for('remesas.dashboard'))

    # Guardar info para el mensaje
    beneficiario = remesa.beneficiario_nombre
    monto = remesa.monto_envio

    # Eliminar movimientos contables relacionados
    MovimientoContable.query.filter_by(remesa_id=remesa.id).delete()

    # Eliminar movimientos de efectivo relacionados
    MovimientoEfectivo.query.filter_by(remesa_id=remesa.id).delete()

    # Eliminar la remesa
    db.session.delete(remesa)
    db.session.commit()

    flash(f'Remesa {codigo} eliminada (Beneficiario: {beneficiario}, Monto: ${monto:.2f})', 'success')
    return redirect(url_for('remesas.dashboard'))


@admin_bp.route('/remesas/eliminar-multiple', methods=['POST'])
@login_required
@admin_required
def remesas_eliminar_multiple():
    """
    Elimina multiples remesas por codigo.
    Espera JSON: {"codigos": ["REM-XXX", "REM-YYY"]}
    """
    from models import Remesa, MovimientoContable

    data = request.get_json()
    if not data or 'codigos' not in data:
        return jsonify({'error': 'Se requiere lista de codigos'}), 400

    codigos = data['codigos']
    eliminadas = []
    no_encontradas = []

    for codigo in codigos:
        remesa = Remesa.query.filter_by(codigo=codigo).first()
        if not remesa:
            no_encontradas.append(codigo)
            continue

        # Eliminar registros relacionados
        MovimientoContable.query.filter_by(remesa_id=remesa.id).delete()
        MovimientoEfectivo.query.filter_by(remesa_id=remesa.id).delete()

        db.session.delete(remesa)
        eliminadas.append(codigo)

    db.session.commit()

    return jsonify({
        'eliminadas': eliminadas,
        'no_encontradas': no_encontradas,
        'mensaje': f'Eliminadas {len(eliminadas)} remesas'
    })
