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

  private async request<T>(path: string, options: RequestInit = {}): Promise<ApiResponse<T>> {
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
