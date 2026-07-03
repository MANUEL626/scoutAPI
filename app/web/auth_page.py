from fastapi.responses import HTMLResponse


AUTH_PAGE_HTML = """<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ScoutAPI Auth</title>
  <style>
    :root { color-scheme: light; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    body { margin: 0; background: #f4f7f6; color: #15201d; }
    main { max-width: 1080px; margin: 0 auto; padding: 32px 20px; }
    h1 { margin: 0 0 4px; font-size: 32px; letter-spacing: 0; }
    p { margin: 0 0 24px; color: #53615d; }
    .grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; align-items: start; }
    section { background: #fff; border: 1px solid #d9e3df; border-radius: 8px; padding: 18px; box-shadow: 0 12px 32px rgba(21, 32, 29, .06); }
    h2 { margin: 0 0 14px; font-size: 18px; }
    label { display: block; margin: 12px 0 6px; font-size: 13px; font-weight: 650; color: #33423e; }
    input, textarea { box-sizing: border-box; width: 100%; border: 1px solid #cbd8d3; border-radius: 6px; padding: 10px 11px; font: inherit; background: #fff; }
    textarea { min-height: 92px; resize: vertical; font-family: ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace; font-size: 12px; }
    button { border: 0; border-radius: 6px; background: #176b5b; color: #fff; padding: 10px 14px; font: inherit; font-weight: 700; cursor: pointer; }
    button.secondary { background: #283633; }
    button.ghost { background: #eef4f2; color: #176b5b; }
    .actions { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 14px; }
    .wide { grid-column: 1 / -1; }
    .hint { margin: 8px 0 0; font-size: 13px; line-height: 1.5; color: #53615d; }
    .status { margin-top: 12px; min-height: 22px; color: #176b5b; font-weight: 650; }
    .error { color: #b42318; }
    @media (max-width: 760px) { .grid { grid-template-columns: 1fr; } main { padding: 22px 14px; } }
  </style>
</head>
<body>
  <main>
    <h1>ScoutAPI Auth</h1>
    <p>Connecte-toi pour creer une cle API permanente et revocable, ideale pour n8n.</p>
    <div class="grid">
      <section>
        <h2>Register</h2>
        <label for="registerName">Nom</label>
        <input id="registerName" autocomplete="name">
        <label for="registerEmail">Email</label>
        <input id="registerEmail" type="email" autocomplete="email">
        <label for="registerPassword">Mot de passe</label>
        <input id="registerPassword" type="password" autocomplete="new-password">
        <div class="actions">
          <button onclick="registerUser()">Creer le compte</button>
        </div>
      </section>
      <section>
        <h2>Login</h2>
        <label for="loginEmail">Email</label>
        <input id="loginEmail" type="email" autocomplete="email">
        <label for="loginPassword">Mot de passe</label>
        <input id="loginPassword" type="password" autocomplete="current-password">
        <div class="actions">
          <button onclick="loginUser()">Se connecter</button>
          <button class="ghost" onclick="refreshTokens()">Refresh</button>
          <button class="secondary" onclick="logoutUser()">Logout</button>
        </div>
      </section>
      <section class="wide">
        <h2>Cle API pour n8n</h2>
        <label for="apiKeyName">Nom de la cle</label>
        <input id="apiKeyName" value="n8n">
        <label for="apiKey">API key</label>
        <textarea id="apiKey" spellcheck="false"></textarea>
        <p class="hint">Dans n8n, ajoute un header HTTP: <strong>X-API-Key</strong> avec cette valeur. La cle n'expire pas, mais elle peut etre revoquee.</p>
        <div class="actions">
          <button onclick="createApiKey()">Generer une cle API</button>
          <button class="ghost" onclick="copyApiKey()">Copier X-API-Key</button>
          <button class="ghost" onclick="callMeWithApiKey()">Tester la cle</button>
        </div>
      </section>
      <section class="wide">
        <h2>Tokens de gestion</h2>
        <label for="accessToken">Access token</label>
        <textarea id="accessToken" spellcheck="false"></textarea>
        <label for="refreshToken">Refresh token</label>
        <textarea id="refreshToken" spellcheck="false"></textarea>
        <div class="actions">
          <button onclick="copyAccess()">Copier Bearer token</button>
          <button class="ghost" onclick="callMe()">Tester /v1/auth/me</button>
        </div>
        <div id="status" class="status"></div>
      </section>
    </div>
  </main>
  <script>
    const statusBox = document.getElementById("status");
    const accessToken = document.getElementById("accessToken");
    const refreshToken = document.getElementById("refreshToken");
    const apiKey = document.getElementById("apiKey");
    accessToken.value = localStorage.getItem("scoutapi_access_token") || "";
    refreshToken.value = localStorage.getItem("scoutapi_refresh_token") || "";
    apiKey.value = localStorage.getItem("scoutapi_api_key") || "";

    function setStatus(message, isError = false) {
      statusBox.textContent = message;
      statusBox.className = isError ? "status error" : "status";
    }

    function saveTokens(data) {
      accessToken.value = data.access_token;
      refreshToken.value = data.refresh_token;
      localStorage.setItem("scoutapi_access_token", data.access_token);
      localStorage.setItem("scoutapi_refresh_token", data.refresh_token);
      setStatus(`Connecte: ${data.user.email}`);
    }

    async function request(path, body, auth = false) {
      const headers = { "Content-Type": "application/json" };
      if (auth && accessToken.value) headers.Authorization = `Bearer ${accessToken.value}`;
      const response = await fetch(path, { method: "POST", headers, body: JSON.stringify(body) });
      const data = response.status === 204 ? {} : await response.json();
      if (!response.ok) throw new Error(data.detail || "Request failed");
      return data;
    }

    async function registerUser() {
      try {
        const data = await request("/v1/auth/register", {
          full_name: document.getElementById("registerName").value || null,
          email: document.getElementById("registerEmail").value,
          password: document.getElementById("registerPassword").value
        });
        saveTokens(data);
      } catch (error) { setStatus(error.message, true); }
    }

    async function loginUser() {
      try {
        const data = await request("/v1/auth/login", {
          email: document.getElementById("loginEmail").value,
          password: document.getElementById("loginPassword").value
        });
        saveTokens(data);
      } catch (error) { setStatus(error.message, true); }
    }

    async function refreshTokens() {
      try {
        const data = await request("/v1/auth/refresh", { refresh_token: refreshToken.value });
        saveTokens(data);
      } catch (error) { setStatus(error.message, true); }
    }

    async function logoutUser() {
      try {
        await request("/v1/auth/logout", { refresh_token: refreshToken.value });
        localStorage.removeItem("scoutapi_access_token");
        localStorage.removeItem("scoutapi_refresh_token");
        accessToken.value = "";
        refreshToken.value = "";
        setStatus("Deconnecte");
      } catch (error) { setStatus(error.message, true); }
    }

    async function createApiKey() {
      try {
        const data = await request("/v1/auth/api-keys", {
          name: document.getElementById("apiKeyName").value || "n8n"
        }, true);
        apiKey.value = data.api_key;
        localStorage.setItem("scoutapi_api_key", data.api_key);
        setStatus("Cle API creee. Copie-la maintenant, elle ne sera plus renvoyee ensuite.");
      } catch (error) { setStatus(error.message, true); }
    }

    async function copyApiKey() {
      await navigator.clipboard.writeText(apiKey.value);
      setStatus("Cle API copiee");
    }

    async function copyAccess() {
      await navigator.clipboard.writeText(`Bearer ${accessToken.value}`);
      setStatus("Bearer token copie");
    }

    async function callMe() {
      try {
        const response = await fetch("/v1/auth/me", { headers: { Authorization: `Bearer ${accessToken.value}` } });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || "Token invalide");
        setStatus(`Token OK: ${data.email}`);
      } catch (error) { setStatus(error.message, true); }
    }

    async function callMeWithApiKey() {
      try {
        const response = await fetch("/v1/auth/me", { headers: { "X-API-Key": apiKey.value } });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || "Cle invalide");
        setStatus(`Cle API OK: ${data.email}`);
      } catch (error) { setStatus(error.message, true); }
    }
  </script>
</body>
</html>"""


def auth_page() -> HTMLResponse:
    return HTMLResponse(AUTH_PAGE_HTML)
