from flask_login import UserMixin  # type: ignore
from werkzeug.security import generate_password_hash, check_password_hash
from app import db, login_manager
from datetime import datetime, timedelta

class UserRole:
    ADMIN = "admin"
    CUSTOMER = "customer"
    CHEF = "chef"
    SELLER = "seller"
    SUPERADMIN = "superadmin"

    CHOICES = (ADMIN, CUSTOMER, CHEF, SELLER, SUPERADMIN)

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    nombre_completo = db.Column(db.String(150), nullable=False)
    correo_electronico = db.Column(db.String(150), unique=True, nullable=False, index=True)
    password = db.Column(db.String(255), nullable=False)
    rol_asignado = db.Column(db.String(50), nullable=False, index=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    two_factor_enabled = db.Column(db.Boolean, default=False, nullable=False, index=True)
    two_factor_secret = db.Column(db.String(64), nullable=True)

    # 1:1 relationship with Customer
    customer = db.relationship("Customer", back_populates="user", uselist=False)

    __table_args__ = (
        db.Index('ix_user_rol_asignado_is_active', 'rol_asignado', 'is_active'),
    )
    
    def __init__(self, nombre_completo: str, correo_electronico: str, password: str, rol_asignado: str, is_active: bool = True):
        self.nombre_completo = nombre_completo.strip()
        self.correo_electronico = self.normalize_email(correo_electronico)
        self.set_password(password)
        self.rol_asignado = rol_asignado.strip().lower()
        self.is_active = is_active

    def set_password(self, password: str) -> None:
        self.password = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password, password)

    def has_role(self, role: str) -> bool:
        return self.rol_asignado == role

    def is_admin(self) -> bool:
        return self.has_role(UserRole.ADMIN) or self.has_role(UserRole.SUPERADMIN)

    def is_customer(self) -> bool:
        return self.has_role(UserRole.CUSTOMER) or self.has_role(UserRole.SUPERADMIN)

    def is_chef(self) -> bool:
        return self.has_role(UserRole.CHEF) or self.has_role(UserRole.SUPERADMIN)

    def is_seller(self) -> bool:
        return self.has_role(UserRole.SELLER) or self.has_role(UserRole.SUPERADMIN)

    def is_superadmin(self) -> bool:
        return self.has_role(UserRole.SUPERADMIN)

    def has_two_factor(self) -> bool:
        return bool(self.two_factor_enabled and self.two_factor_secret)

    @staticmethod
    def normalize_email(email: str) -> str:
        return email.strip().lower()


@login_manager.user_loader  # type: ignore
def load_user(user_id: str):
    try:
        return db.session.get(User, int(user_id))
    except (TypeError, ValueError):
        return None


class Customer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), unique=True, nullable=False, index=True)
    telefono = db.Column(db.String(20))
    direccion_despacho = db.Column(db.String(200))
    puntos_acumulados = db.Column(db.Integer, default=0, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)

    user = db.relationship("User", back_populates="customer")
    
    def __init__(self, user: User, telefono: str = '', direccion_despacho: str = ''):
        self.user = user
        self.telefono = telefono.strip()
        self.direccion_despacho = direccion_despacho.strip()
        
    def nivel_cliente(self) -> str:
        if self.puntos_acumulados >= 1000:
            return "Platino"
        elif self.puntos_acumulados >= 500:
            return "Oro"
        elif self.puntos_acumulados >= 100:
            return "Plata"
        else:
            return "Bronce"

class UnidadMedida(db.Model):
    __tablename__ = 'UNIDAD_MEDIDA'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(50), nullable=False)
    abreviatura = db.Column(db.String(10))

