from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from models import db, Remesa, Usuario, TasaCambio, Comision, MovimientoContable, MovimientoEfectivo
from datetime import datetime, timedelta
from functools import wraps
from notificaciones import (
    notificar_nueva_remesa, notificar_remitente, notificar_beneficiario,
    notificar_entrega_admin, notificar_entrega_remitente, generar_link_whatsapp,
    notificar_admin_nueva_remesa, notificar_admin_cambio_estado,
    obtener_links_notificacion_remesa
)
from push_notifications import (
    push_nueva_remesa_admin, push_remesa_asignada, push_remesa_entregada_admin
)

remesas_bp = Blueprint('remesas', __name__)


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.es_admin():
            flash('No tienes permiso para acceder a esta pagina', 'error')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function


@remesas_bp.route('/dashboard')
@login_required
@admin_required
def dashboard():
    hoy = datetime.utcnow().date()
    inicio_semana = hoy - timedelta(days=hoy.weekday())
    inicio_mes = hoy.replace(day=1)

    total_remesas = Remesa.query.count()
    remesas_pendientes = Remesa.query.filter_by(estado='pendiente').count()
    remesas_hoy = Remesa.query.filter(
        db.func.date(Remesa.fecha_creacion) == hoy
    ).count()

    ingresos_mes = db.session.query(
        db.func.sum(Remesa.total_comision)
    ).filter(
        Remesa.fecha_creacion >= inicio_mes,
        Remesa.estado != 'cancelada'
    ).scalar() or 0

    total_movido_hoy = db.session.query(
        db.func.sum(Remesa.monto_envio)
    ).filter(
        db.func.date(Remesa.fecha_creacion) == hoy,
        Remesa.estado != 'cancelada'
    ).scalar() or 0

    ultimas_remesas = Remesa.query.order_by(
        Remesa.fecha_creacion.desc()
    ).limit(10).all()

    tasa_actual = TasaCambio.obtener_tasa_actual()

    # Estadisticas de pagos
    remesas_sin_pagar = Remesa.query.filter_by(facturada=False, estado='entregada').count()
    monto_sin_pagar = db.session.query(
        db.func.sum(Remesa.total_cobrado)
    ).filter(
        Remesa.facturada == False,
        Remesa.estado == 'entregada'
    ).scalar() or 0

    remesas_pagadas_mes = Remesa.query.filter(
        Remesa.facturada == True,
        Remesa.fecha_facturacion >= inicio_mes
    ).count()
    monto_pagado_mes = db.session.query(
        db.func.sum(Remesa.total_cobrado)
    ).filter(
        Remesa.facturada == True,
        Remesa.fecha_facturacion >= inicio_mes
    ).scalar() or 0

    # Alertas
    hace_24h = datetime.utcnow() - timedelta(hours=24)
    alertas = {
        'sin_pagar': remesas_sin_pagar,
        'sin_entregar_24h': Remesa.query.filter(
            Remesa.estado.in_(['pendiente', 'en_proceso']),
            Remesa.fecha_creacion < hace_24h
        ).count()
    }

    # Solicitudes pendientes de aprobacion
    solicitudes_pendientes = Remesa.query.filter_by(
        estado='solicitud',
        es_solicitud=True
    ).order_by(Remesa.fecha_creacion.desc()).all()

    # Generar links de WhatsApp para solicitudes
    from notificaciones import generar_link_whatsapp
    for sol in solicitudes_pendientes:
        if sol.remitente_telefono:
            msg = f"""Hola {sol.remitente_nombre},

Recibimos tu solicitud de remesa {sol.codigo}.

Beneficiario: {sol.beneficiario_nombre}
Monto: ${sol.monto_envio:.2f} USD

Te contactamos para confirmar los detalles."""
            sol.link_whatsapp_remitente = generar_link_whatsapp(sol.remitente_telefono, msg)

    return render_template('dashboard.html',
        total_remesas=total_remesas,
        remesas_pendientes=remesas_pendientes,
        remesas_hoy=remesas_hoy,
        ingresos_mes=ingresos_mes,
        total_movido_hoy=total_movido_hoy,
        ultimas_remesas=ultimas_remesas,
        tasa_actual=tasa_actual,
        remesas_sin_pagar=remesas_sin_pagar,
        monto_sin_pagar=monto_sin_pagar,
        remesas_pagadas_mes=remesas_pagadas_mes,
        monto_pagado_mes=monto_pagado_mes,
        alertas=alertas,
        solicitudes_pendientes=solicitudes_pendientes
    )


