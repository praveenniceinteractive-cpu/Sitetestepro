document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('performance-form');
    const resultsTableBody = document.querySelector('table tbody');
    let pollInterval = null;

    if (!form) return;

    form.addEventListener('submit', async function (e) {
        e.preventDefault();

        // 1. Get URLs
        const urlsTextarea = document.querySelector('textarea[name="urls"]');
        const urls = urlsTextarea.value.trim();
        if (!urls) return; // Validation already handled by inline script, this is safety

        const formData = new FormData(form);

        // 2. Show Loading State
        const submitBtn = form.querySelector('button[type="submit"]');
        const originalBtnText = submitBtn.innerText;
        submitBtn.innerText = 'Starting Analysis...';
        submitBtn.disabled = true;

        // Add a temporary "Scanning" row
        const loadingRow = document.createElement('tr');
        loadingRow.id = 'scanning-row';
        loadingRow.className = 'border-b border-gray-800/50 animate-pulse';
        loadingRow.innerHTML = `
            <td colspan="5" class="py-4 text-center text-gray-400">
                <svg class="animate-spin -ml-1 mr-3 h-5 w-5 text-green-500 inline-block" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                    <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                    <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
                Running performance audit...
            </td>
        `;

        // Remove "No audits yet" row if it exists
        if (resultsTableBody.querySelector('td[colspan="5"]')) {
            resultsTableBody.innerHTML = '';
        }
        resultsTableBody.prepend(loadingRow);

        try {
            // 3. Submit Request
            const response = await fetch('/api/performance-test', {
                method: 'POST',
                body: formData
            });

            if (!response.ok) throw new Error('Failed to start audit');

            const data = await response.json();
            const sessionId = data.session_id;

            submitBtn.innerText = 'Analyzing...';

            // 4. Start Polling
            startPolling(sessionId, submitBtn, originalBtnText, loadingRow);

        } catch (error) {
            console.error(error);
            Swal.fire({
                icon: 'error',
                title: 'Error',
                text: 'Failed to start performance audit.',
                background: '#0f172a',
                color: '#f8fafc'
            });
            submitBtn.innerText = originalBtnText;
            submitBtn.disabled = false;
            loadingRow.remove();
        }
    });

    function startPolling(sessionId, btn, originalText, loadingRow) {
        let attempts = 0;
        const maxAttempts = 60; // 2 minutes max (2s interval)

        pollInterval = setInterval(async () => {
            attempts++;
            try {
                const res = await fetch(`/api/results/${sessionId}`);
                if (!res.ok) return;

                const data = await res.json();
                const results = data.results || [];
                const status = data.status;

                // Update Table
                if (results && results.length > 0) {
                    if (resultsTableBody.contains(loadingRow)) loadingRow.remove();

                    results.forEach(result => {
                        // Check if row already exists to avoid duplicates
                        // We check by URL (cell 0) and Ensure Date is 'Just now' (cell 4)
                        const existingRow = Array.from(resultsTableBody.children).find(row =>
                            row.cells[0]?.innerText.trim() === result.url &&
                            row.cells[4]?.innerText.trim() === 'Just now'
                        );

                        if (!existingRow) {
                            const row = createResultRow(result);
                            resultsTableBody.prepend(row);
                        }
                    });
                }

                // Check for completion
                if (status === 'completed' || status === 'error') {
                    clearInterval(pollInterval);
                    btn.innerText = originalText;
                    btn.disabled = false;
                    if (resultsTableBody.contains(loadingRow)) loadingRow.remove();

                    // Auto-refresh as requested by user
                    setTimeout(() => {
                        window.location.reload();
                    }, 1000);

                    if (status === 'error') {
                        Swal.fire({
                            icon: 'warning',
                            title: 'Audit Issue',
                            text: 'The audit completed with potential errors.',
                            toast: true,
                            position: 'top-end',
                            timer: 3000
                        });
                    }
                }

                if (attempts >= maxAttempts) {
                    clearInterval(pollInterval);
                    btn.innerText = originalText;
                    btn.disabled = false;
                    if (resultsTableBody.contains(loadingRow)) loadingRow.remove();
                }

            } catch (e) {
                console.error("Polling error", e);
            }
        }, 2000);
    }

    function createResultRow(result) {
        const tr = document.createElement('tr');
        tr.className = 'border-b border-gray-800/50 hover:bg-gray-800/30 animate-fade-in';

        let scoreClass = 'bg-red-500/20 text-red-300';
        if (result.score >= 80) scoreClass = 'bg-green-500/20 text-green-300';
        else if (result.score >= 60) scoreClass = 'bg-yellow-500/20 text-yellow-300';

        tr.innerHTML = `
            <td class="py-4 truncate max-w-xs text-white">${result.url}</td>
            <td class="py-4">
                <span class="px-2 py-1 rounded ${scoreClass} text-xs font-bold">
                    ${result.score || 0}
                </span>
            </td>
            <td class="py-4">${result.ttfb ? Math.round(result.ttfb) + 'ms' : '-'}</td>
            <td class="py-4">${result.page_load ? (result.page_load / 1000).toFixed(2) + 's' : '-'}</td>
            <td class="py-4 text-gray-500 text-sm">Just now</td>
        `;
        return tr;
    }
});
