from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import uuid

db = SQLAlchemy()

class Usuario(UserMixin, db.Model):
    __tablename__ = 'usuarios'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    nombre = db.Column(db.String(100), nullable=False)
    telefono = db.Column(db.String(20))
    rol = db.Column(db.String(20), nullable=False, default='repartidor')  # admin, repartidor, revendedor
    activo = db.Column(db.Boolean, default=True)
    debe_cambiar_password = db.Column(db.Boolean, default=True)  # True = debe cambiar en primer login
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)

    # Campos para revendedores
    comision_revendedor = db.Column(db.Float, default=2.0)  # % que cobra Happy Remesitas al revendedor
    saldo_pendiente = db.Column(db.Float, default=0.0)  # Lo que debe el revendedor
    usa_logistica = db.Column(db.Boolean, default=True)  # True=usa tu logistica, False=solo plataforma

    # Campos para repartidores - Control de efectivo
    saldo_usd = db.Column(db.Float, default=0.0)  # Efectivo USD que tiene el repartidor
    saldo_cup = db.Column(db.Float, default=0.0)  # Efectivo CUP que tiene el repartidor

    # Relaciones
    remesas_asignadas = db.relationship('Remesa', backref='repartidor', lazy=True, foreign_keys='Remesa.repartidor_id')
    remesas_creadas = db.relationship('Remesa', backref='creador', lazy=True, foreign_keys='Remesa.creado_por')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def es_admin(self):
        return self.rol == 'admin'

    def es_revendedor(self):
        return self.rol == 'revendedor'


class Remesa(db.Model):
    __tablename__ = 'remesas'

    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(20), unique=True, nullable=False)

    # Datos del remitente
    remitente_nombre = db.Column(db.String(100), nullable=False)
    remitente_telefono = db.Column(db.String(20))

    # Datos del beneficiario
    beneficiario_nombre = db.Column(db.String(100), nullable=False)
    beneficiario_telefono = db.Column(db.String(20))
    beneficiario_direccion = db.Column(db.Text)

    # Tipo de entrega
    tipo_entrega = db.Column(db.String(10), default='MN')  # MN (CUP) o USD

    # Montos y conversion
    monto_envio = db.Column(db.Float, nullable=False)  # Monto recibido en USD
    tasa_cambio = db.Column(db.Float, nullable=False)  # Tasa aplicada
    monto_entrega = db.Column(db.Float, nullable=False)  # Monto a entregar
    moneda_entrega = db.Column(db.String(10), default='CUP')  # CUP o USD

    # Comisiones
    comision_porcentaje = db.Column(db.Float, default=0)
    comision_fija = db.Column(db.Float, default=0)
    total_comision = db.Column(db.Float, default=0)
    total_cobrado = db.Column(db.Float, nullable=False)  # monto_envio + total_comision

    # Comision de plataforma (para revendedores)
    comision_plataforma = db.Column(db.Float, default=0)  # Lo que gana Happy Remesitas

    # Estado y asignacion
    estado = db.Column(db.String(20), default='pendiente')
    repartidor_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=True)
    creado_por = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)

    # Revendedor (si aplica)
    revendedor_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=True)

    # Fechas
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    fecha_entrega = db.Column(db.DateTime, nullable=True)

    # Facturacion
    facturada = db.Column(db.Boolean, default=False)
    fecha_facturacion = db.Column(db.DateTime, nullable=True)

    # Notas
    notas = db.Column(db.Text)

    # Foto de entrega
    foto_entrega = db.Column(db.String(255), nullable=True)

    # Para solicitudes de clientes
    es_solicitud = db.Column(db.Boolean, default=False)
    fecha_aprobacion = db.Column(db.DateTime, nullable=True)

    # Relacion con revendedor
    revendedor = db.relationship('Usuario', foreign_keys=[revendedor_id], backref='remesas_revendedor')

    def __init__(self, **kwargs):
        super(Remesa, self).__init__(**kwargs)
        if not self.codigo:
            self.codigo = self.generar_codigo()

    @staticmethod
    def generar_codigo():
        return 'REM-' + uuid.uuid4().hex[:8].upper()


class TasaCambio(db.Model):
    __tablename__ = 'tasas_cambio'

    id = db.Column(db.Integer, primary_key=True)
    moneda_origen = db.Column(db.String(10), default='USD')
    moneda_destino = db.Column(db.String(10), nullable=False)
    tasa = db.Column(db.Float, nullable=False)
    activa = db.Column(db.Boolean, default=True)
    fecha_actualizacion = db.Column(db.DateTime, default=datetime.utcnow)

    @staticmethod
    def obtener_tasa_actual(moneda_origen='USD', moneda_destino='CUP'):
        tasa = TasaCambio.query.filter_by(
            moneda_origen=moneda_origen,
            moneda_destino=moneda_destino,
            activa=True
        ).order_by(TasaCambio.fecha_actualizacion.desc()).first()
        return tasa.tasa if tasa else 435.0


