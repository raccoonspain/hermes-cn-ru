// Общие хелперы для login.html/home.html/project-selector.html/project-workspace.html — без сборщика, обычный <script src="app.js">.

async function apiFetch(url, options = {}) {
  const resp = await fetch(url, { credentials: 'same-origin', ...options });
  return resp;
}

async function requireAuth() {
  const resp = await apiFetch('/api/me');
  if (resp.status === 401) {
    location.href = 'login.html';
    return null;
  }
  return resp.json();
}

async function logout() {
  await apiFetch('/logout', { method: 'POST' });
  location.href = 'login.html';
}

// Читает text/event-stream тело fetch-ответа построчно и зовёт onEvent(name, payload)
// для каждого события. Формат идентичен Hermes API server: "event: X\ndata: Y\n\n".
async function readSSE(response, onEvent) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';
  let eventName = null;
  let dataLines = [];

  function flush() {
    if (eventName !== null) {
      const payload = dataLines.length ? JSON.parse(dataLines.join('\n')) : {};
      onEvent(eventName, payload);
    }
    eventName = null;
    dataLines = [];
  }

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop();
    for (const rawLine of lines) {
      const line = rawLine.replace(/\r$/, '');
      if (line.startsWith(':')) continue;
      if (line === '') { flush(); continue; }
      if (line.startsWith('event:')) eventName = line.slice('event:'.length).trim();
      else if (line.startsWith('data:')) dataLines.push(line.slice('data:'.length).trim());
    }
  }
  flush();
}