@remesas_bp.route('/remesas')
@login_required
@admin_required
def lista():
    estado = request.args.get('estado', '')
    buscar = request.args.get('buscar', '')
    facturada = request.args.get('facturada', '')

    query = Remesa.query

    if estado:
        query = query.filter_by(estado=estado)
    if buscar:
        query = query.filter(
            db.or_(
                Remesa.codigo.contains(buscar),
                Remesa.remitente_nombre.contains(buscar),
                Remesa.beneficiario_nombre.contains(buscar)
            )
        )
    if facturada == 'si':
        query = query.filter_by(facturada=True)
    elif facturada == 'no':
        query = query.filter_by(facturada=False)

    remesas = query.order_by(Remesa.fecha_creacion.desc()).all()
    repartidores = Usuario.query.filter_by(rol='repartidor', activo=True).all()

    # Calcular alertas
    hace_24h = datetime.utcnow() - timedelta(hours=24)
    alertas = {
        'sin_pagar': Remesa.query.filter_by(facturada=False, estado='entregada').count(),
        'sin_entregar_24h': Remesa.query.filter(
            Remesa.estado.in_(['pendiente', 'en_proceso']),
            Remesa.fecha_creacion < hace_24h
        ).count(),
        'pendientes': Remesa.query.filter_by(estado='pendiente').count(),
        'sin_repartidor': Remesa.query.filter(
            Remesa.estado.in_(['pendiente', 'en_proceso']),
            Remesa.repartidor_id == None
        ).count()
    }
    alertas['total'] = alertas['sin_pagar'] + alertas['sin_entregar_24h'] + alertas['sin_repartidor']

    return render_template('remesas/lista.html',
        remesas=remesas,
        repartidores=repartidores,
        estado_filtro=estado,
        buscar=buscar,
        facturada_filtro=facturada,
        alertas=alertas
    )


@remesas_bp.route('/remesas/nueva', methods=['GET', 'POST'])
@login_required
@admin_required
def nueva():
    if request.method == 'POST':
        monto_envio = float(request.form.get('monto_envio', 0))
        tipo_entrega = request.form.get('tipo_entrega', 'MN')
        tasa_mercado = TasaCambio.obtener_tasa_actual()

        if tipo_entrega == 'USD':
            porcentaje = 5.0
            fija = 0.0
            total_comision = monto_envio * (porcentaje / 100)
        else:
            porcentaje = 0.0
            fija = 0.0
            total_comision = 0.0

        if tipo_entrega == 'USD':
            monto_entrega = monto_envio
            moneda_entrega = 'USD'
            tasa_aplicada = 1.0
        else:
            tasa_entrega = float(request.form.get('tasa_entrega', tasa_mercado))
            monto_entrega = monto_envio * tasa_entrega
            moneda_entrega = 'CUP'
            tasa_aplicada = tasa_entrega

        remesa = Remesa(
            remitente_nombre=request.form.get('remitente_nombre'),
            remitente_telefono=request.form.get('remitente_telefono'),
            beneficiario_nombre=request.form.get('beneficiario_nombre'),
            beneficiario_telefono=request.form.get('beneficiario_telefono'),
            beneficiario_direccion=request.form.get('beneficiario_direccion'),
            tipo_entrega=tipo_entrega,
            monto_envio=monto_envio,
            tasa_cambio=tasa_aplicada,
            monto_entrega=monto_entrega,
            moneda_entrega=moneda_entrega,
            comision_porcentaje=porcentaje,
            comision_fija=fija,
            total_comision=total_comision,
            total_cobrado=monto_envio + total_comision,
            notas=request.form.get('notas'),
            creado_por=current_user.id
        )

        repartidor_id = request.form.get('repartidor_id')
        repartidor = None
        if repartidor_id:
            remesa.repartidor_id = int(repartidor_id)
            remesa.estado = 'en_proceso'
            repartidor = Usuario.query.get(int(repartidor_id))

        db.session.add(remesa)

        movimiento = MovimientoContable(
            tipo='ingreso',
            concepto=f'Comision remesa {remesa.codigo}',
            monto=total_comision,
            remesa_id=remesa.id,
            usuario_id=current_user.id
        )
        db.session.add(movimiento)

        db.session.commit()

        # Enviar Push Notification a admins
        try:
            push_nueva_remesa_admin(remesa)
        except Exception as e:
            print(f"Error enviando push: {e}")

        # Si tiene repartidor asignado, enviar push
        if repartidor:
            try:
                push_remesa_asignada(remesa)
            except Exception as e:
                print(f"Error enviando push a repartidor: {e}")

        # Generar todos los links de WhatsApp para notificaciones manuales
        links_wa = obtener_links_notificacion_remesa(remesa, repartidor)

        flash(f'Remesa {remesa.codigo} creada exitosamente', 'success')

        # Mostrar links de WhatsApp para envio manual
        if links_wa.get('repartidor'):
            flash(f'Notificar a {links_wa["repartidor"]["nombre"]}: <a href="{links_wa["repartidor"]["link"]}" target="_blank" class="btn btn-sm btn-success"><i class="fab fa-whatsapp"></i> WhatsApp Repartidor</a>', 'whatsapp')

        if links_wa.get('beneficiario'):
            flash(f'Notificar a {links_wa["beneficiario"]["nombre"]}: <a href="{links_wa["beneficiario"]["link"]}" target="_blank" class="btn btn-sm btn-success"><i class="fab fa-whatsapp"></i> WhatsApp Beneficiario</a>', 'whatsapp')

        return redirect(url_for('remesas.lista'))

    # Verificar si viene de "repetir remesa"
    repetir_id = request.args.get('repetir')
    remesa_base = None
    if repetir_id:
        remesa_base = Remesa.query.get(int(repetir_id))

    tasa_actual = TasaCambio.obtener_tasa_actual()
    comision = Comision.query.filter_by(activa=True).first()
    repartidores = Usuario.query.filter_by(rol='repartidor', activo=True).all()

    return render_template('remesas/nueva.html',
        tasa_actual=tasa_actual,
        comision=comision,
        repartidores=repartidores,
        remesa_base=remesa_base
    )


