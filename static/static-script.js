// Static audit JavaScript
const dropZone = document.getElementById('drop-zone');
const fileInput = document.getElementById('file-input');
const form = document.getElementById('upload-form');
const stopButton = document.getElementById('stop-button');
let sessionId = null;
let totalExpected = 0;
let selectedBrowsers = [];
let pollInterval = null;

// Get authentication token from cookie
function getToken() {
  const cookies = document.cookie.split(';');
  for (let cookie of cookies) {
    const [name, value] = cookie.trim().split('=');
    if (name === 'access_token') {
      return value;
    }
  }
  return null;
}

dropZone.onclick = () => fileInput.click();

fileInput.onchange = () => {
  const file = fileInput.files[0];
  if (file) {
    dropZone.innerHTML = `
      <div class="w-24 h-24 mx-auto mb-4 bg-green-500/10 rounded-full flex items-center justify-center">
        <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="text-green-400"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>
      </div>
      <p class="text-2xl text-green-400">${file.name}<br>Ready for static audit!</p>
    `;
  }
};

form.onsubmit = async (e) => {
  e.preventDefault();

  // Check authentication
  const token = getToken();
  if (!token) {
    Swal.fire({
      icon: 'warning',
      title: 'Authentication Required',
      text: 'Please log in to start an audit.',
      background: '#0f172a',
      color: '#f8fafc',
      confirmButtonColor: '#3b82f6',
      confirmButtonText: 'Go to Login'
    }).then((result) => {
      if (result.isConfirmed) {
        window.location.href = "/login";
      }
    });
    return;
  }

  if (!fileInput.files[0]) {
    Swal.fire({
      icon: 'info',
      title: 'File Required',
      text: 'Please select a urls.txt file to continue.',
      background: '#0f172a',
      color: '#f8fafc',
      confirmButtonColor: '#3b82f6'
    });
    return;
  }

  selectedBrowsers = Array.from(document.querySelectorAll('input[name="browser"]:checked'))
    .map(cb => cb.value);
  const selectedResolutions = Array.from(document.querySelectorAll('input[name="resolution"]:checked'))
    .map(cb => cb.value);

  const sessionName = document.querySelector('input[name="session_name"]').value;

  if (selectedBrowsers.length === 0) {
    Swal.fire({
      icon: 'info',
      title: 'Browser Selection Required',
      text: 'Please select at least one browser to continue.',
      background: '#0f172a',
      color: '#f8fafc',
      confirmButtonColor: '#3b82f6'
    });
    return;
  }
  if (selectedResolutions.length === 0) {
    Swal.fire({
      icon: 'info',
      title: 'Resolution Selection Required',
      text: 'Please select at least one resolution to continue.',
      background: '#0f172a',
      color: '#f8fafc',
      confirmButtonColor: '#3b82f6'
    });
    return;
  }
  if (!sessionName.trim()) {
    Swal.fire({
      icon: 'info',
      title: 'Session Name Required',
      text: 'Please enter a name for this audit session.',
      background: '#0f172a',
      color: '#f8fafc',
      confirmButtonColor: '#3b82f6'
    });
    return;
  }

  document.getElementById('upload-section').classList.add('hidden');
  document.getElementById('progress-section').classList.remove('hidden');
  document.getElementById('status-text').textContent = "Uploading file and preparing...";
  stopButton.classList.remove('hidden');

  const formData = new FormData();
  formData.append("file", fileInput.files[0]);
  formData.append("browsers", JSON.stringify(selectedBrowsers));
  formData.append("resolutions", JSON.stringify(selectedResolutions));
  formData.append("session_name", sessionName);

  try {
    const res = await fetch("/upload/static", {
      method: "POST",
      headers: {
        'Authorization': `Bearer ${token}`
      },
      body: formData
    });

    if (!res.ok) {
      if (res.status === 401) {
        Swal.fire({
          icon: 'warning',
          title: 'Session Expired',
          text: 'Your session has expired. Please log in again.',
          background: '#0f172a',
          color: '#f8fafc',
          confirmButtonColor: '#3b82f6',
          confirmButtonText: 'Go to Login'
        }).then(() => {
          window.location.href = "/login";
        });
        return;
      }
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.error || errData.detail || `HTTP ${res.status}`);
    }

    const data = await res.json();
    sessionId = data.session;
    totalExpected = data.total_expected;

    document.getElementById('status-text').textContent = "Launching browsers and capturing screenshots...";

    pollInterval = setInterval(async () => {
      try {
        const progRes = await fetch(`/progress/static/${sessionId}`);
        const prog = await progRes.json();
        const completed = prog.completed || 0;
        const total = prog.total || totalExpected;
        const percent = total > 0 ? Math.round((completed / total) * 100) : 0;
        const status = prog.status || "running";

        document.getElementById('progress-bar').style.width = `${percent}%`;
        document.getElementById('progress-bar').textContent = `${percent}%`;
        document.getElementById('status-text').textContent = `Captured ${completed} of ${total} screenshots...`;

        // Handle different statuses
        if (status === "stopped") {
          clearInterval(pollInterval);
          document.getElementById('status-text').textContent = "Session stopped by user.";
          document.getElementById('progress-bar').style.backgroundColor = "#dc2626";
          stopButton.classList.add('hidden');

          setTimeout(() => {
            window.location.href = "/profile";
          }, 2000);
          return;
        }

        if (status === "error") {
          clearInterval(pollInterval);
          document.getElementById('status-text').textContent = "Session encountered an error.";
          document.getElementById('progress-bar').style.backgroundColor = "#dc2626";
          stopButton.classList.add('hidden');
          return;
        }

        if (completed >= total && total > 0 && status === "completed") {
          clearInterval(pollInterval);
          setTimeout(() => {
            document.getElementById('progress-section').classList.add('hidden');
            document.getElementById('results-section').classList.remove('hidden');
            document.getElementById('results-section').classList.add('static-audit');
            setupBrowserTabs();
            loadBrowserView(selectedBrowsers[0]);
          }, 2000);
        }
      } catch (err) {
        console.error("Progress polling error:", err);
      }
    }, 2500);

  } catch (err) {
    Swal.fire({
      icon: 'error',
      title: 'Upload Failed',
      text: err.message || 'An error occurred during upload. Please try again.',
      background: '#0f172a',
      color: '#f8fafc',
      confirmButtonColor: '#3b82f6',
      footer: '<a href="/support" class="text-blue-400">Need help? Contact support</a>'
    });
    document.getElementById('upload-section').classList.remove('hidden');
    document.getElementById('progress-section').classList.add('hidden');
    if (pollInterval) clearInterval(pollInterval);
  }
};