class Insumo(db.Model):
    __tablename__ = 'INSUMO'
    id = db.Column(db.Integer, primary_key=True)
    nombre_insumo = db.Column(db.String(100), nullable=False)
    categoria = db.Column(db.String(50), index=True)
    stock_actual = db.Column(db.Float, default=0)
    stock_minimo_alerta = db.Column(db.Float, default=0)
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    unidad_base_id = db.Column(db.Integer, db.ForeignKey('UNIDAD_MEDIDA.id'), index=True)

    unidad_base = db.relationship('UnidadMedida')
    conversiones = db.relationship('ConversionUnidad', back_populates='insumo')

    @property
    def precio_estimado(self):
        """Calcula el costo promedio por unidad base con compras activas del ultimo mes."""
        now = datetime.now()
        last_month = now - timedelta(days=30)
        compras_activas = [detalle for detalle in self.compras if detalle.purchase and detalle.purchase.is_active and detalle.purchase.fecha_orden >= last_month]
        if not compras_activas:
            return 0.0

        total_costo = 0.0
        total_cantidad_base = 0.0
        for detalle in compras_activas:
            cantidad_base = detalle.cantidad_en_unidad_base()
            if cantidad_base is None or cantidad_base <= 0:
                continue

            total_costo += detalle.cantidad * detalle.precio_unitario
            total_cantidad_base += cantidad_base

        if total_cantidad_base <= 0:
            return 0.0

        return round(total_costo / total_cantidad_base, 6)

class ConversionUnidad(db.Model):
    __tablename__ = 'CONVERSION_UNIDAD'
    id = db.Column(db.Integer, primary_key=True)
    factor_conversion = db.Column(db.Float)
    insumo_id = db.Column(db.Integer, db.ForeignKey('INSUMO.id'), index=True)
    unidad_destino_id = db.Column(db.Integer, db.ForeignKey('UNIDAD_MEDIDA.id'), index=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)

    insumo = db.relationship('Insumo', back_populates='conversiones')
    unidad_destino = db.relationship('UnidadMedida')
    
class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre_producto = db.Column(db.String(100), nullable=False)
    categoria = db.Column(db.String(50), index=True)
    precio_venta = db.Column(db.Float, default=0)
    stock = db.Column(db.Integer, default=0)
    pedido_minimo = db.Column(db.Integer, default=1, nullable=False)
    imagen_url = db.Column(db.String(200))
    descripcion = db.Column(db.String(200))
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)

    recipes = db.relationship('Recipe', back_populates='product')

    @property
    def costo_produccion_estimado(self):
        """Calcula el costo promedio de producción basado en todas sus recetas activas."""
        # Obtenemos recetas activas
        active_recipes = [r for r in self.recipes if r.is_active]
        if not active_recipes:
            return 0.0

        num_recipes = len(active_recipes)
        # Diccionario para acumular (cantidad_base / rendimiento) por cada insumo
        insumos_acumulados = {}  # insumo_id -> float

        for recipe in active_recipes:
            # Si cantidad_producida es 0 o None, evitamos división por cero usando 1.0 como fallback
            rendimiento = recipe.cantidad_producida if recipe.cantidad_producida and recipe.cantidad_producida > 0 else 1.0
            
            for detail in recipe.details:
                if not detail.is_active:
                    continue
                
                cant_base = detail.cantidad_en_unidad_base()
                if cant_base is None:
                    continue
                
                # Cantidad de este insumo necesaria para producir 1 unidad del producto en esta receta
                cant_unitaria = cant_base / rendimiento
                insumos_acumulados[detail.insumo_id] = insumos_acumulados.get(detail.insumo_id, 0.0) + cant_unitaria

        total_cost = 0.0
        for insumo_id, suma_cantidades in insumos_acumulados.items():
            # Promediamos la cantidad unitaria entre todas las recetas disponibles del producto
            # (Si una receta no tiene el insumo, suma 0 al total, lo cual es correcto para el promedio)
            avg_qty = suma_cantidades / num_recipes
            
            # Buscamos el insumo para usar su precio_estimado
            insumo_obj = db.session.get(Insumo, insumo_id)
            if insumo_obj:
                total_cost += avg_qty * insumo_obj.precio_estimado

        return round(total_cost, 2)

