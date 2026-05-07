// 토큰은 sessionStorage에 보관 — 탭 닫으면 자동 로그아웃, XSS 시 노출은 최소화.
// 토큰 부재 시 ARCHON_DASHBOARD_TOKEN 미설정으로 간주하고 통과(서버가 401이면 로그인 강제).

import { useSyncExternalStore } from "react";

const STORAGE_KEY = "archon.dashboard.token";
const EVENT_NAME = "archon:auth-changed";

function emitChange(): void {
  window.dispatchEvent(new Event(EVENT_NAME));
}

export function getToken(): string | null {
  try {
    return sessionStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string): void {
  sessionStorage.setItem(STORAGE_KEY, token);
  emitChange();
}

export function clearToken(): void {
  sessionStorage.removeItem(STORAGE_KEY);
  emitChange();
}

function subscribe(cb: () => void): () => void {
  window.addEventListener(EVENT_NAME, cb);
  window.addEventListener("storage", cb);
  return () => {
    window.removeEventListener(EVENT_NAME, cb);
    window.removeEventListener("storage", cb);
  };
}

export function useToken(): string | null {
  return useSyncExternalStore(subscribe, getToken, () => null);
}
