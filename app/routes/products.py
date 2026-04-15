import math
import os
import uuid
from flask import Blueprint, render_template, request, current_app, flash, redirect, url_for
from werkzeug.utils import secure_filename
from flask_login import login_required, current_user # type: ignore
from sqlalchemy import func, or_
from app import db, user_logger
from app.decorators import roles_required
from app.models import Product

products_bp = Blueprint('products', __name__)

@products_bp.route('/')
@login_required
@roles_required('admin', 'chef', 'seller')
def index():
    raw_query = (request.args.get('q') or '').strip()
    page = request.args.get('page', 1, type=int) or 1
    per_page = request.args.get('per_page', 10, type=int) or 10

    if page < 1:
        page = 1
    if per_page < 5:
        per_page = 5
    if per_page > 50:
        per_page = 50

    base_query = db.session.query(Product).filter(Product.is_active == True)

    if raw_query:
        like = f"%{raw_query.lower()}%"
        base_query = base_query.filter(
            or_(
                func.lower(Product.nombre_producto).like(like),
                func.lower(Product.categoria).like(like),
            )
        )

    total = base_query.count()
    total_pages = max(1, math.ceil(total / per_page))
    if page > total_pages:
        page = total_pages

    products = (
        base_query.order_by(Product.nombre_producto)
        .limit(per_page)
        .offset((page - 1) * per_page)
        .all()
    )

    start_item = 0 if total == 0 else ((page - 1) * per_page + 1)
    end_item = min(total, page * per_page)

    return render_template(
        'internal/products/index.html',
        products=products,
        q=raw_query,
        page=page,
        per_page=per_page,
        total=total,
        total_pages=total_pages,
        start_item=start_item,
        end_item=end_item,
    )

@products_bp.route('/create', methods=['GET', 'POST'])
@login_required
@roles_required('admin')
def create():
    if request.method == 'POST':
        nombre_producto = (request.form.get('nombre_producto') or '').strip()
        categoria = (request.form.get('categoria') or '').strip()
        stock_str = request.form.get('stock') or '0'
        precio_venta_str = request.form.get('precio_venta') or '0'
        pedido_minimo_str = request.form.get('pedido_minimo') or '1'
        descripcion = (request.form.get('descripcion') or '').strip()
        imagen = request.files.get('imagen')

        if not nombre_producto or not categoria:
            flash('El nombre y la categoría son obligatorios.', 'error')
            return render_template('internal/products/create.html', 
                                   nombre=nombre_producto, categoria=categoria, 
                                   stock=stock_str, precio=precio_venta_str, pedido_minimo=pedido_minimo_str, descripcion=descripcion)

        try:
            stock = float(stock_str)
            precio_venta = float(precio_venta_str)
            pedido_minimo = int(pedido_minimo_str)
        except ValueError:
            flash('Stock, precio y pedido mínimo deben ser numéricos.', 'error')
            return render_template('internal/products/create.html', 
                                   nombre=nombre_producto, categoria=categoria, 
                                   stock=stock_str, precio=precio_venta_str, pedido_minimo=pedido_minimo_str, descripcion=descripcion)

        if pedido_minimo < 1:
            flash('El pedido mínimo debe ser al menos 1.', 'error')
            return render_template('internal/products/create.html', 
                                   nombre=nombre_producto, categoria=categoria, 
                                   stock=stock_str, precio=precio_venta_str, pedido_minimo=pedido_minimo_str, descripcion=descripcion)

        if not imagen or imagen.filename == '':
            flash('La imagen del producto es obligatoria.', 'error')
            return render_template('internal/products/create.html', 
                                   nombre=nombre_producto, categoria=categoria, 
                                   stock=stock_str, precio=precio_venta_str, pedido_minimo=pedido_minimo_str, descripcion=descripcion)

        try:
            upload_folder = os.path.join(current_app.root_path, 'static', 'images', 'productos')
            os.makedirs(upload_folder, exist_ok=True)
            
            filename = secure_filename(imagen.filename or '')
            ext = os.path.splitext(filename)[1].lower()
            
            allowed_extensions = {'.jpg', '.jpeg', '.png', '.gif'}
            if ext not in allowed_extensions:
                flash('Solo se permiten imágenes en formato JPG, PNG y GIF.', 'error')
                return render_template('internal/products/create.html', 
                                       nombre=nombre_producto, categoria=categoria, 
                                       stock=stock_str, precio=precio_venta_str, pedido_minimo=pedido_minimo_str, descripcion=descripcion)

            unique_filename = f"{uuid.uuid4().hex}{ext}"
            filepath = os.path.join(upload_folder, unique_filename)
            imagen.save(filepath)
            imagen_url = f"/static/images/productos/{unique_filename}"
            
            new_product = Product(
                nombre_producto=nombre_producto,
                categoria=categoria,
                precio_venta=precio_venta,
                stock=stock,
                pedido_minimo=pedido_minimo,
                descripcion=descripcion,
                imagen_url=imagen_url,
                is_active=True
            )
            
            db.session.add(new_product)
            db.session.commit()
            user_logger.log_action(
                current_user,
                module="Productos",
                action="Se creó un producto",
                success=True,
            )
            
            flash('Producto creado exitosamente.', 'success')
            return redirect(url_for('products.recipes', product_id=new_product.id))
            
        except Exception as e:
            db.session.rollback()
            flash('Ocurrió un error al guardar el producto. Intente de nuevo.', 'error')
            return render_template('internal/products/create.html', 
                                   nombre=nombre_producto, categoria=categoria, 
                                   stock=stock_str, precio=precio_venta_str, pedido_minimo=pedido_minimo_str, descripcion=descripcion)

    return render_template('internal/products/create.html')

