from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user  # type: ignore
from app.decorators import roles_required
from app import db, user_logger
from app.models import ProductionTask, Recipe, Product, RecipeDetail, Insumo
from datetime import datetime, timezone

production_bp = Blueprint('production', __name__)


def _to_base_units(detail: RecipeDetail) -> tuple[float | None, str | None]:
    """
    Convierte la cantidad requerida por un detalle de receta a la unidad base del insumo.
    """
    cantidad_base = detail.cantidad_en_unidad_base()
    
    if cantidad_base is not None:
        return cantidad_base, None
    
    # Si falla la conversión, armamos el mensaje de error
    insumo = detail.insumo
    unidad_receta = detail.unidad_medida.abreviatura if detail.unidad_medida else f"id={detail.unidad_medida_id}"
    unidad_base = insumo.unidad_base.abreviatura if insumo.unidad_base else f"id={insumo.unidad_base_id}"
    
    return None, (
        f"No se encontró conversión para '{insumo.nombre_insumo}': "
        f"{unidad_receta} → {unidad_base}. "
        f"Verifica las conversiones del insumo."
    )


@production_bp.route('/')
@login_required
@roles_required('chef', 'seller')
def index():
    """Muestra todas las órdenes de producción agrupadas por prioridad."""
    tasks_alta = (
        ProductionTask.query
        .filter_by(prioridad='Alta', is_active=True)
        .order_by(ProductionTask.fecha_limite.asc())
        .all()
    )
    tasks_media = (
        ProductionTask.query
        .filter_by(prioridad='Media', is_active=True)
        .order_by(ProductionTask.fecha_limite.asc())
        .all()
    )
    tasks_baja = (
        ProductionTask.query
        .filter_by(prioridad='Baja', is_active=True)
        .order_by(ProductionTask.fecha_limite.asc())
        .all()
    )
    return render_template(
        'internal/production/index.html',
        tasks_alta=tasks_alta,
        tasks_media=tasks_media,
        tasks_baja=tasks_baja,
    )