@remesas_bp.route('/remesas/<int:id>')
@login_required
def detalle(id):
    remesa = Remesa.query.get_or_404(id)

    if not current_user.es_admin() and remesa.repartidor_id != current_user.id:
        flash('No tienes acceso a esta remesa', 'error')
        return redirect(url_for('index'))

    return render_template('remesas/detalle.html', remesa=remesa)


@remesas_bp.route('/remesas/<int:id>/editar', methods=['GET', 'POST'])
@login_required
@admin_required
def editar(id):
    remesa = Remesa.query.get_or_404(id)

    if request.method == 'POST':
        remesa.remitente_nombre = request.form.get('remitente_nombre')
        remesa.remitente_telefono = request.form.get('remitente_telefono')
        remesa.beneficiario_nombre = request.form.get('beneficiario_nombre')
        remesa.beneficiario_telefono = request.form.get('beneficiario_telefono')
        remesa.beneficiario_direccion = request.form.get('beneficiario_direccion')
        remesa.notas = request.form.get('notas')

        estado_anterior = remesa.estado
        nuevo_estado = request.form.get('estado')
        cambio_estado = False

        if nuevo_estado and nuevo_estado != remesa.estado:
            remesa.estado = nuevo_estado
            cambio_estado = True
            if nuevo_estado == 'entregada':
                remesa.fecha_entrega = datetime.utcnow()

        repartidor_id = request.form.get('repartidor_id')
        if repartidor_id:
            remesa.repartidor_id = int(repartidor_id)
            if remesa.estado == 'pendiente':
                remesa.estado = 'en_proceso'
                cambio_estado = True
        else:
            remesa.repartidor_id = None

        db.session.commit()
        flash('Remesa actualizada exitosamente', 'success')

        # Notificar cambio de estado si hubo cambio
        if cambio_estado and not current_user.es_admin():
            resultado = notificar_admin_cambio_estado(remesa, estado_anterior, remesa.estado, current_user)
            if resultado.get('link_manual'):
                flash(f'Notificar Admin: <a href="{resultado["link_manual"]}" target="_blank" class="btn btn-sm btn-success"><i class="fab fa-whatsapp"></i> WhatsApp</a>', 'whatsapp')

        return redirect(url_for('remesas.detalle', id=id))

    repartidores = Usuario.query.filter_by(rol='repartidor', activo=True).all()
    return render_template('remesas/editar.html', remesa=remesa, repartidores=repartidores)


