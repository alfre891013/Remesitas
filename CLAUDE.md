# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Remesitas is a Flask-based remittance platform for processing money transfers between the USA and Cuba. It supports multiple user roles (admin, distributor, reseller, public client) with financial transaction processing, commission management, and SMS/WhatsApp notifications.

## Commands

### Run Development Server
```bash
python app.py
```
Runs on `http://0.0.0.0:5000` with auto-reload. Database auto-created at `instance/remesas.db`.

### Install Dependencies
```bash
pip install -r requirements.txt
```

### Run Tests
```bash
python test_completo_sistema.py    # Full system test (recommended)
python test_balance.py             # Balance calculations
python test_repartidor.py          # Distributor functionality
python test_facturacion.py         # Billing/invoicing
python test_revendedor.py          # Reseller functionality
python test_tipos.py               # Remittance types (USD/CUP)
python test_total.py               # Total calculations
python test_aprobar.py             # Approval workflows
```
Tests are standalone scripts (not pytest). Run directly with `python <test_file>.py`.

### Production (WSGI)
Use `wsgi.py` for PythonAnywhere or similar WSGI-compatible hosting.

### Environment Variables
Configure via environment or defaults in `config.py`:
- `SECRET_KEY` - Flask session key
- `DATABASE_URL` - Database URI (default: SQLite)
- `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN` - Twilio credentials
- `TWILIO_WHATSAPP_FROM`, `TWILIO_SMS_FROM` - Twilio phone numbers
- `URL_BASE` - Base URL for tracking links

## Architecture

### Application Structure
- **app.py**: Flask application factory with `crear_app()` function
- **config.py**: Configuration and environment variables
- **models.py**: SQLAlchemy models (Usuario, Remesa, TasaCambio, Comision, MovimientoEfectivo, MovimientoContable, PagoRevendedor, Configuracion)
- **wsgi.py**: Production WSGI entry point

### Routes (Blueprint Organization)
Routes are organized by user role/feature in `routes/`:
- `auth.py` - Authentication and login flows
- `admin.py` - Admin dashboard, user management, configuration
- `remesas.py` - Core remittance operations (admin)
- `publico.py` - Public client-facing routes
- `repartidor.py` - Distributor/delivery person routes
- `revendedor.py` - Reseller/partner routes
- `reportes.py` - Reporting and analytics

### Role-Based Access Control
- **Admin**: Full system control, rate/user management, reporting
- **Repartidor (Distributor)**: Delivers cash, tracks USD/CUP inventory
- **Revendedor (Reseller)**: Creates remittances via platform, tracks commissions
- **Public Client**: Requests remittances without authentication

Protected with `@admin_required` decorator (defined in `routes/admin.py`) and Flask-Login's `@login_required`.

### Remittance Lifecycle
States: `pendiente` → `en_proceso` → `entregada` → `facturada`

### External Integrations
- **Twilio**: SMS for USA (+1 prefix), WhatsApp for Cuba (+53 prefix). Country detected via `detectar_pais()` in `notificaciones.py`
- **Exchange Rates**: Scraped from CiberCuba via `tasas_externas.py`. Supports USD, EUR, and MLC to CUP conversions
- **Notifications**: `notificaciones.py` handles country detection and messaging with fallback to manual WhatsApp links

### Background Processing
`scheduler.py` runs APScheduler for automatic exchange rate updates (every 12 hours) using BeautifulSoup web scraping. Scheduler starts automatically when running `app.py` in production mode.

### Frontend
- Jinja2 templates in `templates/` organized by role
- Bootstrap CSS with custom styles in `static/css/style.css`
- PWA support with `manifest.json` and `sw.js` (Service Worker)

### Database
SQLite (development) via SQLAlchemy. Auto-seeds initial data on first run:
- Default admin user (admin/admin123)
- Default commission (3% + $2 fixed)
- Default exchange rate (435 CUP/USD)

### File Uploads
Delivery photos saved to `static/fotos_entrega/` with format `{REMESA_CODIGO}_{TIMESTAMP}.jpg`

### API Endpoints (AJAX)
Internal JSON APIs for dynamic UI calculations:
- `/api/calcular` - Calculate remittance amounts and commissions (admin)
- `/api/buscar-remitentes`, `/api/buscar-beneficiarios` - Autocomplete searches
- `/publico/api/calcular-entrega` - Public delivery amount calculator
- `/revendedor/api/calcular` - Reseller commission calculator
- `/admin/api/tasa-externa` - Fetch external exchange rates
