(function () {
  const TOKEN_KEY = "suat_access_token";
  const INTENDED_KEY = "suat_intended_redirect";
  const INTENDED_LS_KEY = "suat_intended_redirect_ls";
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
      history.replaceState(
        null,
        "",
        location.pathname +
          (location.search.replace(/[?&](access_token|token|accessToken)=[^&]*/g, "").replace(/^&/, "?") || ""),
      );
      return queryToken;
    }
    return "";
  }

  function appendToken(url, token) {
    if (!token || !url) return url || "/";
    const base = String(url).split("#")[0];
    return `${base}#access_token=${encodeURIComponent(token)}`;
  }

  function normalizeRedirect(value) {
    if (!value || typeof value !== "string") return "";
    let v = value.trim();
    for (let i = 0; i < 2; i += 1) {
      try {
        if (v.includes("%")) v = decodeURIComponent(v);
      } catch {
        break;
      }
    }
    return v.trim();
  }

  function isMs1001Https(url) {
    try {
      const u = new URL(url);
      return u.protocol === "https:" && (u.hostname === "ms1001.com" || u.hostname.endsWith(".ms1001.com"));
    } catch {
      return false;
    }
  }

  function isLocalDevUrl(url) {
    try {
      const u = new URL(url);
      return (u.hostname === "127.0.0.1" || u.hostname === "localhost") && u.protocol === "http:";
    } catch {
      return false;
    }
  }

  function isAllowedRedirect(url) {
    return isMs1001Https(url) || isLocalDevUrl(url);
  }

  function storeIntendedRedirect(value) {
    const normalized = normalizeRedirect(value);
    if (!normalized || !isAllowedRedirect(normalized)) return;
    sessionStorage.setItem(INTENDED_KEY, normalized);
    try {
      localStorage.setItem(INTENDED_LS_KEY, JSON.stringify({ url: normalized, at: Date.now() }));
    } catch {
      /* ignore */
    }
  }

  function readIntendedRedirect() {
    const fromSession = normalizeRedirect(sessionStorage.getItem(INTENDED_KEY) || "");
    if (fromSession && isAllowedRedirect(fromSession)) return fromSession;
    try {
      const raw = localStorage.getItem(INTENDED_LS_KEY);
      if (!raw) return "";
      const parsed = JSON.parse(raw);
      const url = normalizeRedirect(parsed?.url || "");
      if (!url || !isAllowedRedirect(url)) return "";
      if (Date.now() - Number(parsed?.at || 0) > 30 * 60 * 1000) {
        localStorage.removeItem(INTENDED_LS_KEY);
        return "";
      }
      return url;
    } catch {
      return "";
    }
  }

  function clearIntendedRedirect() {
    sessionStorage.removeItem(INTENDED_KEY);
    try {
      localStorage.removeItem(INTENDED_LS_KEY);
    } catch {
      /* ignore */
    }
  }

  function isPosterPathMatch(pathname, posterPath) {
    if (!posterPath || !posterPath.startsWith("/")) return false;
    return pathname === posterPath || pathname.endsWith(posterPath.replace(/^\//, ""));
  }

  function recoverPosterAfterLogin(token) {
    const activeToken = token || localStorage.getItem(TOKEN_KEY) || "";
    if (!activeToken) return false;

    const posterPath = sessionStorage.getItem("poster_after_login");
    if (posterPath) {
      sessionStorage.removeItem("poster_after_login");
      if (!isPosterPathMatch(location.pathname, posterPath)) {
        location.replace(appendToken(`${location.origin}${posterPath}`, activeToken));
        return true;
      }
      clearIntendedRedirect();
      return false;
    }

    const intended = readIntendedRedirect();
    if (!intended || !isAllowedRedirect(intended)) return false;
    try {
      const target = new URL(intended);
      if (target.hostname !== location.hostname) return false;
      clearIntendedRedirect();
      const onTarget =
        target.pathname === location.pathname && (target.search || "") === (location.search || "");
      if (onTarget) {
        return false;
      }
      location.replace(appendToken(intended.split("#")[0], activeToken));
      return true;
    } catch {
      return false;
    }
  }

  const capturedToken = captureTokenFromUrl();
  if (recoverPosterAfterLogin(capturedToken)) return;

  window.suatCaptureTokenFromUrl = captureTokenFromUrl;
  window.suatAppendTokenToUrl = appendToken;
  window.suatStoreIntendedRedirect = storeIntendedRedirect;
  window.suatReadIntendedRedirect = readIntendedRedirect;
  window.suatAccessToken = () => localStorage.getItem(TOKEN_KEY) || "";
})();
