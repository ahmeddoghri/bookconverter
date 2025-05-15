document.addEventListener('DOMContentLoaded', function () {
    const uploadForm = document.getElementById('uploadForm');
    const statusDiv = document.getElementById('status');
    const resultsDiv = document.getElementById('results');
    const sourceFormatSelect = document.getElementById('source_format');
    const fileInput = document.getElementById('files');

    // Client-side validation for selected files based on source_format
    fileInput.addEventListener('change', function() {
        const selectedSourceFormat = sourceFormatSelect.value.toLowerCase();
        if (!selectedSourceFormat) {
            statusDiv.innerHTML = '<p class="error-message">Please select a source format first.</p>';
            this.value = ''; // Clear the file input
            return;
        }
        
        let allFilesValid = true;
        let errorMessages = '';

        for (const file of this.files) {
            const fileName = file.name;
            const fileExtension = fileName.slice(((fileName.lastIndexOf(".") - 1) >>> 0) + 2).toLowerCase();
            if (fileExtension !== selectedSourceFormat) {
                allFilesValid = false;
                errorMessages += `<p class="error-message">File "${fileName}" does not match the selected source format (.${selectedSourceFormat}).</p>`;
            }
        }

        if (!allFilesValid) {
            statusDiv.innerHTML = errorMessages;
            this.value = ''; // Clear the file input to force re-selection
        } else {
            statusDiv.innerHTML = ''; // Clear previous error messages if files are now valid
        }
    });

    uploadForm.addEventListener('submit', function (event) {
        event.preventDefault();
        statusDiv.innerHTML = ''; // Clear previous status
        resultsDiv.innerHTML = ''; // Clear previous results

        const formData = new FormData(uploadForm);
        const files = formData.getAll('files[]');
        const sourceFormat = formData.get('source_format');
        const targetFormat = formData.get('target_format');

        if (!sourceFormat || !targetFormat) {
            statusDiv.innerHTML = '<p class="error-message">Please select both source and target formats.</p>';
            statusDiv.className = 'error';
            return;
        }

        if (files.length === 0 || (files.length === 1 && files[0].name === '')) {
            statusDiv.innerHTML = '<p class="error-message">Please select one or more files to convert.</p>';
            statusDiv.className = 'error';
            return;
        }

        // Re-validate files against selected source format before submitting
        let filesAreValid = true;
        let clientSideErrors = '';
        for (const file of files) {
            const fileName = file.name;
            if (fileName) { // Check if a file is actually selected
                const fileExtension = fileName.slice(((fileName.lastIndexOf(".") - 1) >>> 0) + 2).toLowerCase();
                if (fileExtension !== sourceFormat.toLowerCase()) {
                    filesAreValid = false;
                    clientSideErrors += `<p class="error-message">File "${fileName}" does not match the selected source format (.${sourceFormat}). Please re-select files or adjust source format.</p>`;
                }
            }
        }

        if (!filesAreValid) {
            statusDiv.innerHTML = clientSideErrors;
            statusDiv.className = 'error';
            fileInput.value = ''; // Clear file input
            return;
        }


        statusDiv.innerHTML = '<p>Processing... Please wait.</p>';
        statusDiv.className = 'processing';

        fetch('/upload', {
            method: 'POST',
            body: formData,
        })
        .then(response => {
            if (!response.ok) {
                // Try to parse error from JSON, otherwise use status text
                return response.json().then(errData => {
                    throw new Error(errData.error || `Server error: ${response.statusText}`);
                }).catch(() => {
                     throw new Error(`Server error: ${response.status} ${response.statusText}`);
                });
            }
            return response.json();
        })
        .then(data => {
            statusDiv.innerHTML = '<p>Conversion complete!</p>';
            statusDiv.className = '';

            if (data.errors && data.errors.length > 0) {
                let errorHtml = '<h2>Errors:</h2><ul>';
                data.errors.forEach(err => {
                    errorHtml += `<li>${err}</li>`;
                });
                errorHtml += '</ul>';
                resultsDiv.innerHTML += errorHtml;
            }

            if (data.processed_files && data.processed_files.length > 0) {
                let filesHtml = '<h2>Converted Files:</h2><ul>';
                data.processed_files.forEach(file => {
                    filesHtml += `<li>
                                     <span class="filename">${file.original_name} &rarr; ${file.converted_name}</span>
                                     <a href="${file.download_url}" class="download-link" download>Download</a>
                                 </li>`;
                });
                filesHtml += '</ul>';
                resultsDiv.innerHTML += filesHtml;
            }

            if (data.zip_download_url) {
                resultsDiv.innerHTML += `<div class="zip-download">
                                            <a href="${data.zip_download_url}" download>Download All as ZIP</a>
                                        </div>`;
            }
            
            if (!data.processed_files || data.processed_files.length === 0) {
                if (!data.errors || data.errors.length === 0) { // No files processed and no specific errors reported
                     resultsDiv.innerHTML += '<p>No files were converted. Please check your selection and try again.</p>';
                }
            }
        })
        .catch(error => {
            statusDiv.innerHTML = `<p class="error-message">Error: ${error.message}</p>`;
            statusDiv.className = 'error';
            console.error('Fetch error:', error);
        });
    });
}); 