@remesas_bp.route('/remesas/<int:id>/asignar', methods=['POST'])
@login_required
@admin_required
def asignar(id):
    remesa = Remesa.query.get_or_404(id)
    repartidor_id = request.form.get('repartidor_id')

    if repartidor_id:
        remesa.repartidor_id = int(repartidor_id)
        if remesa.estado == 'pendiente':
            remesa.estado = 'en_proceso'
        db.session.commit()

        notificaciones = []
        repartidor = Usuario.query.get(int(repartidor_id))

        # Enviar Push Notification al repartidor
        try:
            push_remesa_asignada(remesa)
        except Exception as e:
            print(f"Error enviando push a repartidor: {e}")

        # Notificar al repartidor por WhatsApp
        if repartidor:
            resultado = notificar_nueva_remesa(repartidor, remesa)
            if resultado['exito']:
                notificaciones.append('Repartidor')

        # Notificar al beneficiario
        if remesa.beneficiario_telefono:
            resultado = notificar_beneficiario(remesa)
            if resultado['exito']:
                notificaciones.append('Beneficiario')

        if notificaciones:
            flash(f'Repartidor asignado - Notificados: {", ".join(notificaciones)}', 'success')
        else:
            flash('Repartidor asignado exitosamente', 'success')
    else:
        flash('Selecciona un repartidor', 'error')

    return redirect(url_for('remesas.lista'))


@remesas_bp.route('/remesas/<int:id>/facturar', methods=['POST'])
@login_required
@admin_required
def facturar(id):
    remesa = Remesa.query.get_or_404(id)
    remesa.facturada = True
    remesa.fecha_facturacion = datetime.utcnow()
    db.session.commit()
    flash(f'Remesa {remesa.codigo} marcada como pagada', 'success')
    return redirect(url_for('remesas.lista'))


@remesas_bp.route('/remesas/<int:id>/desfacturar', methods=['POST'])
@login_required
@admin_required
def desfacturar(id):
    remesa = Remesa.query.get_or_404(id)
    remesa.facturada = False
    remesa.fecha_facturacion = None
    db.session.commit()
    flash(f'Remesa {remesa.codigo} desmarcada como pagada', 'info')
    return redirect(url_for('remesas.lista'))


# === RUTAS PARA REPARTIDORES ===

@remesas_bp.route('/mis-entregas')
@login_required
def mis_entregas():
    remesas = Remesa.query.filter(
        Remesa.repartidor_id == current_user.id,
        Remesa.estado.in_(['pendiente', 'en_proceso'])
    ).order_by(Remesa.fecha_creacion.desc()).all()

    return render_template('remesas/mis_entregas.html', remesas=remesas)


@remesas_bp.route('/historial')
@login_required
def historial():
    remesas = Remesa.query.filter(
        Remesa.repartidor_id == current_user.id,
        Remesa.estado.in_(['entregada', 'cancelada'])
    ).order_by(Remesa.fecha_entrega.desc()).limit(50).all()

    return render_template('remesas/historial.html', remesas=remesas)


