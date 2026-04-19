import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Config:
    """Base configuration class"""
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'you-will-never-guess'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    STATIC_FOLDER = 'static'
    # MongoDB configuration
    MONGODB_URI = os.environ.get('MONGODB_URI') or 'mongodb://localhost:27017'
    MONGODB_DB = os.environ.get('MONGODB_DB') or 'maison_logs'
    # Urls de conexión para los diferentes usuarios
    ADMIN_DATABASE_URL = os.environ.get('ADMIN_DATABASE_URL')
    CHEF_DATABASE_URL = os.environ.get('CHEF_DATABASE_URL')
    VENDEDOR_DATABASE_URL = os.environ.get('VENDEDOR_DATABASE_URL')
    CLIENTE_DATABASE_URL = os.environ.get('CLIENTE_DATABASE_URL')

class DevelopmentConfig(Config):
    """Development configuration class"""
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///dev.db'

class ProductionConfig(Config):
    """Production configuration class"""
    DEBUG = False
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL')
    SESSION_COOKIE_SECURE = True
    REMEMBER_COOKIE_SECURE = True

# Dictionary to map environment names to configuration classes
config_dict: dict[str, type[Config]] = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}