@products_bp.route('/edit/<int:product_id>', methods=['GET', 'POST'])
@login_required
@roles_required('admin')
def edit(product_id: int):
    product = db.session.query(Product).filter_by(id=product_id, is_active=True).first()
    if not product:
        flash('Producto no encontrado.', 'error')
        return redirect(url_for('products.index'))

    if request.method == 'POST':
        nombre_producto = (request.form.get('nombre_producto') or '').strip()
        categoria = (request.form.get('categoria') or '').strip()
        stock_str = request.form.get('stock') or '0'
        precio_venta_str = request.form.get('precio_venta') or '0'
        pedido_minimo_str = request.form.get('pedido_minimo') or str(product.pedido_minimo or 1)
        descripcion = (request.form.get('descripcion') or '').strip()
        imagen = request.files.get('imagen')

        if not nombre_producto or not categoria:
            flash('El nombre y la categoría son obligatorios.', 'error')
            return redirect(url_for('products.edit', product_id=product.id))

        try:
            stock = float(stock_str)
            precio_venta = float(precio_venta_str)
            pedido_minimo = int(pedido_minimo_str)
        except ValueError:
            flash('Stock, precio y pedido mínimo deben ser numéricos.', 'error')
            return redirect(url_for('products.edit', product_id=product.id))

        if pedido_minimo < 1:
            flash('El pedido mínimo debe ser al menos 1.', 'error')
            return redirect(url_for('products.edit', product_id=product.id))

        try:
            if imagen and imagen.filename != '':
                filename = secure_filename(imagen.filename or '')
                ext = os.path.splitext(filename)[1].lower()
                
                allowed_extensions = {'.jpg', '.jpeg', '.png', '.gif'}
                if ext not in allowed_extensions:
                    flash('Solo se permiten imágenes en formato JPG, PNG y GIF.', 'error')
                    return redirect(url_for('products.edit', product_id=product.id))

                upload_folder = os.path.join(current_app.root_path, 'static', 'images', 'productos')
                os.makedirs(upload_folder, exist_ok=True)
                
                if product.imagen_url:
                    old_filename = os.path.basename(product.imagen_url)
                    old_filepath = os.path.join(upload_folder, old_filename)
                    if os.path.exists(old_filepath):
                        os.remove(old_filepath)

                unique_filename = f"{uuid.uuid4().hex}{ext}"
                filepath = os.path.join(upload_folder, unique_filename)
                
                imagen.save(filepath)
                product.imagen_url = f"/static/images/productos/{unique_filename}"
            
            product.nombre_producto = nombre_producto
            product.categoria = categoria
            product.precio_venta = precio_venta
            product.stock = stock
            product.pedido_minimo = pedido_minimo
            product.descripcion = descripcion
            
            db.session.commit()
            user_logger.log_action(
                current_user,
                module="Productos",
                action="Se actualizó un producto",
                success=True,
            )
            
            flash('Producto actualizado exitosamente.', 'success')
            return redirect(url_for('products.index'))
            
        except Exception as e:
            db.session.rollback()
            flash('Ocurrió un error al actualizar el producto. Intente de nuevo.', 'error')
            return redirect(url_for('products.edit', product_id=product.id))

    return render_template('internal/products/edit.html', product=product)

