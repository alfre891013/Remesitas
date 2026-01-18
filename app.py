from flask import Flask, redirect, url_for, render_template, send_from_directory, make_response
from flask_login import LoginManager, current_user
from config import Config
import os
from models import db, Usuario, TasaCambio, Comision, Configuracion, Remesa

login_manager = LoginManager()

def crear_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Inicializar extensiones
    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Por favor inicia sesion para acceder.'

    @login_manager.user_loader
    def load_user(user_id):
        return Usuario.query.get(int(user_id))

    # Registrar blueprints
    from routes.auth import auth_bp
    from routes.remesas import remesas_bp
    from routes.admin import admin_bp
    from routes.reportes import reportes_bp
    from routes.publico import publico_bp
    from routes.repartidor import repartidor_bp
    from routes.revendedor import revendedor_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(remesas_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(reportes_bp)
    app.register_blueprint(publico_bp)
    app.register_blueprint(repartidor_bp)
    app.register_blueprint(revendedor_bp)

    # Ruta principal - Landing Page
    @app.route('/')
    def index():
        if current_user.is_authenticated:
            if current_user.es_admin():
                return redirect(url_for('remesas.dashboard'))
            elif current_user.es_revendedor():
                return redirect(url_for('revendedor.panel'))
            else:
                return redirect(url_for('remesas.mis_entregas'))
        # Mostrar landing page para visitantes
        tasa = TasaCambio.obtener_tasa_actual()
        return render_template('landing.html', tasa_actual=tasa)

    # Service Worker desde la raiz (necesario para scope /)
    @app.route('/sw.js')
    def service_worker():
        response = make_response(
            send_from_directory(
                os.path.join(app.root_path, 'static'),
                'sw.js',
                mimetype='application/javascript'
            )
        )
        # Header especial para permitir scope /
        response.headers['Service-Worker-Allowed'] = '/'
        return response

    # Crear tablas y datos iniciales
    with app.app_context():
        db.create_all()
        crear_datos_iniciales()

    return app


def crear_datos_iniciales():
    """Crea datos iniciales si no existen"""
    # Eliminar remesas de prueba (temporal - quitar después)
    remesas_prueba = ['REM-75220A0D', 'REM-C2D8B9B5', 'REM-8189C9BF']
    for codigo in remesas_prueba:
        remesa = Remesa.query.filter_by(codigo=codigo).first()
        if remesa:
            db.session.delete(remesa)
            db.session.commit()
    # Crear usuario admin si no existe
    if not Usuario.query.filter_by(username='admin').first():
        admin = Usuario(
            username='admin',
            nombre='Administrador',
            rol='admin',
            debe_cambiar_password=False  # Admin inicial no requiere cambio
        )
        admin.set_password('admin123')
        db.session.add(admin)

    # Crear tasa de cambio inicial si no existe
    if not TasaCambio.query.first():
        # Intentar obtener tasa real de internet
        try:
            from tasas_externas import obtener_tasa_actual
            tasa_externa = obtener_tasa_actual()
            tasa_valor = tasa_externa['USD'] if tasa_externa else 435
        except:
            tasa_valor = 435  # Valor por defecto si falla

        tasa = TasaCambio(
            moneda_origen='USD',
            moneda_destino='CUP',
            tasa=tasa_valor,
            activa=True
        )
        db.session.add(tasa)

    # Crear comision por defecto si no existe
    if not Comision.query.first():
        comision = Comision(
            nombre='Comision estandar',
            rango_minimo=0,
            rango_maximo=None,
            porcentaje=3.0,
            monto_fijo=2.0,
            activa=True
        )
        db.session.add(comision)

    # Configuracion inicial
    if not Configuracion.query.first():
        configs = [
            Configuracion(clave='moneda_local', valor='CUP', descripcion='Codigo de moneda local'),
            Configuracion(clave='nombre_negocio', valor='Remesitas', descripcion='Nombre del negocio'),
        ]
        db.session.add_all(configs)

    db.session.commit()


if __name__ == '__main__':
    app = crear_app()

    # Iniciar scheduler para actualizacion automatica de tasas
    # Solo en el proceso principal (evita duplicados con reloader)
    import os
    if os.environ.get('WERKZEUG_RUN_MAIN') == 'true' or not app.debug:
        from scheduler import iniciar_scheduler
        iniciar_scheduler(app)

    app.run(debug=True, host='0.0.0.0', port=5000)