@production_bp.route('/create', methods=['GET', 'POST'])
@login_required
@roles_required('seller')
def create():
    """Crea una nueva orden de producción, valida insumos y descuenta stock."""
    products = (
        Product.query
        .filter_by(is_active=True)
        .order_by(Product.nombre_producto)
        .all()
    )

    if request.method == 'POST':
        recipe_id = request.form.get('recipe_id', type=int)
        prioridad = request.form.get('prioridad', 'Media')
        fecha_limite_str = request.form.get('fecha_limite', '').strip()

        # --- Validaciones básicas ---
        if not recipe_id:
            flash('Debes seleccionar una receta válida.', 'danger')
            return redirect(url_for('production.create'))

        if prioridad not in ('Alta', 'Media', 'Baja'):
            flash('Prioridad inválida.', 'danger')
            return redirect(url_for('production.create'))

        if not fecha_limite_str:
            flash('La fecha y hora límite son obligatorias.', 'danger')
            return redirect(url_for('production.create'))

        try:
            fecha_limite = datetime.strptime(fecha_limite_str, '%Y-%m-%dT%H:%M')
            fecha_limite = fecha_limite.replace(tzinfo=timezone.utc)
        except ValueError:
            flash('Formato de fecha inválido.', 'danger')
            return redirect(url_for('production.create'))

        # --- Cargar receta ---
        recipe = db.session.query(Recipe).filter_by(id=recipe_id, is_active=True).first()
        if not recipe:
            flash('La receta seleccionada no existe o ya no está disponible.', 'danger')
            return redirect(url_for('production.create'))
        cantidad_ordenes = request.form.get('cantidad_ordenes', type=int, default=1)
        if cantidad_ordenes is None or cantidad_ordenes < 1:
            flash('La cantidad de órdenes debe ser al menos 1.', 'danger')
            return redirect(url_for('production.create'))
        # --- Validar insumos suficientes (con conversión de unidades) ---
        # Primero calculamos cuánto se necesita de cada insumo en su unidad base
        # para poder comparar contra stock_actual (que siempre está en unidad base).
        deductions: list[tuple[Insumo, float]] = []  # (insumo, cantidad_en_base_a_descontar)

        conversion_errors: list[str] = []
        stock_errors: list[str] = []

        for detail in recipe.details:
            if not detail.is_active:
                continue

            cantidad_base, err = _to_base_units(detail)
            insumo: Insumo = detail.insumo

            if err:
                conversion_errors.append(err)
                continue

            cantidad_base_total = cantidad_base * cantidad_ordenes
            cantidad_detalle_total = detail.cantidad * cantidad_ordenes
            unidad_base_abr = insumo.unidad_base.abreviatura if insumo.unidad_base else ''
            unidad_detalle_abr = detail.unidad_medida.abreviatura if detail.unidad_medida else ''

            if insumo.stock_actual < cantidad_base_total:
                stock_errors.append(
                    f"{insumo.nombre_insumo}: necesita {cantidad_detalle_total} {unidad_detalle_abr} "
                    f"({cantidad_base_total:.4g} {unidad_base_abr}), "
                    f"stock disponible: {insumo.stock_actual} {unidad_base_abr}"
                )
            else:
                deductions.append((insumo, cantidad_base_total))

        if conversion_errors:
            for msg in conversion_errors:
                flash(f'Error de configuración: {msg}', 'danger')
            return redirect(url_for('production.create'))

        if stock_errors:
            for msg in stock_errors:
                flash(f'Insumo insuficiente: {msg}', 'warning')
            flash('No se puede crear la orden: faltan insumos en inventario.', 'danger')
            return redirect(url_for('production.create'))

        # --- Descontar stock de insumos (en unidades base) ---
        try:
            for insumo_obj, cantidad_base in deductions:
                insumo_obj.stock_actual -= cantidad_base

            # --- Crear las tareas de producción ---
            for _ in range(cantidad_ordenes):
                nueva_tarea = ProductionTask(
                    receta_id=recipe_id,
                    estado='Pendiente',
                    prioridad=prioridad,
                    fecha_limite=fecha_limite,
                )
                db.session.add(nueva_tarea)

            db.session.commit()
            user_logger.log_action(
                current_user,
                module="Producción",
                action="Se creó una tarea de producción",
                success=True,
            )

            if cantidad_ordenes == 1:
                flash(
                    f'Orden de producción creada: {recipe.product.nombre_producto if recipe.product else ""} '
                    f'– {recipe.nombre_variante}. Se actualizó el inventario.',
                    'success'
                )
            else:
                flash(
                    f'Se crearon {cantidad_ordenes} órdenes de producción: {recipe.product.nombre_producto if recipe.product else ""} '
                    f'– {recipe.nombre_variante}. Se actualizó el inventario.',
                    'success'
                )
            return redirect(url_for('production.index'))

        except Exception as e:
            db.session.rollback()
            flash(f'Error al crear la orden: {str(e)}', 'danger')
            return redirect(url_for('production.create'))

    return render_template('internal/production/create.html', products=products)


@production_bp.route('/api/products/<int:product_id>/recipes', methods=['GET'])
@login_required
@roles_required('seller')
def api_product_recipes(product_id: int):
    """Devuelve en JSON las recetas activas de un producto (para el select dinámico)."""
    product = db.session.query(Product).filter_by(id=product_id, is_active=True).first()
    if not product:
        return jsonify({'error': 'Producto no encontrado'}), 404

    recipes = [
        {
            'id': r.id,
            'nombre_variante': r.nombre_variante,
            'cantidad_producida': r.cantidad_producida,
            'tiempo_estimado_min': r.tiempo_estimado_min,
        }
        for r in product.recipes
        if r.is_active
    ]
    return jsonify({'recipes': recipes})


