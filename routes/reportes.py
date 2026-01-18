from flask import Blueprint, render_template, request
from flask_login import login_required, current_user
from models import db, Remesa, Usuario, MovimientoContable
from datetime import datetime, timedelta
from functools import wraps
from sqlalchemy import func

reportes_bp = Blueprint('reportes', __name__, url_prefix='/reportes')


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.es_admin():
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function


@reportes_bp.route('/balance')
@login_required
@admin_required
def balance():
    # Obtener rango de fechas
    hoy = datetime.utcnow().date()
    fecha_inicio = request.args.get('fecha_inicio', (hoy - timedelta(days=30)).isoformat())
    fecha_fin = request.args.get('fecha_fin', hoy.isoformat())

    fecha_inicio_dt = datetime.fromisoformat(fecha_inicio)
    fecha_fin_dt = datetime.fromisoformat(fecha_fin) + timedelta(days=1)  # Incluir todo el dia

    # Estadisticas del periodo
    remesas_periodo = Remesa.query.filter(
        Remesa.fecha_creacion >= fecha_inicio_dt,
        Remesa.fecha_creacion < fecha_fin_dt,
        Remesa.estado != 'cancelada'
    )

    total_remesas = remesas_periodo.count()
    total_enviado = db.session.query(func.sum(Remesa.monto_envio)).filter(
        Remesa.fecha_creacion >= fecha_inicio_dt,
        Remesa.fecha_creacion < fecha_fin_dt,
        Remesa.estado != 'cancelada'
    ).scalar() or 0

    total_comisiones = db.session.query(func.sum(Remesa.total_comision)).filter(
        Remesa.fecha_creacion >= fecha_inicio_dt,
        Remesa.fecha_creacion < fecha_fin_dt,
        Remesa.estado != 'cancelada'
    ).scalar() or 0

    total_cobrado = db.session.query(func.sum(Remesa.total_cobrado)).filter(
        Remesa.fecha_creacion >= fecha_inicio_dt,
        Remesa.fecha_creacion < fecha_fin_dt,
        Remesa.estado != 'cancelada'
    ).scalar() or 0

    # Remesas por estado
    por_estado = db.session.query(
        Remesa.estado,
        func.count(Remesa.id)
    ).filter(
        Remesa.fecha_creacion >= fecha_inicio_dt,
        Remesa.fecha_creacion < fecha_fin_dt
    ).group_by(Remesa.estado).all()

    # Remesas por dia
    por_dia = db.session.query(
        func.date(Remesa.fecha_creacion).label('fecha'),
        func.count(Remesa.id).label('cantidad'),
        func.sum(Remesa.monto_envio).label('monto'),
        func.sum(Remesa.total_comision).label('comision')
    ).filter(
        Remesa.fecha_creacion >= fecha_inicio_dt,
        Remesa.fecha_creacion < fecha_fin_dt,
        Remesa.estado != 'cancelada'
    ).group_by(func.date(Remesa.fecha_creacion)).order_by(
        func.date(Remesa.fecha_creacion).desc()
    ).all()

    return render_template('reportes/balance.html',
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        total_remesas=total_remesas,
        total_enviado=total_enviado,
        total_comisiones=total_comisiones,
        total_cobrado=total_cobrado,
        por_estado=dict(por_estado),
        por_dia=por_dia
    )


@reportes_bp.route('/repartidores')
@login_required
@admin_required
def por_repartidor():
    hoy = datetime.utcnow().date()
    fecha_inicio = request.args.get('fecha_inicio', (hoy - timedelta(days=30)).isoformat())
    fecha_fin = request.args.get('fecha_fin', hoy.isoformat())

    fecha_inicio_dt = datetime.fromisoformat(fecha_inicio)
    fecha_fin_dt = datetime.fromisoformat(fecha_fin) + timedelta(days=1)

    # Estadisticas por repartidor
    repartidores = Usuario.query.filter_by(rol='repartidor').all()

    stats_repartidores = []
    for rep in repartidores:
        remesas = Remesa.query.filter(
            Remesa.repartidor_id == rep.id,
            Remesa.fecha_creacion >= fecha_inicio_dt,
            Remesa.fecha_creacion < fecha_fin_dt
        )

        total = remesas.count()
        entregadas = remesas.filter_by(estado='entregada').count()
        pendientes = remesas.filter(Remesa.estado.in_(['pendiente', 'en_proceso'])).count()

        monto_entregado = db.session.query(func.sum(Remesa.monto_entrega)).filter(
            Remesa.repartidor_id == rep.id,
            Remesa.estado == 'entregada',
            Remesa.fecha_creacion >= fecha_inicio_dt,
            Remesa.fecha_creacion < fecha_fin_dt
        ).scalar() or 0

        stats_repartidores.append({
            'repartidor': rep,
            'total': total,
            'entregadas': entregadas,
            'pendientes': pendientes,
            'monto_entregado': monto_entregado
        })

    return render_template('reportes/repartidores.html',
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        stats_repartidores=stats_repartidores
    )


