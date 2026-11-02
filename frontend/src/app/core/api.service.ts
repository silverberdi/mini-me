import { Injectable } from "@angular/core";
import { ApiResponse } from "./models";

@Injectable({
  providedIn: "root"
})
export class ApiService {
  async get<T>(path: string, options: RequestInit = {}): Promise<ApiResponse<T>> {
    return this.request<T>(path, { ...options, method: "GET" });
  }

  async post<T>(path: string, body: any, options: RequestInit = {}): Promise<ApiResponse<T>> {
    return this.request<T>(path, {
      ...options,
      method: "POST",
      body: JSON.stringify(body),
      headers: {
        "Content-Type": "application/json",
        ...(options.headers || {})
      }
    });
  }

  async patch<T>(path: string, body: any, options: RequestInit = {}): Promise<ApiResponse<T>> {
    return this.request<T>(path, {
      ...options,
      method: "PATCH",
      body: JSON.stringify(body),
      headers: {
        "Content-Type": "application/json",
        ...(options.headers || {})
      }
    });
  }

  async delete<T>(path: string, body?: any, options: RequestInit = {}): Promise<ApiResponse<T>> {
    return this.request<T>(path, {
      ...options,
      method: "DELETE",
      body: body ? JSON.stringify(body) : undefined,
      headers: {
        "Content-Type": "application/json",
        ...(options.headers || {})
      }
    });
  }

  private async request<T>(path: string, options: RequestInit = {}): Promise<ApiResponse<T>> {
    const method = (options.method || "GET").toUpperCase();
    if (method !== "GET" && typeof navigator !== "undefined" && !navigator.onLine) {
      return { ok: false, offline: true, status: 0, data: null, error: "Acción no disponible sin conexión" };
    }
    try {
      const response = await fetch(path, {
        credentials: "same-origin",
        cache: "no-store",
        ...options,
        headers: {
          Accept: "application/json",
          ...(options.headers || {})
        }
      });

      let data: any = null;
      try {
        data = await response.json();
      } catch {
        // empty response or not json
      }

      if (response.status === 401 && path !== "/api/v1/auth/me") {
        // Session expired or revoked. The SPA otherwise keeps showing a stale
        // authenticated view (dashboard) while every data call 401s. Reload so
        // the shell re-runs /auth/me and renders the login card.
        if (typeof window !== "undefined") {
          window.location.reload();
        }
        return { ok: false, status: 401, data: null, error: "Sesión expirada" };
      }

      return {
        ok: response.ok,
        status: response.status,
        data: data as T,
        error: data?.detail || response.statusText
      };
    } catch (err: any) {
      if (err?.name === "AbortError") {
        return { ok: false, aborted: true, status: 0, data: null, error: "Lectura obsoleta" };
      }
      return { ok: false, offline: true, status: 0, data: null, error: "No se pudo conectar" };
    }
  }
}
