import os
import shutil
import subprocess

def find_ebook_convert_path():
    """Tries to find the ebook-convert executable."""
    potential_paths = [
        shutil.which('ebook-convert'),
        '/Applications/calibre.app/Contents/MacOS/ebook-convert', # macOS
        # Add common paths for Linux if known (often just in PATH)
        # For Windows, it might be C:\Program Files\Calibre2\ebook-convert.exe
        # but relying on PATH via shutil.which is often best for Windows.
    ]
    for path in potential_paths:
        if path and os.path.exists(path) and os.access(path, os.X_OK):
            return path
    return None

def get_unique_filename(directory, base_name, extension):
    """Generates a unique filename by appending (n) if necessary."""
    counter = 1
    # Ensure extension starts with a dot
    if not extension.startswith('.'):
        ext_with_dot = '.' + extension
    else:
        ext_with_dot = extension

    output_filename = f"{base_name}{ext_with_dot}"
    output_path = os.path.join(directory, output_filename)
    while os.path.exists(output_path):
        output_filename = f"{base_name} ({counter}){ext_with_dot}"
        output_path = os.path.join(directory, output_filename)
        counter += 1
    return output_path

def convert_file_web(ebook_convert_path, input_path, output_extension, output_dir, base_name_override=None):
    """Converts a single file for the web app.
       Returns (True, output_filepath) on success, or (False, error_message) on failure.
    """
    if not ebook_convert_path:
        return False, "ebook-convert tool path not configured."

    if base_name_override:
        base_name = base_name_override
    else:
        base_name = os.path.splitext(os.path.basename(input_path))[0]
    
    output_filepath = get_unique_filename(output_dir, base_name, output_extension)

    print(f"Web converting: '{input_path}' to '{output_filepath}'")
    try:
        process = subprocess.Popen(
            [ebook_convert_path, input_path, output_filepath],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        stdout, stderr = process.communicate(timeout=300) # 5-minute timeout

        if process.returncode == 0:
            print(f"Successfully converted to '{output_filepath}'")
            return True, output_filepath
        else:
            error_msg = f"ebook-convert failed. Return code: {process.returncode}\nSTDERR: {stderr.decode(errors='ignore')}\nSTDOUT: {stdout.decode(errors='ignore')}"
            print(error_msg)
            return False, error_msg
    except subprocess.TimeoutExpired:
        msg = "Conversion process timed out."
        print(msg)
        if process:
            process.kill()
            process.communicate()
        return False, msg
    except Exception as e:
        msg = f"An unexpected error occurred during conversion: {str(e)}"
        print(msg)
        return False, msg 