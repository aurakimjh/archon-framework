// WebSocket 클라이언트 — exponential backoff + jitter, 토큰 자동 첨부, 단일 연결 공유.

import type { DashboardEvent } from "@/types";
import { getToken } from "@/lib/auth";

type Listener = (event: DashboardEvent) => void;
type StatusListener = (status: ConnectionStatus) => void;

export type ConnectionStatus = "connecting" | "open" | "closed" | "error";

class WSClient {
  private socket: WebSocket | null = null;
  private listeners = new Set<Listener>();
  private statusListeners = new Set<StatusListener>();
  private status: ConnectionStatus = "closed";
  private retryCount = 0;
  private retryTimer: ReturnType<typeof setTimeout> | null = null;
  private intentionallyClosed = false;

  private url(): string {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const token = getToken();
    const qs = token ? `?token=${encodeURIComponent(token)}` : "";
    return `${proto}//${window.location.host}/ws${qs}`;
  }

  connect(): void {
    if (this.socket && this.socket.readyState !== WebSocket.CLOSED) return;
    this.intentionallyClosed = false;
    this.setStatus("connecting");

    try {
      this.socket = new WebSocket(this.url());
    } catch {
      this.scheduleReconnect();
      return;
    }

    this.socket.onopen = () => {
      this.retryCount = 0;
      this.setStatus("open");
    };

    this.socket.onmessage = (e) => {
      try {
        const evt = JSON.parse(e.data) as DashboardEvent;
        this.listeners.forEach((cb) => cb(evt));
      } catch {
        /* ignore malformed messages */
      }
    };

    this.socket.onerror = () => {
      this.setStatus("error");
    };

    this.socket.onclose = () => {
      this.setStatus("closed");
      if (!this.intentionallyClosed) this.scheduleReconnect();
    };
  }

  disconnect(): void {
    this.intentionallyClosed = true;
    if (this.retryTimer) clearTimeout(this.retryTimer);
    this.socket?.close();
    this.socket = null;
  }

  private scheduleReconnect(): void {
    if (this.retryTimer) clearTimeout(this.retryTimer);
    const base = Math.min(30_000, 500 * 2 ** this.retryCount);
    const jitter = Math.random() * 500;
    this.retryCount += 1;
    this.retryTimer = setTimeout(() => this.connect(), base + jitter);
  }

  private setStatus(next: ConnectionStatus): void {
    this.status = next;
    this.statusListeners.forEach((cb) => cb(next));
  }

  getStatus(): ConnectionStatus {
    return this.status;
  }

  on(cb: Listener): () => void {
    this.listeners.add(cb);
    return () => this.listeners.delete(cb);
  }

  onStatus(cb: StatusListener): () => void {
    this.statusListeners.add(cb);
    return () => this.statusListeners.delete(cb);
  }
}

export const wsClient = new WSClient();