class Recipe(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), index=True)
    nombre_variante = db.Column(db.String(100), nullable=False)
    cantidad_producida = db.Column(db.Float, default=0)
    tiempo_estimado_min = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)

    product = db.relationship('Product', back_populates='recipes')
    details = db.relationship('RecipeDetail', back_populates='recipe')

class RecipeDetail(db.Model):
    recipe_id = db.Column(db.Integer, db.ForeignKey('recipe.id'), primary_key=True)
    insumo_id = db.Column(db.Integer, db.ForeignKey('INSUMO.id'), primary_key=True, index=True)
    cantidad = db.Column(db.Float, default=0)
    unidad_medida_id = db.Column(db.Integer, db.ForeignKey('UNIDAD_MEDIDA.id'), index=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)

    recipe = db.relationship('Recipe', back_populates='details')
    insumo = db.relationship('Insumo')
    unidad_medida = db.relationship('UnidadMedida')

    def cantidad_en_unidad_base(self):
        """Convierte la cantidad del detalle a la unidad base del insumo."""
        if not self.insumo or not self.unidad_medida_id:
            return None
            
        # Caso 1 – ya está en la unidad base
        if self.unidad_medida_id == self.insumo.unidad_base_id:
            return self.cantidad

        # Caso 2 – buscar en las conversiones del insumo
        for conv in self.insumo.conversiones:
            if conv.is_active and conv.unidad_destino_id == self.unidad_medida_id:
                if conv.factor_conversion and conv.factor_conversion != 0:
                    return self.cantidad / conv.factor_conversion
        
        return None
    
