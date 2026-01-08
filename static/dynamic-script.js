// Dynamic audit JavaScript
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
      <p class="text-2xl text-green-400">${file.name}<br>Ready for video audit!</p>
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

  const manualText = document.getElementById('manual-urls').value.trim();
  let fileToUpload = fileInput.files[0];

  if (!fileToUpload && manualText) {
    fileToUpload = new File([manualText], "manual_urls.txt", { type: "text/plain" });
  }

  if (!fileToUpload) {
    Swal.fire({
      icon: 'info',
      title: 'URLs Required',
      text: 'Please select a file OR enter URLs manually.',
      background: '#0f172a',
      color: '#f8fafc',
      confirmButtonColor: '#3b82f6'
    });
    return;
  }

  selectedBrowsers = Array.from(document.querySelectorAll('input[name="browser"]:checked'))
    .map(cb => cb.value).filter(b => b === "Chrome" || b === "Edge");

  const selectedResolutions = Array.from(document.querySelectorAll('input[name="resolution"]:checked'))
    .map(cb => cb.value);

  const sessionName = document.querySelector('input[name="session_name"]').value;

  if (selectedBrowsers.length === 0) {
    Swal.fire({
      icon: 'info',
      title: 'Browser Selection Required',
      text: 'Please select at least one supported browser (Chrome or Edge).',
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
  document.getElementById('status-text').textContent = "Recording responsive videos... Please wait.";
  stopButton.classList.remove('hidden');

  const formData = new FormData();
  formData.append("file", fileToUpload);
  formData.append("browsers", JSON.stringify(selectedBrowsers));
  formData.append("resolutions", JSON.stringify(selectedResolutions));
  formData.append("session_name", sessionName);

  try {
    const res = await fetch("/upload/dynamic", {
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

    document.getElementById('status-text').textContent = "Initializing...";

    pollInterval = setInterval(async () => {
      try {
        const progRes = await fetch(`/progress/dynamic/${sessionId}`);
        const prog = await progRes.json();
        const completed = prog.completed || 0;
        const total = prog.total || totalExpected;
        const percent = total > 0 ? Math.round((completed / total) * 100) : 0;
        const status = prog.status || "running";

        document.getElementById('progress-bar').style.width = `${percent}%`;
        const progressText = document.getElementById('progress-text');
        if (progressText) {
          progressText.textContent = `${percent}%`;
        }
        document.getElementById('status-text').textContent = `Recorded ${completed} of ${total} videos...`;

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
            document.getElementById('results-section').classList.add('dynamic-audit');
            setupBrowserTabs();
            loadBrowserView(selectedBrowsers[0]);
          }, 2000);
        }
      } catch (err) {
        console.error("Progress polling error:", err);
      }
    }, 3000);

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
    const res = await fetch(`/session-config/dynamic/${sessionId}`);
    const config = await res.json();

    if (!config.urls || config.urls.length === 0) {
      document.getElementById('content-area').innerHTML = `
        <p class="text-center text-gray-400 text-2xl">No URLs found in this session.</p>
      `;
      return;
    }

    document.getElementById('content-area').innerHTML = `
      <h3 class="text-3xl font-bold text-blue-300 mb-10 text-center">Select a URL to View Responsive Videos</h3>
      <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-10 max-w-7xl mx-auto">
        ${config.urls.map(url => `
          <div onclick="showVideos('${url.replace(/'/g, "\\'")}', '${browser}')" 
               class="bg-gray-800/90 rounded-2xl p-10 cursor-pointer hover:bg-gray-700 transition-all duration-300 border-2 border-gray-700 hover:border-blue-500 shadow-xl">
            <p class="text-2xl text-blue-300 truncate font-medium">${url}</p>
          </div>
        `).join('')}
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
    let domain = parsed.hostname.replace("www.", "");
    domain = domain.replace(/[^\w\.-]/g, '-');
    let path = parsed.pathname.replace(/^\/|\/$/g, "");
    let page_name = "home";
    if (path) {
      const segments = path.split("/").filter(s => s);
      if (segments.length) {
        page_name = segments[segments.length - 1].split('.')[0];
        page_name = page_name.replace(/[^\w\-]/g, '-').replace(/-+/g, '-').trim("-").toLowerCase();
        if (!page_name || page_name === "index") page_name = "home";
        if (page_name.length > 50) page_name = page_name.substring(0, 47) + "...";
      }
    }
    return page_name === "home" ? `home__${domain}` : `${page_name}__${domain}`;
  } catch (e) {
    return "unknown__site";
  }
}

function showVideos(url, browser) {
  const checkedRes = document.querySelectorAll('input[name="resolution"]:checked');
  const resolutions = Array.from(checkedRes).map(cb => cb.value);

  // Fetch actual video URLs from database
  fetch(`/session-config/dynamic/${sessionId}`)
    .then(res => {
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}: ${res.statusText}`);
      }
      return res.json();
    })
    .then(config => {
      console.log('Session config:', config); // Debug log

      // Validate response structure
      if (!config || !config.results || !Array.isArray(config.results)) {
        throw new Error('Invalid response structure from API');
      }

      // Filter results for this URL and browser
      const videoResults = config.results.filter(r => r.url === url && r.browser === browser);

      if (videoResults.length === 0) {
        document.getElementById('content-area').innerHTML = `
          <p class="text-yellow-400 text-center text-2xl">No videos found for this URL and browser combination.</p>
        `;
        return;
      }

      document.getElementById('content-area').innerHTML = `
        <div class="mb-12 text-center">
          <button onclick="loadBrowserView('${browser}')" 
                  class="text-blue-400 hover:underline text-xl mb-6 inline-block hover:text-blue-300 transition">
            ← Back to URL List
          </button>
          <h2 class="text-5xl font-bold text-blue-300 mb-4">${url}</h2>
          <p class="text-gray-400 text-2xl">Responsive Videos • ${resolutions.length} Resolution${resolutions.length > 1 ? 's' : ''}</p>
        </div>

        <div class="grid grid-cols-1 lg:grid-cols-2 gap-16 max-w-7xl mx-auto px-6">
          ${selectedBrowsers.map(b => {
        const browserResults = videoResults.filter(r => r.browser === b);
        return `
              <div class="bg-gray-800 rounded-3xl overflow-hidden shadow-2xl border-4 border-gray-700">
                <div class="bg-gradient-to-r from-blue-800 to-purple-900 p-6 text-center">
                  <h3 class="text-4xl font-bold text-white tracking-wider">${b}</h3>
                </div>
                <div class="p-10 bg-gray-900 space-y-12">
                  ${browserResults.map(result => `
                    <div class="group">
                      <div class="bg-black rounded-2xl overflow-hidden border-4 border-gray-700 shadow-2xl transition-all duration-300 group-hover:border-blue-500">
                        <video 
                          controls 
                          preload="metadata" 
                          class="w-full h-auto block mx-auto"
                          style="max-width: 100%; height: auto;">
                          <source src="${result.video_path}" type="video/mp4">
                          Your browser does not support the video tag.
                        </video>
                      </div>
                      <div class="mt-6 text-center">
                        <span class="text-3xl font-bold text-blue-300">${result.resolution.replace('x', ' × ')}</span>
                      </div>
                    </div>
                  `).join('')}
                </div>
              </div>
            `;
      }).join('')}
        </div>
      `;
    })
    .catch(err => {
      console.error('Failed to load video URLs:', err);
      document.getElementById('content-area').innerHTML = `
        <div class="text-center">
          <p class="text-red-400 text-2xl mb-4">Error loading videos</p>
          <p class="text-gray-400">${err.message || 'Please try again.'}</p>
        </div>
      `;
    });
}