@products_bp.route('/delete/<int:product_id>', methods=['GET', 'POST'])
@login_required
@roles_required('admin')
def delete(product_id: int):
    product = db.session.query(Product).filter_by(id=product_id, is_active=True).first()
    if not product:
        flash('Producto no encontrado.', 'error')
        return redirect(url_for('products.index'))

    if request.method == 'POST':
        try:
            # Opción 1: Hard delete (podemos hacerlo soft setting is_active=False)
            product.is_active = False
            
            # Eliminación en cascada para recetas y sus detalles (Soft Delete)
            for recipe in product.recipes:
                recipe.is_active = False
                for detail in recipe.details:
                    detail.is_active = False
                    
            db.session.commit()
            user_logger.log_action(
                current_user,
                module="Productos",
                action="Se eliminó un producto",
                success=True,
            )
            
            flash('Producto eliminado exitosamente.', 'success')
            return redirect(url_for('products.index'))
        except Exception:
            db.session.rollback()
            flash('No se pudo eliminar el producto. Intente nuevamente.', 'error')
            return redirect(url_for('products.delete', product_id=product.id))

    return render_template('internal/products/delete.html', product=product)

@products_bp.route('/<int:product_id>/recipes', methods=['GET'])
@login_required
@roles_required('admin', 'chef')
def recipes(product_id: int):
    product = db.session.query(Product).filter_by(id=product_id, is_active=True).first()
    if not product:
        flash('Producto no encontrado.', 'error')
        return redirect(url_for('products.index'))

    from app.models import Insumo, Recipe, RecipeDetail, UnidadMedida
    import json
    
    insumos = db.session.query(Insumo).filter_by(is_active=True).order_by(Insumo.nombre_insumo).all()

    edit_recipe_id = request.args.get('recipe_id', type=int)
    recipe_to_edit = None
    detalle_edit = []

    if edit_recipe_id:
        recipe_to_edit = db.session.query(Recipe).filter_by(id=edit_recipe_id, product_id=product.id, is_active=True).first()
        if recipe_to_edit:
            for d in recipe_to_edit.details:
                if d.is_active:
                    unidades_permitidas = []
                    if d.insumo.unidad_base:
                        unidades_permitidas.append({
                            "id": d.insumo.unidad_base.id,
                            "nombre": d.insumo.unidad_base.nombre,
                            "abreviatura": d.insumo.unidad_base.abreviatura
                        })
                    for conv in d.insumo.conversiones:
                        if conv.is_active and conv.unidad_destino:
                            unidades_permitidas.append({
                                "id": conv.unidad_destino.id,
                                "nombre": conv.unidad_destino.nombre,
                                "abreviatura": conv.unidad_destino.abreviatura
                            })
                            
                    detalle_edit.append({
                        'insumo_id': d.insumo_id,
                        'cantidad': d.cantidad,
                        'unidad_medida_id': d.unidad_medida_id,
                        'unidades_permitidas': unidades_permitidas
                    })

    recipes_list = db.session.query(Recipe).filter_by(product_id=product.id, is_active=True).all()

    return render_template('internal/products/recipes.html', 
                           product=product,
                           insumos=insumos,
                           recipes=recipes_list,
                           recipe_to_edit=recipe_to_edit,
                           detalle_edit_json=json.dumps(detalle_edit))

@products_bp.route('/<int:product_id>/recipes/create', methods=['POST'])
@login_required
@roles_required('admin', 'chef')
def create_recipe(product_id: int):
    from app.models import Recipe, RecipeDetail
    product = db.session.query(Product).filter_by(id=product_id, is_active=True).first()
    if not product:
        flash('Producto no encontrado.', 'error')
        return redirect(url_for('products.index'))

    nombre_variante = (request.form.get('nombre_variante') or '').strip()
    cantidad_producida = float(request.form.get('cantidad_producida') or 0)
    tiempo_estimado_min = int(request.form.get('tiempo_estimado_min') or 0)

    insumo_ids = request.form.getlist('insumo_id[]')
    cantidades = request.form.getlist('cantidad[]')
    unidades = request.form.getlist('unidad_medida_id[]')

    if not nombre_variante:
        flash('Debe asignar un nombre a la variante.', 'error')
        return redirect(url_for('products.recipes', product_id=product.id))

    # Validar al menos un ingrediente
    valid_ingredients = [i for i, c, u in zip(insumo_ids, cantidades, unidades) if i and c and u]
    if not valid_ingredients:
        flash('La receta debe contener por lo menos un ingrediente.', 'error')
        return redirect(url_for('products.recipes', product_id=product.id))

    recipe = Recipe(
        product_id=product.id,
        nombre_variante=nombre_variante,
        cantidad_producida=cantidad_producida,
        tiempo_estimado_min=tiempo_estimado_min,
        is_active=True
    )
    db.session.add(recipe)
    db.session.flush()

    for i_id, cant, u_id in zip(insumo_ids, cantidades, unidades):
        if i_id and cant and u_id:
            try:
                rd = RecipeDetail(
                    recipe_id=recipe.id,
                    insumo_id=int(i_id),
                    cantidad=float(cant),
                    unidad_medida_id=int(u_id),
                    is_active=True
                )
                db.session.add(rd)
            except ValueError:
                pass

    try:
        db.session.commit()
        user_logger.log_action(
            current_user,
            module="Recetas",
            action="Se creó una receta",
            success=True,
        )
        flash('Receta creada exitosamente.', 'success')
    except Exception:
        db.session.rollback()
        flash('Ocurrió un error al crear la receta.', 'error')

    return redirect(url_for('products.recipes', product_id=product.id))

