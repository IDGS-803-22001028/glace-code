import os
from flask import Flask, render_template, request, url_for
from flask_wtf.csrf import CSRFProtect
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager # type: ignore
from config import config_dict
from app.mongo import mongo
from app.logger import UserLogger

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
user_logger = UserLogger()  # Intialized directly, uses mongo plugin
csrf = CSRFProtect()

def create_app():
    app = Flask(__name__)
    
    # Load configuration based on the FLASK_ENV environment variable
    env = os.environ.get('FLASK_ENV', 'default')
    app.config.from_object(config_dict[env])
    
    # Initialize Flask-SQLAlchemy
    db.init_app(app)
    
    # Initialize Flask-Migrate
    migrate.init_app(app, db)
    
    # Initialize Flask-Login
    login_manager.login_view = 'auth.login'  # type: ignore
    login_manager.init_app(app) # type: ignore

    # Initialize CSRF
    csrf.init_app(app)
    
    # Initialize MongoDB
    mongo.init_app(app)

    # Register blueprints
    from app.routes.main import main_bp
    app.register_blueprint(main_bp)
    from app.routes.auth import auth_bp
    app.register_blueprint(auth_bp, url_prefix='/auth')
    from app.routes.supplies import supplies_bp
    app.register_blueprint(supplies_bp, url_prefix='/supplies')
    from app.routes.products import products_bp
    app.register_blueprint(products_bp, url_prefix='/products')
    from app.routes.pos import pos_bp
    app.register_blueprint(pos_bp, url_prefix='/pos')
    from app.routes.orders import orders_bp
    app.register_blueprint(orders_bp, url_prefix='/orders')
    from app.routes.customers import customers_bp
    app.register_blueprint(customers_bp, url_prefix='/customers')
    from app.routes.production import production_bp
    app.register_blueprint(production_bp, url_prefix='/production')
    from app.routes.suppliers import suppliers_bp
    app.register_blueprint(suppliers_bp, url_prefix='/suppliers')
    from app.routes.reports import reports_bp
    app.register_blueprint(reports_bp, url_prefix='/reports')
    from app.routes.users import users_bp
    app.register_blueprint(users_bp, url_prefix='/users')
    from app.routes.losses import losses_bp
    app.register_blueprint(losses_bp, url_prefix='/losses')
    from app.routes.purchases import compras_bp
    app.register_blueprint(compras_bp, url_prefix='/purchases')
    from app.routes.configuration import configuration_bp
    app.register_blueprint(configuration_bp, url_prefix='/configuration')
    
    @app.errorhandler(403)
    def forbidden(_): # type: ignore
        return render_template('403.html'), 403
    @app.errorhandler(404)
    def page_not_found(_): # type: ignore
        return render_template('404.html'), 404
        
    @app.context_processor
    def inject_config():
        from app.mongo import mongo
        config = {}
        if mongo.db is not None:
            config = mongo.db['configuration'].find_one({'_id': 'main_config'}) or {}

        def resolve_product_image(image_url: str | None) -> str:
            fallback = url_for('static', filename='images/dessert-1.png')
            if not image_url:
                return fallback

            raw = str(image_url).strip()
            if raw.startswith(('http://', 'https://', 'data:')):
                return raw

            if raw.startswith('/static/'):
                relative = raw[len('/static/'):]
            elif raw.startswith('static/'):
                relative = raw[len('static/'):]
            else:
                relative = raw.lstrip('/')

            relative = relative.replace('\\', '/')
            parts = [p for p in relative.split('/') if p]
            if not parts or any(p == '..' for p in parts):
                return fallback

            static_root = app.static_folder or os.path.join(app.root_path, 'static')
            file_path = os.path.join(static_root, *parts)
            if os.path.isfile(file_path):
                return url_for('static', filename='/'.join(parts))

            return fallback

        return dict(sys_config=config, resolve_product_image=resolve_product_image)

    @app.after_request
    def add_no_cache_headers(response):
        # Prevent browser back-button from showing stale protected pages.
        if request.endpoint != 'static':
            response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0, private'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '0'
        return response
    
    return app