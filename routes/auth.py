from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, current_app
from flask_login import login_user, logout_user, login_required, current_user
from models import db, Usuario, SuscripcionPush

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        # Si debe cambiar password, redirigir
        if current_user.debe_cambiar_password:
            return redirect(url_for('auth.primer_password'))
        return redirect(url_for('index'))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        usuario = Usuario.query.filter_by(username=username).first()

        if usuario and usuario.check_password(password):
            if not usuario.activo:
                flash('Tu cuenta esta desactivada. Contacta al administrador.', 'error')
                return render_template('login.html')

            login_user(usuario, remember=True)

            # Si debe cambiar password, redirigir a cambio obligatorio
            if usuario.debe_cambiar_password:
                return redirect(url_for('auth.primer_password'))

            next_page = request.args.get('next')

            if usuario.es_admin():
                return redirect(next_page or url_for('remesas.dashboard'))
            elif usuario.es_revendedor():
                return redirect(next_page or url_for('revendedor.panel'))
            else:
                return redirect(next_page or url_for('remesas.mis_entregas'))
        else:
            flash('Usuario o contrasena incorrectos', 'error')

    return render_template('login.html')


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Sesion cerrada correctamente', 'success')
    return redirect(url_for('auth.login'))


@auth_bp.route('/primer-acceso', methods=['GET', 'POST'])
@login_required
def primer_password():
    """Cambio obligatorio de contrasena en primer acceso"""
    if not current_user.debe_cambiar_password:
        return redirect(url_for('index'))

    if request.method == 'POST':
        password_nueva = request.form.get('password_nueva')
        password_confirmar = request.form.get('password_confirmar')

        if password_nueva != password_confirmar:
            flash('Las contrasenas no coinciden', 'error')
        elif len(password_nueva) < 4:
            flash('La contrasena debe tener al menos 4 caracteres', 'error')
        else:
            current_user.set_password(password_nueva)
            current_user.debe_cambiar_password = False
            db.session.commit()
            flash('Contrasena establecida correctamente. Bienvenido!', 'success')

            # Redirigir segun rol
            if current_user.es_admin():
                return redirect(url_for('remesas.dashboard'))
            elif current_user.es_revendedor():
                return redirect(url_for('revendedor.panel'))
            else:
                return redirect(url_for('remesas.mis_entregas'))

    return render_template('primer_password.html')


@auth_bp.route('/cambiar-password', methods=['GET', 'POST'])
@login_required
def cambiar_password():
    # Si debe cambiar password obligatorio, redirigir
    if current_user.debe_cambiar_password:
        return redirect(url_for('auth.primer_password'))

    if request.method == 'POST':
        password_actual = request.form.get('password_actual')
        password_nueva = request.form.get('password_nueva')
        password_confirmar = request.form.get('password_confirmar')

        if not current_user.check_password(password_actual):
            flash('La contrasena actual es incorrecta', 'error')
        elif password_nueva != password_confirmar:
            flash('Las contrasenas nuevas no coinciden', 'error')
        elif len(password_nueva) < 4:
            flash('La contrasena debe tener al menos 4 caracteres', 'error')
        else:
            current_user.set_password(password_nueva)
            db.session.commit()
            flash('Contrasena actualizada correctamente', 'success')
            return redirect(url_for('index'))

    return render_template('cambiar_password.html')


# ==========================================
# API DE PUSH NOTIFICATIONS
# ==========================================

@auth_bp.route('/api/push/vapid-key')
def get_vapid_key():
    """Retorna la clave publica VAPID para suscribirse a push"""
    vapid_public = current_app.config.get('VAPID_PUBLIC_KEY')
    if not vapid_public:
        return jsonify({'error': 'VAPID no configurado'}), 500
    return jsonify({'publicKey': vapid_public})


@auth_bp.route('/api/push/suscribir', methods=['POST'])
def suscribir_push():
    """Guarda una suscripcion push del navegador"""
    data = request.get_json()

    if not data or 'endpoint' not in data:
        return jsonify({'error': 'Datos invalidos'}), 400

    endpoint = data.get('endpoint')
    keys = data.get('keys', {})
    p256dh = keys.get('p256dh')
    auth = keys.get('auth')

    if not all([endpoint, p256dh, auth]):
        return jsonify({'error': 'Faltan datos de suscripcion'}), 400

    # Verificar si ya existe
    existente = SuscripcionPush.query.filter_by(endpoint=endpoint).first()

    if existente:
        # Actualizar suscripcion existente
        existente.p256dh = p256dh
        existente.auth = auth
        existente.activa = True
        if current_user.is_authenticated:
            existente.usuario_id = current_user.id
        db.session.commit()
        return jsonify({'mensaje': 'Suscripcion actualizada', 'id': existente.id})

    # Crear nueva suscripcion
    nueva = SuscripcionPush(
        endpoint=endpoint,
        p256dh=p256dh,
        auth=auth,
        usuario_id=current_user.id if current_user.is_authenticated else None
    )
    db.session.add(nueva)
    db.session.commit()

    return jsonify({'mensaje': 'Suscripcion creada', 'id': nueva.id})


@auth_bp.route('/api/push/desuscribir', methods=['POST'])
def desuscribir_push():
    """Elimina o desactiva una suscripcion push"""
    data = request.get_json()
    endpoint = data.get('endpoint') if data else None

    if not endpoint:
        return jsonify({'error': 'Endpoint requerido'}), 400

    suscripcion = SuscripcionPush.query.filter_by(endpoint=endpoint).first()

    if suscripcion:
        suscripcion.activa = False
        db.session.commit()
        return jsonify({'mensaje': 'Suscripcion desactivada'})

    return jsonify({'mensaje': 'Suscripcion no encontrada'}), 404


@auth_bp.route('/api/push/test', methods=['POST'])
@login_required
def test_push():
    """Endpoint de prueba para enviar push al usuario actual"""
    from push_notifications import notificar_usuario_push

    resultado = notificar_usuario_push(
        current_user.id,
        "Prueba de Notificacion",
        "Si ves esto, las notificaciones funcionan correctamente!"
    )

    return jsonify(resultado)


@auth_bp.route('/test-push')
@login_required
def test_push_page():
    """Pagina de diagnostico para Push Notifications"""
    return render_template('test_push.html')