async function stopSession() {
  if (!sessionId || !confirm("Are you sure you want to stop this session?")) {
    return;
  }

  const token = getToken();
  if (!token) {
    Swal.fire({
      icon: 'warning',
      title: 'Authentication Required',
      text: 'Please log in to continue.',
      background: '#0f172a',
      color: '#f8fafc',
      confirmButtonColor: '#3b82f6',
      confirmButtonText: 'Go to Login'
    }).then(() => {
      window.location.href = "/login";
    });
    return;
  }

  try {
    stopButton.disabled = true;
    stopButton.textContent = "Stopping...";

    const response = await fetch(`/api/sessions/${sessionId}/stop`, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${token}`
      }
    });

    if (response.ok) {
      document.getElementById('status-text').textContent = "Stopping session...";
      if (pollInterval) clearInterval(pollInterval);
    } else {
      Swal.fire({
        icon: 'error',
        title: 'Unable to Stop Session',
        text: 'The session could not be stopped. It may have already completed.',
        background: '#0f172a',
        color: '#f8fafc',
        confirmButtonColor: '#3b82f6'
      });
      stopButton.disabled = false;
      stopButton.textContent = "Stop Session";
    }
  } catch (error) {
    Swal.fire({
      icon: 'error',
      title: 'Error',
      text: 'An error occurred while stopping the session.',
      background: '#0f172a',
      color: '#f8fafc',
      confirmButtonColor: '#3b82f6'
    });
    stopButton.disabled = false;
    stopButton.textContent = "Stop Session";
  }
}

function setupBrowserTabs() {
  const tabContainer = document.getElementById('browser-tabs-container');
  tabContainer.innerHTML = '';

  selectedBrowsers.forEach(browser => {
    const button = document.createElement('button');
    button.className = 'browser-tab';
    button.dataset.browser = browser;
    button.textContent = browser;
    button.onclick = () => loadBrowserView(browser);
    tabContainer.appendChild(button);
  });

  if (selectedBrowsers.length > 0) {
    document.querySelector(`[data-browser="${selectedBrowsers[0]}"]`).classList.add('active');
  }
}

async function loadBrowserView(browser) {
  document.querySelectorAll('.browser-tab').forEach(tab => tab.classList.remove('active'));
  document.querySelector(`[data-browser="${browser}"]`).classList.add('active');

  try {
    const res = await fetch(`/session-config/static/${sessionId}`);
    const config = await res.json();

    if (!config.urls || config.urls.length === 0) {
      document.getElementById('content-area').innerHTML = `
        <p class="text-center text-gray-400 text-2xl">No URLs found in this session.</p>
      `;
      return;
    }

    const contentArea = document.getElementById('content-area');
    contentArea.innerHTML = `
      <h3 class="text-3xl font-bold text-cyan-300 mb-10 text-center">
        ${browser} — Select a page to view screenshots
      </h3>
      <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8">
        ${config.urls.map(url => {
      const unique = getUniqueFilename(url);
      return `
            <div onclick="showScreenshots('${url.replace(/'/g, "\\'")}', '${browser}')"
                 class="bg-gray-800/80 backdrop-blur p-8 rounded-2xl hover:bg-gray-700/90 cursor-pointer transition-all hover:scale-105 border border-cyan-500/30 shadow-xl">
              <p class="text-cyan-400 font-medium text-lg truncate">${url}</p>
            </div>
          `;
    }).join('')}
      </div>
    `;
  } catch (err) {
    console.error("Failed to load session config:", err);
    document.getElementById('content-area').innerHTML = `<p class="text-red-400">Error loading results.</p>`;
  }
}

function getUniqueFilename(url) {
  try {
    const parsed = new URL(url);
    let domain = parsed.hostname.replace(/^www\./, '').replace(/[^\w\.-]/g, '-');
    let path = parsed.pathname.slice(1);
    let page_name = 'home';

    if (path && path.trim() !== '') {
      let segments = path.split('/').filter(Boolean);
      if (segments.length > 0) {
        page_name = segments[segments.length - 1];
        if (page_name.includes('.')) page_name = page_name.split('.').shift();
        page_name = page_name.replace(/[^\w\-]/g, '-')
          .replace(/-+/g, '-')
          .replace(/^-|-$/g, '')
          .toLowerCase();
        if (!page_name || page_name === 'index') page_name = 'home';
        if (page_name.length > 50) page_name = page_name.substring(0, 47) + '...';
      }
    }

    return page_name === 'home' ? `home__${domain}` : `${page_name}__${domain}`;
  } catch (e) {
    return 'unknown__site';
  }
}

function showScreenshots(url, browser) {
  const unique = getUniqueFilename(url);
  const checkedRes = document.querySelectorAll('input[name="resolution"]:checked');
  const resolutions = Array.from(checkedRes).map(cb => cb.value);

  document.getElementById('content-area').innerHTML = `
    <div class="mb-12 text-center">
      <button onclick="loadBrowserView('${browser}')" 
              class="text-cyan-400 hover:underline text-xl mb-6 inline-block hover:text-cyan-300 transition">
        ← Back to URL List
      </button>
      <h2 class="text-4xl font-bold text-cyan-300">${url}</h2>
      <p class="text-gray-400 mt-3 text-xl">${browser} • ${resolutions.length} Resolution${resolutions.length > 1 ? 's' : ''}</p>
    </div>

    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-12 max-w-7xl mx-auto">
      ${resolutions.map(res => {
    const [w, h] = res.split('x');
    return `
          <div class="bg-gray-800 rounded-2xl overflow-hidden shadow-2xl border border-gray-700 flex flex-col">
            <div class="flex-1 bg-black flex items-center justify-center overflow-hidden">
              <img src="/screenshots/${sessionId}/${browser}/${unique}__${res}.png"
                   alt="${url} - ${browser} - ${res}"
                   class="max-w-full max-h-full object-contain"
                   onerror="this.src='https://via.placeholder.com/1200x800/111111/666666?text=Not+Found';"
                   loading="lazy"/>
            </div>
            <div class="p-5 bg-gradient-to-r from-cyan-900 to-blue-900 text-center font-bold text-2xl">
              ${w} × ${h}
            </div>
          </div>
        `;
  }).join('')}
    </div>
  `;
}