@reportes_bp.route('/ingresos')
@login_required
@admin_required
def ingresos():
    hoy = datetime.utcnow().date()
    fecha_inicio = request.args.get('fecha_inicio', (hoy - timedelta(days=30)).isoformat())
    fecha_fin = request.args.get('fecha_fin', hoy.isoformat())

    fecha_inicio_dt = datetime.fromisoformat(fecha_inicio)
    fecha_fin_dt = datetime.fromisoformat(fecha_fin) + timedelta(days=1)

    # Movimientos contables
    movimientos = MovimientoContable.query.filter(
        MovimientoContable.fecha >= fecha_inicio_dt,
        MovimientoContable.fecha < fecha_fin_dt
    ).order_by(MovimientoContable.fecha.desc()).all()

    # Totales
    total_ingresos = db.session.query(func.sum(MovimientoContable.monto)).filter(
        MovimientoContable.tipo == 'ingreso',
        MovimientoContable.fecha >= fecha_inicio_dt,
        MovimientoContable.fecha < fecha_fin_dt
    ).scalar() or 0

    total_egresos = db.session.query(func.sum(MovimientoContable.monto)).filter(
        MovimientoContable.tipo == 'egreso',
        MovimientoContable.fecha >= fecha_inicio_dt,
        MovimientoContable.fecha < fecha_fin_dt
    ).scalar() or 0

    return render_template('reportes/ingresos.html',
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        movimientos=movimientos,
        total_ingresos=total_ingresos,
        total_egresos=total_egresos,
        balance=total_ingresos - total_egresos
    )


@reportes_bp.route('/pagos')
@login_required
@admin_required
def pagos():
    """Reporte de remesas pagadas vs pendientes de pago"""
    hoy = datetime.utcnow().date()
    fecha_inicio = request.args.get('fecha_inicio', (hoy - timedelta(days=30)).isoformat())
    fecha_fin = request.args.get('fecha_fin', hoy.isoformat())

    fecha_inicio_dt = datetime.fromisoformat(fecha_inicio)
    fecha_fin_dt = datetime.fromisoformat(fecha_fin) + timedelta(days=1)

    # Remesas sin pagar (entregadas pero no facturadas)
    sin_pagar = Remesa.query.filter(
        Remesa.facturada == False,
        Remesa.estado == 'entregada'
    ).order_by(Remesa.fecha_entrega.desc()).all()

    total_sin_pagar = db.session.query(func.sum(Remesa.total_cobrado)).filter(
        Remesa.facturada == False,
        Remesa.estado == 'entregada'
    ).scalar() or 0

    # Remesas pagadas en el periodo
    pagadas_periodo = Remesa.query.filter(
        Remesa.facturada == True,
        Remesa.fecha_facturacion >= fecha_inicio_dt,
        Remesa.fecha_facturacion < fecha_fin_dt
    ).order_by(Remesa.fecha_facturacion.desc()).all()

    total_pagado_periodo = db.session.query(func.sum(Remesa.total_cobrado)).filter(
        Remesa.facturada == True,
        Remesa.fecha_facturacion >= fecha_inicio_dt,
        Remesa.fecha_facturacion < fecha_fin_dt
    ).scalar() or 0

    # Totales historicos
    total_pagado_historico = db.session.query(func.sum(Remesa.total_cobrado)).filter(
        Remesa.facturada == True
    ).scalar() or 0

    return render_template('reportes/pagos.html',
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        sin_pagar=sin_pagar,
        total_sin_pagar=total_sin_pagar,
        pagadas_periodo=pagadas_periodo,
        total_pagado_periodo=total_pagado_periodo,
        total_pagado_historico=total_pagado_historico
    )
