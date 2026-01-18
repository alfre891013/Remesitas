# Archivo WSGI para PythonAnywhere
import sys
import os

# Agregar el directorio del proyecto al path
project_home = '/home/alfre891013/Remesitas'
if project_home not in sys.path:
    sys.path.insert(0, project_home)

# Configurar variable de entorno para produccion
os.environ['FLASK_ENV'] = 'production'

# Importar la aplicacion
from app import crear_app

application = crear_app()
