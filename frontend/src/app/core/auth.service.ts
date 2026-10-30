import { Injectable, signal } from "@angular/core";
import { ApiService } from "./api.service";
import { UserSession } from "./models";

@Injectable({
  providedIn: "root"
})
export class AuthService {
  readonly session = signal<UserSession>({ authenticated: false, user: null });
  readonly isLoaded = signal<boolean>(false);

  constructor(private api: ApiService) {}

  async checkSession(): Promise<boolean> {
    const res = await this.api.get<UserSession>("/api/v1/auth/me");
    if (res.ok && res.data?.authenticated) {
      this.session.set(res.data);
      this.isLoaded.set(true);
      return true;
    }
    this.session.set({ authenticated: false, user: null });
    this.isLoaded.set(true);
    return false;
  }

  async logout(): Promise<void> {
    await this.api.post("/api/v1/auth/logout", {});
    this.session.set({ authenticated: false, user: null });
    window.location.assign("/");
  }
}
