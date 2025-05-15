import os
import shutil
import subprocess
import uuid
import zipfile
from flask import Flask, render_template, request, jsonify, send_from_directory, send_file, url_for
from werkzeug.utils import secure_filename

# Assuming book_converter_utils.py will be created in the same directory
import book_converter_utils as bcu

app = Flask(__name__)

# Configuration
UPLOAD_FOLDER = 'uploads'
CONVERTED_FOLDER = 'converted_files'
ALLOWED_EXTENSIONS = {'pdf', 'epub', 'mobi'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['CONVERTED_FOLDER'] = CONVERTED_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 30 * 1024 * 1024  # 30 MB limit

# Ensure necessary folders exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(CONVERTED_FOLDER, exist_ok=True)

EBOOK_CONVERT_PATH = bcu.find_ebook_convert_path()
if not EBOOK_CONVERT_PATH:
    print("WARNING: ebook-convert tool not found. Conversions will fail. Please install Calibre and ensure ebook-convert is in your PATH.")

def allowed_file(filename, selected_source_format):
    """Checks if the file extension is allowed and matches the selected source format."""
    if '.' not in filename:
        return False
    ext = filename.rsplit('.', 1)[1].lower()
    return ext in ALLOWED_EXTENSIONS and ext == selected_source_format.lower()

@app.route('/')
def index():
    """Renders the main page."""
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_files():
    """Handles file uploads and initiates conversion."""
    if not EBOOK_CONVERT_PATH:
        return jsonify({'error': 'ebook-convert tool not found on server. Cannot perform conversions.'}), 500

    source_format = request.form.get('source_format')
    target_format = request.form.get('target_format')
    
    if not source_format or not target_format:
        return jsonify({'error': 'Source or target format missing.'}), 400

    if 'files[]' not in request.files:
        return jsonify({'error': 'No files part in the request.'}), 400

    files = request.files.getlist('files[]')
    
    if not files or all(f.filename == '' for f in files):
        return jsonify({'error': 'No files selected.'}), 400

    processed_files = []
    errors = []
    conversion_session_id = str(uuid.uuid4()) # Unique ID for this batch of conversions
    session_upload_dir = os.path.join(app.config['UPLOAD_FOLDER'], conversion_session_id)
    session_converted_dir = os.path.join(app.config['CONVERTED_FOLDER'], conversion_session_id)
    os.makedirs(session_upload_dir, exist_ok=True)
    os.makedirs(session_converted_dir, exist_ok=True)

    for file in files:
        if file and allowed_file(file.filename, source_format):
            original_filename = secure_filename(file.filename)
            uploaded_filepath = os.path.join(session_upload_dir, original_filename)
            
            try:
                file.save(uploaded_filepath)
            except Exception as e:
                errors.append(f"Could not save file {original_filename}: {str(e)}")
                continue

            base_name, input_ext = os.path.splitext(original_filename)
            output_ext = f".{target_format.lower()}"

            if source_format.lower() == target_format.lower():
                # If source and target are the same, just copy the file
                converted_filepath = bcu.get_unique_filename(session_converted_dir, base_name, output_ext)
                try:
                    shutil.copy(uploaded_filepath, converted_filepath)
                    processed_files.append({
                        'original_name': original_filename,
                        'converted_name': os.path.basename(converted_filepath),
                        'download_url': url_for('download_file', session_id=conversion_session_id, filename=os.path.basename(converted_filepath))
                    })
                except Exception as e:
                    errors.append(f"Could not copy file {original_filename} (same format): {str(e)}")
            else:
                # Perform conversion
                success, result_path_or_msg = bcu.convert_file_web(
                    EBOOK_CONVERT_PATH,
                    uploaded_filepath,
                    output_ext,
                    session_converted_dir,
                    base_name # pass base_name to convert_file_web
                )
                if success and result_path_or_msg:
                    processed_files.append({
                        'original_name': original_filename,
                        'converted_name': os.path.basename(result_path_or_msg),
                        'download_url': url_for('download_file', session_id=conversion_session_id, filename=os.path.basename(result_path_or_msg))
                    })
                else:
                    errors.append(f"Error converting {original_filename}: {result_path_or_msg}")
        elif file.filename: # If a file was selected but not allowed
             errors.append(f"File type not allowed or does not match source format: {file.filename}")


    if not processed_files and not errors:
        return jsonify({'error': 'No valid files were processed. Check file types and source format selection.'}),400
        
    response_data = {'processed_files': processed_files, 'errors': errors}
    if len(processed_files) > 1:
         response_data['zip_download_url'] = url_for('download_zip', session_id=conversion_session_id)

    # Basic cleanup of empty session dirs if no files processed at all. 
    # More robust cleanup would be a background job.
    if not processed_files and not os.listdir(session_upload_dir) and not os.listdir(session_converted_dir):
        try:
            shutil.rmtree(session_upload_dir)
            shutil.rmtree(session_converted_dir)
        except OSError as e:
            print(f"Error removing empty session directories: {e}")
            
    return jsonify(response_data)


@app.route('/download/<session_id>/<filename>')
def download_file(session_id, filename):
    """Serves a single converted file for download."""
    directory = os.path.join(app.config['CONVERTED_FOLDER'], session_id)
    safe_filename = secure_filename(filename)
    if not os.path.exists(os.path.join(directory, safe_filename)):
        return "File not found.", 404
    return send_from_directory(directory, safe_filename, as_attachment=True)

@app.route('/download_zip/<session_id>')
def download_zip(session_id):
    """Creates a ZIP archive of all converted files in a session and serves it."""
    session_converted_dir = os.path.join(app.config['CONVERTED_FOLDER'], session_id)
    if not os.path.isdir(session_converted_dir) or not os.listdir(session_converted_dir):
        return "No files to zip or session not found.", 404

    # Generate a unique filename for the zip in the root of CONVERTED_FOLDER
    zip_base_name = "converted_files"
    zip_extension = ".zip"
    # Use the get_unique_filename utility from bcu
    # Target directory for the zip file itself is app.config['CONVERTED_FOLDER']
    zip_filepath = bcu.get_unique_filename(app.config['CONVERTED_FOLDER'], zip_base_name, zip_extension)
    # The actual name the user will see when downloading
    download_name = os.path.basename(zip_filepath) 

    try:
        with zipfile.ZipFile(zip_filepath, 'w', zipfile.ZIP_DEFLATED) as zf:
            for root, _, files in os.walk(session_converted_dir):
                for file in files:
                    # Add files to the zip with their names, not full paths
                    zf.write(os.path.join(root, file), arcname=file)
        
        return send_file(zip_filepath, as_attachment=True, download_name=download_name)
    except Exception as e:
        print(f"Error creating ZIP file for session {session_id}: {e}")
        return jsonify({'error': f'Could not create ZIP file: {str(e)}'}), 500
    # finally:
        # Optional: Clean up the zip file from server after sending
        # if os.path.exists(zip_filepath):
        #     os.remove(zip_filepath)
        # Optional: Clean up the session_converted_dir (source of zipped files)
        # This should be handled more robustly by a background cleanup task in a real app.
        # if os.path.exists(session_converted_dir):
        #     shutil.rmtree(session_converted_dir)
        # And corresponding upload dir
        # session_upload_dir = os.path.join(app.config['UPLOAD_FOLDER'], session_id)
        # if os.path.exists(session_upload_dir):
        #     shutil.rmtree(session_upload_dir)


if __name__ == '__main__':
    # Important: Debug mode should be False in a production environment
    app.run(debug=True, port=5001) 