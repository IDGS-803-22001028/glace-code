import re
import base64
from io import BytesIO

import pyotp
import qrcode
from flask import Blueprint, flash, render_template, redirect, url_for, request, session
from flask_login import login_user, logout_user, current_user  # type: ignore
from app import db, user_logger
from app.models import User, Customer, UserRole

auth_bp = Blueprint('auth', __name__)


def _clear_2fa_session_state() -> None:
    for key in (
        'two_factor_pending_user_id',
        'two_factor_setup_user_id',
        'two_factor_setup_secret',
        'post_login_next',
    ):
        session.pop(key, None)


def _post_login_redirect(user: User):
    next_page = session.pop('post_login_next', None)
    if next_page:
        return redirect(next_page)
    if user.is_customer():
        return redirect(url_for('main.index'))
    if user.is_seller():
        return redirect(url_for('pos.index'))
    return redirect(url_for('main.internal'))


def _build_qr_data_uri(data: str) -> str:
    img = qrcode.make(data)
    buffer = BytesIO()
    try:
        img.save(buffer, format='PNG')
    except TypeError:
        # PyPNG backend does not accept the PIL-style 'format' keyword.
        img.save(buffer)
    encoded = base64.b64encode(buffer.getvalue()).decode('ascii')
    return f'data:image/png;base64,{encoded}'

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = User.normalize_email(request.form.get('email') or '')
        password = request.form.get('password') or ''
        next_page = request.args.get('next') or request.form.get('next')

        user = db.session.query(User).filter_by(correo_electronico=email).first()
        if user and user.is_active and user.check_password(password):
            _clear_2fa_session_state()
            if next_page:
                session['post_login_next'] = next_page

            if user.has_two_factor():
                session['two_factor_pending_user_id'] = user.id
                return redirect(url_for('auth.verify_2fa'))

            # Primera vez: fuerza configuracion de 2FA antes de permitir acceso.
            session['two_factor_setup_user_id'] = user.id
            session['two_factor_setup_secret'] = pyotp.random_base32()
            return redirect(url_for('auth.setup_2fa'))
        else:
            flash('Correo electrónico o contraseña incorrectos.', 'error')
            return redirect(url_for('auth.login'))
    
    if current_user.is_authenticated:
        if current_user.is_customer():
            return redirect(url_for('main.index'))
        elif current_user.is_seller():
            return redirect(url_for('pos.index'))
        else:
            return redirect(url_for('main.internal'))
    return render_template('login.html', next=request.args.get('next', ''))


@auth_bp.route('/2fa/setup', methods=['GET', 'POST'])
def setup_2fa():
    setup_user_id = session.get('two_factor_setup_user_id')
    setup_secret = session.get('two_factor_setup_secret')
    if not setup_user_id or not setup_secret:
        flash('Tu sesión de autenticación expiró. Inicia sesión nuevamente.', 'error')
        return redirect(url_for('auth.login'))

    user = db.session.get(User, int(setup_user_id))
    if user is None or not user.is_active:
        _clear_2fa_session_state()
        flash('No se pudo validar el usuario para configurar 2FA.', 'error')
        return redirect(url_for('auth.login'))

    totp = pyotp.TOTP(setup_secret)
    otp_uri = totp.provisioning_uri(name=user.correo_electronico, issuer_name='Maison Glace')
    qr_data_uri = _build_qr_data_uri(otp_uri)

    if request.method == 'POST':
        code = (request.form.get('code') or '').strip().replace(' ', '')
        if not totp.verify(code, valid_window=1):
            flash('Código de verificación inválido. Intenta de nuevo.', 'error')
            return render_template('setup_2fa.html', qr_data_uri=qr_data_uri, secret=setup_secret)

        user.two_factor_secret = setup_secret
        user.two_factor_enabled = True
        db.session.commit()

        _clear_2fa_session_state()
        login_user(user)

        user_logger.log_action(
            current_user=user,
            module="Autenticación",
            action="Usuario configuró 2FA e inició sesión",
            success=True,
        )

        flash('Autenticación de dos factores activada correctamente.', 'success')
        return _post_login_redirect(user)

    return render_template('setup_2fa.html', qr_data_uri=qr_data_uri, secret=setup_secret)