@production_bp.route('/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@roles_required('seller')
def edit(id: int):
    task = db.session.get(ProductionTask, id)
    if not task or not task.is_active:
        flash('Orden de producción no encontrada.', 'danger')
        return redirect(url_for('production.index'))

    if request.method == 'POST':
        prioridad = request.form.get('prioridad', 'Media')
        fecha_limite_str = request.form.get('fecha_limite', '').strip()

        if prioridad not in ('Alta', 'Media', 'Baja'):
            flash('Prioridad inválida.', 'danger')
            return redirect(url_for('production.edit', id=id))

        if not fecha_limite_str:
            flash('La fecha y hora límite son obligatorias.', 'danger')
            return redirect(url_for('production.edit', id=id))

        try:
            fecha_limite = datetime.strptime(fecha_limite_str, '%Y-%m-%dT%H:%M')
            fecha_limite = fecha_limite.replace(tzinfo=timezone.utc)
        except ValueError:
            flash('Formato de fecha inválido.', 'danger')
            return redirect(url_for('production.edit', id=id))

        try:
            task.prioridad = prioridad
            task.fecha_limite = fecha_limite
            db.session.commit()
            user_logger.log_action(
                current_user,
                module="Producción",
                action="Se editó una tarea de producción",
                success=True,
            )
            flash('Orden de producción actualizada correctamente.', 'success')
            return redirect(url_for('production.index'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error al actualizar: {str(e)}', 'danger')
            return redirect(url_for('production.edit', id=id))

    return render_template('internal/production/edit.html', task=task)


@production_bp.route('/delete/<int:id>', methods=['GET', 'POST'])
@login_required
@roles_required('seller')
def delete(id: int):
    task = db.session.get(ProductionTask, id)
    if not task or not task.is_active:
        flash('Orden de producción no encontrada.', 'danger')
        return redirect(url_for('production.index'))

    if task.estado != 'Pendiente':
        flash(f'No es posible eliminar porque está en estado {task.estado}.', 'warning')
        return redirect(url_for('production.index'))

    if request.method == 'POST':
        try:
            # --- Restaurar stock de insumos (conversión a unidad base) ---
            restore_errors: list[str] = []
            for detail in task.receta.details:
                if not detail.is_active:
                    continue
                cantidad_base, err = _to_base_units(detail)
                if err:
                    restore_errors.append(err)
                    continue
                detail.insumo.stock_actual += cantidad_base

            if restore_errors:
                for msg in restore_errors:
                    flash(f'Advertencia al restaurar: {msg}', 'warning')

            # --- Soft delete ---
            task.is_active = False
            db.session.commit()
            user_logger.log_action(
                current_user,
                module="Producción",
                action="Se eliminó una tarea de producción",
                success=True,
            )

            flash('Orden eliminada y existencias de insumos restauradas.', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Error al eliminar: {str(e)}', 'danger')
        return redirect(url_for('production.index'))

    return render_template('internal/production/delete.html', task=task)


@production_bp.route('/view/<int:id>')
@login_required
@roles_required('chef')
def view(id: int):
    task = db.session.get(ProductionTask, id)
    if not task or not task.is_active:
        flash('Orden de producción no encontrada.', 'danger')
        return redirect(url_for('production.index'))
    return render_template('internal/production/view.html', task=task)


@production_bp.route('/status/<int:id>', methods=['GET', 'POST'])
@login_required
@roles_required('chef')
def status(id: int):
    task = db.session.get(ProductionTask, id)
    if not task or not task.is_active:
        flash('Orden de producción no encontrada.', 'danger')
        return redirect(url_for('production.index'))

    estados_validos = ('Pendiente', 'En Horno', 'Decorando', 'Listo')

    if request.method == 'POST':
        nuevo_estado = request.form.get('estado', '').strip()
        if nuevo_estado not in estados_validos:
            flash('Estado inválido.', 'danger')
            return redirect(url_for('production.status', id=id))

        try:
            if nuevo_estado == 'Listo':
                # --- Marcar como completada ---
                # 1. Incrementar stock del producto producido
                if task.receta and task.receta.product:
                    task.receta.product.stock += int(task.receta.cantidad_producida)

                # 2. Soft-delete de la tarea
                task.is_active = False

                db.session.commit()
                user_logger.log_action(
                    current_user,
                    module="Producción",
                    action=f"Se completó la tarea de producción {id}",
                    success=True,
                )

                nombre = task.receta.product.nombre_producto if task.receta and task.receta.product else 'Producto'
                cantidad = int(task.receta.cantidad_producida) if task.receta else 0
                flash(
                    f'Orden completada: se añadieron {cantidad} unidades de {nombre} al inventario.',
                    'success'
                )
            else:
                task.estado = nuevo_estado
                db.session.commit()
                user_logger.log_action(
                    current_user,
                    module="Producción",
                    action=f"Se actualizó estado de tarea de producción {id} a {nuevo_estado}",
                    success=True,
                )
                flash(f'Estado actualizado a "{nuevo_estado}".', 'success')

            return redirect(url_for('production.index'))

        except Exception as e:
            db.session.rollback()
            flash(f'Error al actualizar estado: {str(e)}', 'danger')
            return redirect(url_for('production.status', id=id))

    return render_template('internal/production/status.html', task=task, estados=estados_validos)
