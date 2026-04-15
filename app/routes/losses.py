from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user # type: ignore
from app.decorators import roles_required
from sqlalchemy import or_, cast, String
from app import db, user_logger
from app.models import Merma, Insumo, Product

losses_bp = Blueprint('losses', __name__)

@losses_bp.route('/')
@login_required
@roles_required('chef')
def index():
    page = request.args.get('page', 1, type=int)
    query_param = request.args.get('q', '').strip()
    
    base_query = Merma.query.outerjoin(Insumo).outerjoin(Product).filter(Merma.is_active == True)
    
    if query_param:
        # Creamos el filtro de búsqueda
        search_filter = or_(
            Insumo.nombre_insumo.ilike(f'%{query_param}%'),
            Product.nombre_producto.ilike(f'%{query_param}%'),
            Merma.causa.ilike(f'%{query_param}%'),
            # Convertimos la fecha a string genérico para evitar errores entre SQLite y MySQL
            cast(Merma.fecha_registro, String).ilike(f'%{query_param}%')
        )
        base_query = base_query.filter(search_filter)
    
    mermas_obj = base_query.order_by(Merma.fecha_registro.desc()).paginate(
        page=page, per_page=8, error_out=False
    )
    
    return render_template('internal/losses/Mermas.html', mermas_obj=mermas_obj)

@losses_bp.route('/nueva', methods=['GET', 'POST'])
@login_required
@roles_required('chef')
def nueva_merma():
    if request.method == 'POST':
        item_type = request.form.get('item_type', 'insumo')
        cantidad = float(request.form.get('cantidad_perdida') or 0)
        causa = request.form.get('causa')
        notas = request.form.get('notas_adicionales')

        try:
            insumo_id = None
            producto_id = None

            if item_type == 'producto':
                producto_id_raw = request.form.get('producto_id')
                if not producto_id_raw:
                    flash('Selecciona un producto terminado para la merma.', 'error')
                    return redirect(url_for('losses.nueva_merma'))

                producto_id = int(producto_id_raw)
                producto = Product.query.get(producto_id)
                if not producto:
                    flash('Producto terminado no encontrado.', 'error')
                    return redirect(url_for('losses.nueva_merma'))

                if cantidad > producto.stock:
                    flash(f"No puedes mermar más unidades ({cantidad}) de las que hay disponibles ({producto.stock}) para este producto.", "error")
                    return redirect(url_for('losses.nueva_merma'))

                producto.stock -= cantidad
                if producto.stock < 0:
                    producto.stock = 0
            else:
                insumo_id_raw = request.form.get('insumo_id')
                if not insumo_id_raw:
                    flash('Selecciona un insumo para la merma.', 'error')
                    return redirect(url_for('losses.nueva_merma'))

                insumo_id = int(insumo_id_raw)
                insumo = Insumo.query.get(insumo_id)
                if not insumo:
                    flash('Insumo no encontrado.', 'error')
                    return redirect(url_for('losses.nueva_merma'))

                if cantidad > insumo.stock_actual:
                    flash(f"No puedes mermar más unidades ({cantidad}) de las que hay disponibles ({insumo.stock_actual}).", "error")
                    return redirect(url_for('losses.nueva_merma'))

                insumo.stock_actual -= cantidad
                if insumo.stock_actual < 0:
                    insumo.stock_actual = 0 

            nueva = Merma(
                insumo_id=insumo_id,
                producto_id=producto_id,
                cantidad_perdida=cantidad,
                causa=causa,
                notas_adicionales=notas
            )

            db.session.add(nueva)
            db.session.commit()
            user_logger.log_action(
                current_user,
                module="Mermas",
                action="Se registró una nueva merma",
                success=True,
            )
            flash("Merma registrada satisfactoriamente.", "success")
            return redirect(url_for('losses.index'))
            
        except Exception as e:
            db.session.rollback()
            print(f"Error al registrar merma: {e}")
            flash(f"Error al registrar merma: {e}", "error")
            return redirect(url_for('losses.nueva_merma'))

    insumos = Insumo.query.all()
    productos = Product.query.filter(Product.is_active == True).order_by(Product.nombre_producto).all()
    return render_template('internal/losses/Registrar.html', insumos=insumos, productos=productos)

