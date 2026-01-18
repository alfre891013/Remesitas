import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'clave-secreta-remesitas-2024'
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'sqlite:///remesas.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Configuracion de monedas por defecto
    MONEDA_ORIGEN = 'USD'
    MONEDA_DESTINO = 'LOCAL'

    # Configuracion de Twilio para WhatsApp y SMS
    # Obtener de: https://console.twilio.com/
    TWILIO_ACCOUNT_SID = os.environ.get('TWILIO_ACCOUNT_SID') or 'AC57ea834fb7fbf24139b6ad9a874d6e13'
    TWILIO_AUTH_TOKEN = os.environ.get('TWILIO_AUTH_TOKEN') or '11fb7aa3d0da7c00bcd9e0aad5a53ccf'
    TWILIO_WHATSAPP_FROM = os.environ.get('TWILIO_WHATSAPP_FROM') or '+14155238886'  # Sandbox WhatsApp
    TWILIO_SMS_FROM = os.environ.get('TWILIO_SMS_FROM') or '+17869360066'  # Numero para SMS USA

    # URL base para links de seguimiento
    URL_BASE = os.environ.get('URL_BASE') or 'https://happyremesitas.com'

    # Configuracion de Push Notifications (VAPID)
    # Generar con: python -c "from py_vapid import Vapid; v=Vapid(); v.generate_keys(); print(v.private_key, v.public_key)"
    VAPID_PUBLIC_KEY = os.environ.get('VAPID_PUBLIC_KEY')
    VAPID_PRIVATE_KEY = os.environ.get('VAPID_PRIVATE_KEY')
    VAPID_EMAIL = os.environ.get('VAPID_EMAIL') or 'admin@happyremesitas.com'

    # Configuracion de UltraMsg (WhatsApp alternativo a Twilio)
    # Obtener de: https://ultramsg.com
    ULTRAMSG_INSTANCE_ID = os.environ.get('ULTRAMSG_INSTANCE_ID')
    ULTRAMSG_TOKEN = os.environ.get('ULTRAMSG_TOKEN')