@remesas_bp.route('/remesas/<int:id>/entregar', methods=['POST'])
@login_required
def marcar_entregada(id):
    remesa = Remesa.query.get_or_404(id)

    if remesa.repartidor_id != current_user.id and not current_user.es_admin():
        flash('No tienes permiso para esta accion', 'error')
        return redirect(url_for('index'))

    remesa.estado = 'entregada'
    remesa.fecha_entrega = datetime.utcnow()
    db.session.commit()

    # Actualizar balance del repartidor si tiene uno asignado
    if remesa.repartidor:
        repartidor = remesa.repartidor
        monto = remesa.monto_entrega
        moneda = remesa.moneda_entrega

        if moneda == 'USD':
            saldo_anterior = repartidor.saldo_usd or 0
            repartidor.saldo_usd = saldo_anterior - monto
            saldo_nuevo = repartidor.saldo_usd
        else:  # CUP
            saldo_anterior = repartidor.saldo_cup or 0
            repartidor.saldo_cup = saldo_anterior - monto
            saldo_nuevo = repartidor.saldo_cup

        # Registrar movimiento de efectivo
        movimiento = MovimientoEfectivo(
            repartidor_id=repartidor.id,
            tipo='entrega',
            moneda=moneda,
            monto=monto,
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

    # Notificar la entrega
    flash(f'Remesa {remesa.codigo} marcada como entregada', 'success')

    # Notificar al admin (USA -> SMS)
    if not current_user.es_admin():
        resultado = notificar_entrega_admin(remesa, current_user)
        if resultado.get('exito'):
            flash('Admin notificado por SMS', 'info')

    # Notificar al remitente (USA -> SMS)
    if remesa.remitente_telefono:
        resultado = notificar_entrega_remitente(remesa)
        if resultado.get('exito'):
            flash('Remitente notificado por SMS', 'info')

    if current_user.es_admin():
        return redirect(url_for('remesas.lista'))
    return redirect(url_for('remesas.mis_entregas'))


# === APIs ===

@remesas_bp.route('/api/calcular', methods=['POST'])
@login_required
def calcular_remesa():
    """API para calcular montos en tiempo real"""
    data = request.get_json()
    monto = float(data.get('monto', 0))
    tipo_entrega = data.get('tipo_entrega', 'MN')

    tasa = TasaCambio.obtener_tasa_actual()

    if tipo_entrega == 'USD':
        porcentaje = 5.0
        fija = 0.0
        total_comision = monto * (porcentaje / 100)
    else:
        porcentaje = 0.0
        fija = 0.0
        total_comision = 0.0

    return {
        'monto_entrega': round(monto * tasa, 2),
        'tasa': tasa,
        'comision_porcentaje': porcentaje,
        'comision_fija': fija,
        'total_comision': round(total_comision, 2),
        'total_cobrar': round(monto + total_comision, 2)
    }


@remesas_bp.route('/api/buscar-remitentes')
@login_required
def buscar_remitentes():
    """API para buscar remitentes existentes (autocompletar)"""
    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return jsonify([])

    # Buscar remitentes unicos en remesas anteriores
    remesas = Remesa.query.filter(
        Remesa.remitente_nombre.ilike(f'%{q}%')
    ).order_by(Remesa.fecha_creacion.desc()).limit(10).all()

    # Eliminar duplicados manteniendo el mas reciente
    vistos = set()
    resultados = []
    for r in remesas:
        clave = r.remitente_nombre.lower()
        if clave not in vistos:
            vistos.add(clave)
            resultados.append({
                'nombre': r.remitente_nombre,
                'telefono': r.remitente_telefono or ''
            })

    return jsonify(resultados)


@remesas_bp.route('/api/buscar-beneficiarios')
@login_required
def buscar_beneficiarios():
    """API para buscar beneficiarios existentes (autocompletar)"""
    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return jsonify([])

    remesas = Remesa.query.filter(
        Remesa.beneficiario_nombre.ilike(f'%{q}%')
    ).order_by(Remesa.fecha_creacion.desc()).limit(10).all()

    vistos = set()
    resultados = []
    for r in remesas:
        clave = r.beneficiario_nombre.lower()
        if clave not in vistos:
            vistos.add(clave)
            resultados.append({
                'nombre': r.beneficiario_nombre,
                'telefono': r.beneficiario_telefono or '',
                'direccion': r.beneficiario_direccion or ''
            })

    return jsonify(resultados)


@remesas_bp.route('/api/listar-remitentes')
@login_required
def listar_remitentes():
    """API para listar todos los remitentes (ultimos 20 unicos)"""
    remesas = Remesa.query.order_by(Remesa.fecha_creacion.desc()).limit(100).all()

    vistos = set()
    resultados = []
    for r in remesas:
        clave = r.remitente_nombre.lower()
        if clave not in vistos and len(resultados) < 20:
            vistos.add(clave)
            resultados.append({
                'nombre': r.remitente_nombre,
                'telefono': r.remitente_telefono or ''
            })

    return jsonify(resultados)


@remesas_bp.route('/api/listar-beneficiarios')
@login_required
def listar_beneficiarios():
    """API para listar todos los beneficiarios (ultimos 20 unicos)"""
    remesas = Remesa.query.order_by(Remesa.fecha_creacion.desc()).limit(100).all()

    vistos = set()
    resultados = []
    for r in remesas:
        clave = r.beneficiario_nombre.lower()
        if clave not in vistos and len(resultados) < 20:
            vistos.add(clave)
            resultados.append({
                'nombre': r.beneficiario_nombre,
                'telefono': r.beneficiario_telefono or '',
                'direccion': r.beneficiario_direccion or ''
            })

    return jsonify(resultados)


# === PAGINA PUBLICA DE SEGUIMIENTO ===

@remesas_bp.route('/seguimiento', methods=['GET', 'POST'])
def seguimiento():
    """Pagina publica para consultar estado de remesa"""
    remesa = None
    error = None

    if request.method == 'POST':
        codigo = request.form.get('codigo', '').strip().upper()
        if codigo:
            remesa = Remesa.query.filter_by(codigo=codigo).first()
            if not remesa:
                error = 'No se encontro ninguna remesa con ese codigo'

    return render_template('remesas/seguimiento.html', remesa=remesa, error=error)