@losses_bp.route('/modificar/<int:id>', methods=['GET', 'POST'])
@login_required
@roles_required('chef')
def modificar_merma(id):
    merma_actual = Merma.query.filter_by(id=id, is_active=True).first_or_404()
    insumos = Insumo.query.all()
    productos = Product.query.order_by(Product.nombre_producto).all()
    
    if request.method == 'POST':
        try:
            cantidad_anterior = merma_actual.cantidad_perdida
            
            if merma_actual.insumo_id:
                insumo_anterior = Insumo.query.get(merma_actual.insumo_id)
                if insumo_anterior:
                    insumo_anterior.stock_actual += cantidad_anterior

            if merma_actual.producto_id:
                producto_anterior = Product.query.get(merma_actual.producto_id)
                if producto_anterior:
                    producto_anterior.stock += cantidad_anterior

            item_type = request.form.get('item_type', 'insumo')
            nuevo_insumo_id = None
            nuevo_producto_id = None
            nueva_cantidad = float(request.form.get('cantidad_perdida') or 0)

            if item_type == 'producto':
                nuevo_producto_id_raw = request.form.get('producto_id')
                if not nuevo_producto_id_raw:
                    flash('Selecciona un producto terminado para la merma.', 'error')
                    return redirect(url_for('losses.modificar_merma', id=merma_actual.id))

                nuevo_producto_id = int(nuevo_producto_id_raw)
                producto_nuevo = Product.query.get(nuevo_producto_id)
                if not producto_nuevo:
                    flash('Producto terminado no encontrado.', 'error')
                    return redirect(url_for('losses.modificar_merma', id=merma_actual.id))

                if nueva_cantidad > producto_nuevo.stock:
                    db.session.rollback()
                    flash(f"No puedes mermar más unidades ({nueva_cantidad}) de las que hay disponibles ({producto_nuevo.stock}) para este producto.", "error")
                    return redirect(url_for('losses.modificar_merma', id=merma_actual.id))

                producto_nuevo.stock -= nueva_cantidad
                if producto_nuevo.stock < 0:
                    producto_nuevo.stock = 0
            else:
                nuevo_insumo_id_raw = request.form.get('insumo_id')
                if not nuevo_insumo_id_raw:
                    flash('Selecciona un insumo para la merma.', 'error')
                    return redirect(url_for('losses.modificar_merma', id=merma_actual.id))

                nuevo_insumo_id = int(nuevo_insumo_id_raw)
                insumo_nuevo = Insumo.query.get(nuevo_insumo_id)
                if not insumo_nuevo:
                    flash('Insumo no encontrado.', 'error')
                    return redirect(url_for('losses.modificar_merma', id=merma_actual.id))

                if nueva_cantidad > insumo_nuevo.stock_actual:
                    db.session.rollback()
                    flash(f"No puedes mermar más unidades ({nueva_cantidad}) de las que hay disponibles ({insumo_nuevo.stock_actual}) para este insumo.", "error")
                    return redirect(url_for('losses.modificar_merma', id=merma_actual.id))

                insumo_nuevo.stock_actual -= nueva_cantidad
                if insumo_nuevo.stock_actual < 0:
                    insumo_nuevo.stock_actual = 0

            merma_actual.insumo_id = nuevo_insumo_id
            merma_actual.producto_id = nuevo_producto_id
            merma_actual.cantidad_perdida = nueva_cantidad
            merma_actual.causa = request.form.get('causa')
            merma_actual.notas_adicionales = request.form.get('notas_adicionales')

            db.session.commit()
            user_logger.log_action(
                current_user,
                module="Mermas",
                action="Se actualizó una merma",
                success=True,
            )
            flash("Merma actualizada correctamente.", "success")
            return redirect(url_for('losses.index'))
        except Exception as e:
            db.session.rollback()
            print(f"Error al modificar: {e}")
            flash(f"Error al modificar: {e}", "error")

    return render_template('internal/losses/Modificar.html', merma=merma_actual, insumos=insumos, productos=productos)

@losses_bp.route('/eliminar/<int:id>', methods=['GET', 'POST'])
@login_required
@roles_required('chef')
def eliminar_merma(id):
    # Buscamos la merma que se desea eliminar
    merma_a_eliminar = Merma.query.filter_by(id=id, is_active=True).first_or_404()
    
    # SI EL MÉTODO ES POST: El usuario confirmó la eliminación desde el formulario
    if request.method == 'POST':
        try:
            # 1. Recuperar el stock en el inventario del elemento perdido
            if merma_a_eliminar.insumo_id:
                insumo = Insumo.query.get(merma_a_eliminar.insumo_id)
                if insumo:
                    insumo.stock_actual += merma_a_eliminar.cantidad_perdida
            elif merma_a_eliminar.producto_id:
                producto = Product.query.get(merma_a_eliminar.producto_id)
                if producto:
                    producto.stock += merma_a_eliminar.cantidad_perdida
            
            # 2. Eliminación suave (soft-delete)
            merma_a_eliminar.is_active = False
            db.session.commit()
            user_logger.log_action(
                current_user,
                module="Mermas",
                action="Se eliminó una merma",
                success=True,
            )
            
            flash("Merma eliminada y stock restituido.", "success")
            # Redirigir a la lista principal tras el éxito
            return redirect(url_for('losses.index'))
            
        except Exception as e:
            db.session.rollback()
            print(f"Error al eliminar la merma: {e}")
            flash(f"Error al eliminar la merma: {e}", "error")
            return redirect(url_for('losses.index'))

    # SI EL MÉTODO ES GET: Mostramos la página de confirmación (el HTML que ya tienes)
    return render_template('internal/losses/Eliminar.html', merma=merma_a_eliminar)