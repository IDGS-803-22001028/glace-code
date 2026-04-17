import os
import json
from datetime import datetime, date
from flask import Blueprint, render_template, request, flash, redirect, url_for, current_app, Response
from flask_login import login_required, current_user  # type: ignore
from app.decorators import roles_required
from app.mongo import mongo
from app import user_logger, db

configuration_bp = Blueprint('configuration', __name__)

@configuration_bp.route('/', methods=['GET', 'POST'])
@login_required
@roles_required('admin')
def index():
    db = mongo.db
    config_collection = db['configuration'] if db is not None else None
    
    if request.method == 'POST':
        razon_social = request.form.get('razon_social')
        rfc = request.form.get('rfc')
        direccion_fiscal = request.form.get('direccion_fiscal')
        telefono_contacto = request.form.get('telefono_contacto')
        
        if 'logotipo' in request.files:
            file = request.files['logotipo']
            if file and file.filename:
                # Save as app/static/images/icon.png
                filepath = os.path.join(current_app.root_path, 'static', 'images', 'icon.png')
                file.save(filepath)
                
        if config_collection is not None:
            config_data = {
                'razon_social': razon_social,
                'rfc': rfc,
                'direccion_fiscal': direccion_fiscal,
                'telefono_contacto': telefono_contacto
            }
            config_collection.update_one(
                {'_id': 'main_config'},
                {'$set': config_data},
                upsert=True
            )
            user_logger.log_action(
                current_user,
                module="Configuración",
                action=f"Se actualizó la configuración",
                success=True,
            )
            flash('Configuración guardada correctamente.', 'success')
        else:
            user_logger.log_action(
                current_user,
                module="Configuración",
                action=f"Error al actualizar la configuración",
                success=False,
            )
            flash('Error: No se pudo conectar a la base de datos.', 'error')
            
        return redirect(url_for('configuration.index'))
        
    config = {}
    if config_collection is not None:
        config = config_collection.find_one({'_id': 'main_config'}) or {}
        
    return render_template('internal/configuration/index.html', config=config)

class CustomJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        return super().default(obj)

@configuration_bp.route('/backup/download', methods=['GET'])
@login_required
@roles_required('admin')
def download_backup():
    try:
        backup_data = {}
        for table in db.metadata.sorted_tables:
            records = db.session.execute(table.select()).mappings().all()
            backup_data[table.name] = [dict(row) for row in records]

        json_data = json.dumps(backup_data, cls=CustomJSONEncoder, indent=2)
        
        response = Response(
            json_data,
            mimetype="application/json",
            headers={
                "Content-Disposition": f"attachment;filename=backup_maison_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            }
        )
        
        user_logger.log_action(
            current_user,
            module="Configuración",
            action="Descargó copia de seguridad JSON",
            success=True,
        )
        return response
    except Exception as e:
        user_logger.log_action(
            current_user,
            module="Configuración",
            action=f"Error al descargar copia de seguridad: {str(e)}",
            success=False,
        )
        flash(f'Error al generar el respaldo: {str(e)}', 'error')
        return redirect(url_for('configuration.index'))

@configuration_bp.route('/backup/upload', methods=['POST'])
@login_required
@roles_required('admin')
def upload_backup():
    if 'backup_file' not in request.files:
        flash('No se seleccionó ningún archivo.', 'error')
        return redirect(url_for('configuration.index'))
        
    file = request.files['backup_file']
    if file.filename == '':
        flash('No se seleccionó ningún archivo.', 'error')
        return redirect(url_for('configuration.index'))
        
    if not file.filename.endswith('.json'):
        flash('El archivo debe ser un JSON.', 'error')
        return redirect(url_for('configuration.index'))

    try:
        data = json.load(file)
        
        for table in reversed(db.metadata.sorted_tables):
            db.session.execute(table.delete())
            
        for table in db.metadata.sorted_tables:
            table_name = table.name
            if table_name in data and data[table_name]:
                rows_to_insert = data[table_name]
                
                # Parse datetime strings back if needed
                for row in rows_to_insert:
                    for col in table.columns:
                        if col.name in row and row[col.name] is not None:
                            col_type_str = str(col.type).upper()
                            col_type_name = type(col.type).__name__.upper()
                            
                            is_datetime = 'DATETIME' in col_type_str or 'DATETIME' in col_type_name or 'TIMESTAMP' in col_type_str
                            is_date = 'DATE' in col_type_str or 'DATE' in col_type_name
                            
                            if is_datetime or (is_date and not is_datetime):
                                val = row[col.name]
                                if isinstance(val, str):
                                    if val.endswith('Z'):
                                        val = val[:-1] + '+00:00'
                                    try:
                                        if is_datetime:
                                            row[col.name] = datetime.fromisoformat(val)
                                        else:
                                            row[col.name] = date.fromisoformat(val) if 'T' not in val else datetime.fromisoformat(val).date()
                                    except ValueError:
                                        pass # Let sqlalchemy try to parse or fail
                                        
                db.session.execute(table.insert(), rows_to_insert)
                
        db.session.commit()
        
        user_logger.log_action(
            current_user,
            module="Configuración",
            action="Restauró copia de seguridad",
            success=True,
        )
        flash('Base de datos restaurada correctamente.', 'success')
        
    except Exception as e:
        db.session.rollback()
        user_logger.log_action(
            current_user,
            module="Configuración",
            action=f"Error al restaurar copia de seguridad: {str(e)}",
            success=False,
        )
        flash(f'Error al restaurar: {str(e)}', 'error')

    return redirect(url_for('configuration.index'))