class Comision(db.Model):
    __tablename__ = 'comisiones'

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(50), nullable=False)
    rango_minimo = db.Column(db.Float, default=0)
    rango_maximo = db.Column(db.Float, nullable=True)
    porcentaje = db.Column(db.Float, default=0)
    monto_fijo = db.Column(db.Float, default=0)
    activa = db.Column(db.Boolean, default=True)

    @staticmethod
    def calcular_comision(monto):
        comision = Comision.query.filter(
            Comision.activa == True,
            Comision.rango_minimo <= monto,
            db.or_(Comision.rango_maximo >= monto, Comision.rango_maximo == None)
        ).first()

        if comision:
            comision_porcentaje = monto * (comision.porcentaje / 100)
            return comision.porcentaje, comision.monto_fijo, comision_porcentaje + comision.monto_fijo
        return 0, 0, 0


class PagoRevendedor(db.Model):
    """Registro de pagos realizados por revendedores"""
    __tablename__ = 'pagos_revendedor'

    id = db.Column(db.Integer, primary_key=True)
    revendedor_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    monto = db.Column(db.Float, nullable=False)
    metodo_pago = db.Column(db.String(50))  # Zelle, efectivo, etc.
    referencia = db.Column(db.String(100))  # Numero de confirmacion
    notas = db.Column(db.Text)
    fecha = db.Column(db.DateTime, default=datetime.utcnow)
    registrado_por = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)

    # Relaciones
    revendedor = db.relationship('Usuario', foreign_keys=[revendedor_id], backref='pagos_realizados')
    admin = db.relationship('Usuario', foreign_keys=[registrado_por])


class MovimientoContable(db.Model):
    __tablename__ = 'movimientos_contables'

    id = db.Column(db.Integer, primary_key=True)
    tipo = db.Column(db.String(20), nullable=False)
    concepto = db.Column(db.String(200), nullable=False)
    monto = db.Column(db.Float, nullable=False)
    remesa_id = db.Column(db.Integer, db.ForeignKey('remesas.id'), nullable=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    fecha = db.Column(db.DateTime, default=datetime.utcnow)

    remesa = db.relationship('Remesa', backref='movimientos')
    usuario = db.relationship('Usuario', backref='movimientos')


class MovimientoEfectivo(db.Model):
    """Registro de movimientos de efectivo de repartidores"""
    __tablename__ = 'movimientos_efectivo'

    id = db.Column(db.Integer, primary_key=True)
    repartidor_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    tipo = db.Column(db.String(20), nullable=False)  # asignacion, retiro, entrega, recogida, venta_usd
    moneda = db.Column(db.String(10), nullable=False)  # USD o CUP
    monto = db.Column(db.Float, nullable=False)
    saldo_anterior = db.Column(db.Float, nullable=False)
    saldo_nuevo = db.Column(db.Float, nullable=False)
    tasa_cambio = db.Column(db.Float, nullable=True)  # Para ventas USD
    remesa_id = db.Column(db.Integer, db.ForeignKey('remesas.id'), nullable=True)
    notas = db.Column(db.Text)
    fecha = db.Column(db.DateTime, default=datetime.utcnow)
    registrado_por = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)

    # Relaciones
    repartidor = db.relationship('Usuario', foreign_keys=[repartidor_id], backref='movimientos_efectivo')
    admin = db.relationship('Usuario', foreign_keys=[registrado_por])
    remesa = db.relationship('Remesa', backref='movimiento_efectivo')


class Configuracion(db.Model):
    __tablename__ = 'configuracion'

    id = db.Column(db.Integer, primary_key=True)
    clave = db.Column(db.String(50), unique=True, nullable=False)
    valor = db.Column(db.String(200), nullable=False)
    descripcion = db.Column(db.String(200))

    @staticmethod
    def obtener(clave, default=None):
        config = Configuracion.query.filter_by(clave=clave).first()
        return config.valor if config else default

    @staticmethod
    def establecer(clave, valor, descripcion=None):
        config = Configuracion.query.filter_by(clave=clave).first()
        if config:
            config.valor = valor
        else:
            config = Configuracion(clave=clave, valor=valor, descripcion=descripcion)
            db.session.add(config)
        db.session.commit()


class SuscripcionPush(db.Model):
    """Suscripciones de Push Notifications para PWA"""
    __tablename__ = 'suscripciones_push'

    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=True)
    endpoint = db.Column(db.Text, nullable=False, unique=True)
    p256dh = db.Column(db.Text, nullable=False)  # Clave publica del cliente
    auth = db.Column(db.Text, nullable=False)     # Token de autenticacion
    activa = db.Column(db.Boolean, default=True)
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)

    # Relacion con usuario (opcional, para suscripciones anonimas)
    usuario = db.relationship('Usuario', backref='suscripciones_push')