@auth_bp.route('/2fa/verify', methods=['GET', 'POST'])
def verify_2fa():
    pending_user_id = session.get('two_factor_pending_user_id')
    if not pending_user_id:
        flash('Tu sesión de autenticación expiró. Inicia sesión nuevamente.', 'error')
        return redirect(url_for('auth.login'))

    user = db.session.get(User, int(pending_user_id))
    if user is None or not user.is_active or not user.has_two_factor():
        _clear_2fa_session_state()
        flash('No se pudo validar el segundo factor para este usuario.', 'error')
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        code = (request.form.get('code') or '').strip().replace(' ', '')
        totp = pyotp.TOTP(user.two_factor_secret)
        if not totp.verify(code, valid_window=1):
            flash('Código de verificación inválido. Intenta de nuevo.', 'error')
            return redirect(url_for('auth.verify_2fa'))

        _clear_2fa_session_state()
        login_user(user)

        user_logger.log_action(
            current_user=user,
            module="Autenticación",
            action="Usuario verificó 2FA e inició sesión",
            success=True,
        )

        return _post_login_redirect(user)

    return render_template('verify_2fa.html')

@auth_bp.route('/logout', methods=['POST'])
def logout():
    _clear_2fa_session_state()
    logout_user()
    return redirect(url_for('main.index'))

def _is_valid_email(email: str) -> bool:
    email = (email or '').strip()
    if not email or len(email) > 150:
        return False
    # Simple, pragmatic validation; database uniqueness is enforced separately.
    return re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", email) is not None


def _is_valid_phone(phone: str) -> bool:
    phone = (phone or '').strip()
    if not phone or len(phone) > 20:
        return False
    # Allow optional leading '+' and then digits only.
    return re.match(r"^\+?[0-9]{7,20}$", phone) is not None


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        nombre_completo = (request.form.get('nombre_completo') or '').strip()
        correo_electronico = User.normalize_email(request.form.get('correo_electronico') or '')
        telefono = (request.form.get('telefono') or '').strip()
        direccion_despacho = (request.form.get('direccion_despacho') or '').strip()
        password = request.form.get('password') or ''
        confirm_password = request.form.get('confirm_password') or ''

        if not nombre_completo:
            flash('El nombre completo es obligatorio.', 'error')
            return redirect(url_for('auth.register'))

        if len(nombre_completo) > 150:
            flash('El nombre completo no puede exceder 150 caracteres.', 'error')
            return redirect(url_for('auth.register'))

        if not _is_valid_email(correo_electronico):
            flash('Ingresa un correo electrónico válido.', 'error')
            return redirect(url_for('auth.register'))

        if not telefono:
            flash('El teléfono es obligatorio.', 'error')
            return redirect(url_for('auth.register'))

        if not _is_valid_phone(telefono):
            flash('Ingresa un teléfono válido (solo números).', 'error')
            return redirect(url_for('auth.register'))

        if not direccion_despacho:
            flash('La dirección de despacho es obligatoria.', 'error')
            return redirect(url_for('auth.register'))

        if len(direccion_despacho) > 200:
            flash('La dirección de despacho no puede exceder 200 caracteres.', 'error')
            return redirect(url_for('auth.register'))

        if not password or len(password) < 8:
            flash('La contraseña debe tener al menos 8 caracteres.', 'error')
            return redirect(url_for('auth.register'))

        if password != confirm_password:
            flash('Las contraseñas no coinciden.', 'error')
            return redirect(url_for('auth.register'))

        existing_user = db.session.query(User).filter_by(correo_electronico=correo_electronico).first()
        if existing_user:
            flash('Ya existe una cuenta con ese correo electrónico.', 'error')
            return redirect(url_for('auth.register'))

        try:
            user = User(
                nombre_completo=nombre_completo,
                correo_electronico=correo_electronico,
                password=password,
                rol_asignado=UserRole.CUSTOMER,
            )
            db.session.add(user)
            db.session.flush()  # ensure user.id

            customer = Customer(
                user=user,
                telefono=telefono,
                direccion_despacho=direccion_despacho,
            )
            db.session.add(customer)
            db.session.commit()
            
            user_logger.log_action(
                current_user=user,
                module="Autenticación",
                action="Usuario se registró (Cliente)",
                success=True,
            )

            login_user(user)
            return redirect(url_for('main.index'))
        except Exception:
            db.session.rollback()
            flash('No se pudo crear la cuenta. Intenta nuevamente.', 'error')
            return redirect(url_for('auth.register'))

    if current_user.is_authenticated:
        if current_user.is_customer():
            return redirect(url_for('main.index'))
        return redirect(url_for('main.internal'))

    return render_template('register.html')