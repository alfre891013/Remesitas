"""
Modulo para obtener tasas de cambio del mercado informal cubano
Referencia: https://eltoque.com/tasas-de-cambio-de-moneda-en-cuba-hoy
"""
import requests
from bs4 import BeautifulSoup
import re
from datetime import datetime

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'text/html,application/xhtml+xml',
    'Accept-Language': 'es-ES,es;q=0.9',
}

RATIO_EUR_USD = 1.05
RATIO_MLC_USD = 0.70


def obtener_tasas_cibercuba():
    """Obtiene tasas desde CiberCuba"""
    url = 'https://www.cibercuba.com/tags/cambio-moneda'

    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(response.text, 'html.parser')
        text = soup.get_text()

        tasas = {
            'fuente': 'CiberCuba',
            'fecha': datetime.now().strftime('%Y-%m-%d %H:%M')
        }

        # Buscar USD
        usd_match = re.search(r'USD\D*(\d{3,4})', text)
        if usd_match:
            tasa = float(usd_match.group(1))
            if 300 <= tasa <= 600:
                tasas['USD'] = tasa

        # Buscar EUR
        eur_match = re.search(r'EUR\D*(\d{3,4})', text)
        if eur_match:
            tasa = float(eur_match.group(1))
            if 300 <= tasa <= 700:
                tasas['EUR'] = tasa

        # Buscar MLC
        mlc_match = re.search(r'MLC\D*(\d{2,4})', text)
        if mlc_match:
            tasa = float(mlc_match.group(1))
            if 200 <= tasa <= 500:
                tasas['MLC'] = tasa

        if 'USD' in tasas:
            if 'EUR' not in tasas:
                tasas['EUR'] = round(tasas['USD'] * RATIO_EUR_USD, 2)
            if 'MLC' not in tasas:
                tasas['MLC'] = round(tasas['USD'] * RATIO_MLC_USD, 2)
            return tasas

        return None

    except Exception as e:
        print(f"Error: {e}")
        return None


def obtener_tasa_actual():
    """Retorna tasas actuales"""
    return obtener_tasas_cibercuba()


def obtener_todas_las_tasas():
    """Obtiene USD, EUR, MLC"""
    return obtener_tasa_actual()


if __name__ == '__main__':
    tasas = obtener_todas_las_tasas()
    if tasas:
        print(f"USD: {tasas.get('USD')} CUP")
        print(f"EUR: {tasas.get('EUR')} CUP")
        print(f"MLC: {tasas.get('MLC')} CUP")
        print(f"Fuente: {tasas.get('fuente')}")
    else:
        print("No se pudo obtener las tasas")