class Merma(db.Model):
    __tablename__ = 'MERMA'
    id = db.Column(db.Integer, primary_key=True)
    insumo_id = db.Column(db.Integer, db.ForeignKey('INSUMO.id'), index=True)
    producto_id = db.Column(db.Integer, db.ForeignKey('product.id'), index=True)
    cantidad_perdida = db.Column(db.Float, nullable=False)
    causa = db.Column(db.String(255))
    notas_adicionales = db.Column(db.Text)
    fecha_registro = db.Column(db.DateTime, default=lambda: datetime.now(), index=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    
    insumo = db.relationship('Insumo', backref='mermas_registradas')
    producto = db.relationship('Product')

    __table_args__ = (
        db.Index('ix_merma_is_active_fecha_registro', 'is_active', 'fecha_registro'),
    )

class ProductionTask(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    receta_id = db.Column(db.Integer, db.ForeignKey('recipe.id'), nullable=False, index=True)
    
    # Estados del diseño: 'Pendiente', 'En Horno', 'Decorando', 'Listo'
    estado = db.Column(db.String(20), default='Pendiente', index=True)
    
    # Prioridades: 'Baja', 'Media', 'Alta'
    prioridad = db.Column(db.String(10), default='Media', index=True)
    
    fecha_limite = db.Column(db.DateTime, nullable=False, index=True)
    fecha_creacion = db.Column(db.DateTime, default=lambda: datetime.now())
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)

    # Relación para obtener el nombre del producto, tiempo estimado y cantidad a producir
    receta = db.relationship('Recipe')

    __table_args__ = (
        db.Index('ix_production_task_prioridad_is_active_fecha_limite', 'prioridad', 'is_active', 'fecha_limite'),
    )

class Venta(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=True, index=True)
    fecha_hora = db.Column(db.DateTime, default=datetime.now, index=True)
    metodo_pago = db.Column(db.String(50))  # efectivo o tarjeta
    monto_recibido = db.Column(db.Float, default=0)
    monto_cambio = db.Column(db.Float, default=0)
    
    # Datos de entrega
    lugar_entrega = db.Column(db.String(50)) # 'Tienda' o 'Domicilio'
    fecha_hora_entrega = db.Column(db.DateTime)
    
    # Seguimiento del pedido
    # Estados del pedido: 'Pendiente', 'En Producción', 'Listo', 'Entregado', 'Cancelado'
    estado = db.Column(db.String(20), default='Pendiente', index=True)
    
    # Relaciones
    detalles = db.relationship('DetalleVenta', backref='venta', lazy=True, cascade='all, delete-orphan')
    cliente = db.relationship('Customer')

    @property
    def total(self):
        return sum(d.cantidad * d.precio_unitario_aplicado for d in self.detalles)


class DetalleVenta(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    venta_id = db.Column(db.Integer, db.ForeignKey('venta.id'), nullable=False, index=True)
    producto_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False, index=True)
    cantidad = db.Column(db.Integer, nullable=False)
    precio_unitario_aplicado = db.Column(db.Float, nullable=False)
    
    # Relación 1:1 con la personalización del postre
    producto = db.relationship('Product')
    custom_order = db.relationship('CustomOrder', backref='detalle_venta', uselist=False, cascade='all, delete-orphan')

class CustomOrder(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    detalle_venta_id = db.Column(db.Integer, db.ForeignKey('detalle_venta.id'), nullable=False, unique=True)
    
    tipo_evento = db.Column(db.String(50), nullable=False)
    instrucciones_decoracion = db.Column(db.Text, nullable=False)
    
    def __init__(self, tipo_evento, instrucciones_decoracion):
        self.tipo_evento = tipo_evento
        self.instrucciones_decoracion = instrucciones_decoracion.strip()

class Supplier(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre_empresa = db.Column(db.String(100), nullable=False)
    categoria_insumos = db.Column(db.String(50), nullable=False, index=True)
    nombre_contacto = db.Column(db.String(100), nullable=False)
    telefono = db.Column(db.String(20), nullable=False)
    correo_electronico = db.Column(db.String(100), nullable=False)
    direccion_fisica = db.Column(db.String(200))
    notas_adicionales = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)

    purchases = db.relationship('Purchase', back_populates='supplier')
    
class Purchase(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'), nullable=False, index=True)
    fecha_orden = db.Column(db.DateTime, default=datetime.now, index=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)

    supplier = db.relationship('Supplier', back_populates='purchases')
    detalles = db.relationship('PurchaseDetail', back_populates='purchase', cascade='all, delete-orphan')

    __table_args__ = (
        db.Index('ix_purchase_is_active_supplier_id', 'is_active', 'supplier_id'),
    )

    @property
    def proveedor_nombre(self):
        return self.supplier.nombre_empresa if self.supplier else 'Sin proveedor'

    @property
    def total(self):
        return sum(d.cantidad * d.precio_unitario for d in self.detalles)
    
class PurchaseDetail(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    purchase_id = db.Column(db.Integer, db.ForeignKey('purchase.id'), nullable=False, index=True)
    insumo_id = db.Column(db.Integer, db.ForeignKey('INSUMO.id'), nullable=False, index=True)
    cantidad = db.Column(db.Float, nullable=False)
    precio_unitario = db.Column(db.Float, nullable=False)
    unidad_medida_id = db.Column(db.Integer, db.ForeignKey('UNIDAD_MEDIDA.id'), nullable=False, index=True)

    purchase = db.relationship('Purchase', back_populates='detalles')
    insumo = db.relationship('Insumo', backref='compras')
    unidad_medida = db.relationship('UnidadMedida')

    def cantidad_en_unidad_base(self):
        """Convierte la cantidad comprada a la unidad base del insumo."""
        if not self.insumo or not self.unidad_medida_id:
            return None
            
        # Caso 1 – ya está en la unidad base
        if self.unidad_medida_id == self.insumo.unidad_base_id:
            return self.cantidad

        # Caso 2 – buscar en las conversiones del insumo
        for conv in self.insumo.conversiones:
            if conv.is_active and conv.unidad_destino_id == self.unidad_medida_id:
                if conv.factor_conversion and conv.factor_conversion != 0:
                    return self.cantidad / conv.factor_conversion
        
        return None