@products_bp.route('/<int:product_id>/recipes/edit/<int:recipe_id>', methods=['POST'])
@login_required
@roles_required('admin', 'chef')
def edit_recipe(product_id: int, recipe_id: int):
    from app.models import Recipe, RecipeDetail
    product = db.session.query(Product).filter_by(id=product_id, is_active=True).first()
    if not product:
        flash('Producto no encontrado.', 'error')
        return redirect(url_for('products.index'))

    recipe = db.session.query(Recipe).filter_by(id=recipe_id, product_id=product.id, is_active=True).first()
    if not recipe:
        flash('Receta no encontrada.', 'error')
        return redirect(url_for('products.recipes', product_id=product.id))

    nombre_variante = (request.form.get('nombre_variante') or '').strip()
    cantidad_producida = float(request.form.get('cantidad_producida') or 0)
    tiempo_estimado_min = int(request.form.get('tiempo_estimado_min') or 0)

    insumo_ids = request.form.getlist('insumo_id[]')
    cantidades = request.form.getlist('cantidad[]')
    unidades = request.form.getlist('unidad_medida_id[]')

    if not nombre_variante:
        flash('Debe asignar un nombre a la variante.', 'error')
        return redirect(url_for('products.recipes', product_id=product.id, recipe_id=recipe.id))

    # Validar al menos un ingrediente
    valid_ingredients = [i for i, c, u in zip(insumo_ids, cantidades, unidades) if i and c and u]
    if not valid_ingredients:
        flash('La receta debe contener por lo menos un ingrediente.', 'error')
        return redirect(url_for('products.recipes', product_id=product.id, recipe_id=recipe.id))

    recipe.nombre_variante = nombre_variante
    recipe.cantidad_producida = cantidad_producida
    recipe.tiempo_estimado_min = tiempo_estimado_min
    
    # Desactivar lógicamente todos los detalles antiguos
    for d in recipe.details:
        d.is_active = False

    # Insertar los nuevos detalles enviados en el formulario
    for i_id, cant, u_id in zip(insumo_ids, cantidades, unidades):
        if i_id and cant and u_id:
            try:
                rd = RecipeDetail(
                    recipe_id=recipe.id,
                    insumo_id=int(i_id),
                    cantidad=float(cant),
                    unidad_medida_id=int(u_id),
                    is_active=True
                )
                db.session.add(rd)
            except ValueError:
                pass

    try:
        db.session.commit()
        user_logger.log_action(
            current_user,
            module="Recetas",
            action="Se modificó una receta",
            success=True,
        )
        flash('Receta modificada exitosamente.', 'success')
    except Exception as e:
        db.session.rollback()
        flash('Ocurrió un error al modificar la receta. Detalles: ' + str(e), 'error')

    return redirect(url_for('products.recipes', product_id=product.id))

@products_bp.route('/recipes/delete/<int:recipe_id>', methods=['POST'])
@login_required
@roles_required('admin', 'chef')
def delete_recipe(recipe_id: int):
    from app.models import Recipe
    recipe = db.session.query(Recipe).filter_by(id=recipe_id, is_active=True).first()
    if not recipe:
        flash('Receta no encontrada.', 'error')
        return redirect(request.referrer or url_for('products.index'))

    product_id = recipe.product_id

    try:
        recipe.is_active = False
        for d in recipe.details:
            d.is_active = False
        db.session.commit()
        user_logger.log_action(
            current_user,
            module="Recetas",
            action="Se eliminó una receta",
            success=True,
        )
        flash('Receta eliminada exitosamente.', 'success')
    except Exception:
        db.session.rollback()
        flash('No se pudo eliminar la receta.', 'error')

    return redirect(url_for('products.recipes', product_id=product_id))