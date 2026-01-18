"""
Tareas programadas para Remesitas
Actualiza la tasa de cambio automaticamente
"""

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
import logging

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()

def actualizar_tasa_automatica():
    """Actualiza las 3 tasas de cambio (USD, EUR, MLC) desde fuentes externas"""
    from app import crear_app
    from models import db, TasaCambio
    from tasas_externas import obtener_todas_las_tasas

    app = crear_app()
    with app.app_context():
        try:
            resultado = obtener_todas_las_tasas()

            if not resultado:
                logger.warning("No se pudo obtener tasas externas")
                return

            fuente = resultado.get('fuente', 'Externa')

            # Actualizar cada moneda (USD, EUR, MLC)
            for moneda in ['USD', 'EUR', 'MLC']:
                if moneda not in resultado:
                    continue

                tasa_nueva = resultado.get(moneda)

                # Obtener tasa actual de esta moneda
                tasa_db = TasaCambio.query.filter_by(
                    moneda_origen=moneda,
                    activa=True
                ).first()
                tasa_actual = tasa_db.tasa if tasa_db else 0

                if tasa_nueva and tasa_nueva != tasa_actual:
                    # Desactivar tasa anterior de esta moneda
                    TasaCambio.query.filter_by(
                        moneda_origen=moneda,
                        activa=True
                    ).update({'activa': False})

                    # Crear nueva tasa
                    nueva = TasaCambio(
                        tasa=tasa_nueva,
                        moneda_origen=moneda,
                        moneda_destino='CUP',
                        activa=True
                    )
                    db.session.add(nueva)
                    logger.info(f"{moneda}: {tasa_actual} -> {tasa_nueva} CUP")

            db.session.commit()
            logger.info(f"Tasas actualizadas desde {fuente}")

        except Exception as e:
            logger.error(f"Error actualizando tasas: {e}")


def iniciar_scheduler(app):
    """Inicia el scheduler con las tareas programadas"""

    # Actualizar tasa cada 12 horas (2 veces al dia)
    scheduler.add_job(
        func=actualizar_tasa_automatica,
        trigger=IntervalTrigger(hours=12),
        id='actualizar_tasa',
        name='Actualizar tasa de cambio',
        replace_existing=True
    )

    # Ejecutar una vez al iniciar
    scheduler.add_job(
        func=actualizar_tasa_automatica,
        trigger='date',  # Ejecutar inmediatamente
        id='actualizar_tasa_inicial',
        name='Actualizar tasa inicial'
    )

    scheduler.start()
    logger.info("Scheduler iniciado - Tasa se actualizara cada 12 horas")


def detener_scheduler():
    """Detiene el scheduler"""
    if scheduler.running:
        scheduler.shutdown()
        logger.info("Scheduler detenido")
