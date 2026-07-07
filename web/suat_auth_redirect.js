(function () {
  const TOKEN_KEY = "suat_access_token";
  const TOKEN_PARAMS = ["access_token", "token", "accessToken"];

  function readTokenFromParams(params) {
    for (const key of TOKEN_PARAMS) {
      const value = params.get(key);
      if (value) return value;
    }
    return "";
  }

  function captureTokenFromUrl() {
    const hash = location.hash.replace(/^#/, "");
    if (hash) {
      const token = readTokenFromParams(new URLSearchParams(hash));
      if (token) {
        localStorage.setItem(TOKEN_KEY, token);
        history.replaceState(null, "", location.pathname + location.search);
        return token;
      }
    }
    const query = new URLSearchParams(location.search);
    const queryToken = readTokenFromParams(query);
    if (queryToken) {
      localStorage.setItem(TOKEN_KEY, queryToken);
      history.replaceState(null, "", location.pathname);
      return queryToken;
    }
    return "";
  }

  function appendToken(url, token) {
    if (!token || !url) return url || "/";
    const base = String(url).split("#")[0];
    return `${base}#access_token=${encodeURIComponent(token)}`;
  }

  captureTokenFromUrl();
  window.suatCaptureTokenFromUrl = captureTokenFromUrl;
  window.suatAppendTokenToUrl = appendToken;
  window.suatAccessToken = () => localStorage.getItem(TOKEN_KEY) || "";
})();
