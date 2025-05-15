"""
python book_converter.py /Users/ahmeddoghri/Desktop/testfiles
"""
import os
import subprocess
import argparse
import shutil

def find_ebook_convert_path():
    """Tries to find the ebook-convert executable."""
    # Common installation paths for Calibre's ebook-convert
    # On macOS, it's typically within the Calibre.app bundle
    potential_paths = [
        shutil.which('ebook-convert'), # Check if it's in PATH
        '/Applications/calibre.app/Contents/MacOS/ebook-convert', # macOS default
        # Add other common paths for Linux/Windows if known, or rely on PATH
    ]
    for path in potential_paths:
        if path and os.path.exists(path) and os.access(path, os.X_OK):
            return path
    return None

EBOOK_CONVERT_PATH = find_ebook_convert_path()

def get_unique_filename(directory, base_name, extension):
    """Generates a unique filename by appending (n) if necessary."""
    counter = 1
    output_filename = f"{base_name}{extension}"
    output_path = os.path.join(directory, output_filename)
    while os.path.exists(output_path):
        output_filename = f"{base_name} ({counter}){extension}"
        output_path = os.path.join(directory, output_filename)
        counter += 1
    return output_path

def convert_file(input_path, output_extension, output_dir):
    """Converts a single file to the specified output_extension."""
    if not EBOOK_CONVERT_PATH:
        print("Error: ebook-convert tool not found. Please ensure Calibre is installed and ebook-convert is in your PATH or specify its location.")
        return False

    base_name = os.path.splitext(os.path.basename(input_path))[0]
    output_path = get_unique_filename(output_dir, base_name, output_extension)

    print(f"Converting '{input_path}' to '{output_path}'...")
    try:
        process = subprocess.Popen(
            [EBOOK_CONVERT_PATH, input_path, output_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        stdout, stderr = process.communicate(timeout=300) # 5 minutes timeout

        if process.returncode == 0:
            print(f"Successfully converted to '{output_path}'")
            return True
        else:
            print(f"Error converting '{input_path}'.")
            print(f"ebook-convert stdout: {stdout.decode(errors='ignore')}")
            print(f"ebook-convert stderr: {stderr.decode(errors='ignore')}")
            return False
    except subprocess.TimeoutExpired:
        print(f"Timeout converting '{input_path}'. The conversion took too long.")
        if process:
            process.kill()
            process.communicate()
        return False
    except Exception as e:
        print(f"An unexpected error occurred during conversion of '{input_path}': {e}")
        return False

def process_directory(input_dir):
    """Processes all supported files in the input directory."""
    if not os.path.isdir(input_dir):
        print(f"Error: Input directory '{input_dir}' not found.")
        return

    if not EBOOK_CONVERT_PATH:
        print("Critical Error: ebook-convert tool not found. Please install Calibre.")
        print("Searched paths included common system PATH and /Applications/calibre.app/Contents/MacOS/ebook-convert (for macOS).")
        print("If Calibre is installed in a non-standard location, you might need to add ebook-convert to your system's PATH.")
        return

    print(f"Scanning directory: '{input_dir}'")
    for item in os.listdir(input_dir):
        item_path = os.path.join(input_dir, item)
        if not os.path.isfile(item_path):
            continue

        filename, extension = os.path.splitext(item)
        extension = extension.lower()

        if extension == '.epub':
            print(f"Found EPUB: '{item_path}'")
            convert_file(item_path, '.mobi', input_dir)
            convert_file(item_path, '.pdf', input_dir)
        elif extension == '.mobi':
            print(f"Found MOBI: '{item_path}'")
            convert_file(item_path, '.pdf', input_dir)
        elif extension == '.pdf':
            print(f"Found PDF: '{item_path}'. No conversion needed.")
        else:
            # Optional: Log unsupported files
            # print(f"Skipping unsupported file: '{item_path}'")
            pass
    print("Directory processing complete.")

def main():
    parser = argparse.ArgumentParser(description="Convert e-book files (EPUB, MOBI) within a directory.")
    parser.add_argument("input_directory", help="The directory containing e-book files to process.")
    # Future enhancement: allow specifying output directory
    # parser.add_argument("-o", "--output_directory", help="The directory to save converted files. Defaults to the input directory.")

    args = parser.parse_args()
    
    # output_dir = args.output_directory if args.output_directory else args.input_directory
    # For now, output is same as input
    process_directory(args.input_directory)

if __name__ == "__main__":
    main() 