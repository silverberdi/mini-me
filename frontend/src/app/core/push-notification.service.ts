import { Injectable, signal } from "@angular/core";
import { ApiService } from "./api.service";

export interface PushNotificationCategories {
  stage_transitions: boolean;
  human_required: boolean;
  terminal_outcomes: boolean;
}

@Injectable({
  providedIn: "root"
})
export class PushNotificationService {
  isSupported = signal<boolean>(false);
  permission = signal<NotificationPermission>("default");
  isSubscribed = signal<boolean>(false);
  isLoading = signal<boolean>(false);
  errorMessage = signal<string | null>(null);
  successMessage = signal<string | null>(null);

  categories = signal<PushNotificationCategories>({
    stage_transitions: true,
    human_required: true,
    terminal_outcomes: true
  });

  constructor(private api: ApiService) {
    if (typeof window !== "undefined" && "serviceWorker" in navigator && "PushManager" in window) {
      this.isSupported.set(true);
      this.permission.set(Notification.permission);
      this.checkCurrentSubscription();
    }
  }

  private urlBase64ToUint8Array(base64String: string): Uint8Array {
    const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
    const base64 = (base64String + padding).replace(/\-/g, "+").replace(/_/g, "/");
    const rawData = window.atob(base64);
    const outputArray = new Uint8Array(rawData.length);
    for (let i = 0; i < rawData.length; ++i) {
      outputArray[i] = rawData.charCodeAt(i);
    }
    return outputArray;
  }

  async checkCurrentSubscription(): Promise<boolean> {
    if (!this.isSupported()) return false;
    try {
      const reg = await navigator.serviceWorker.ready;
      const sub = await reg.pushManager.getSubscription();
      const active = sub !== null;
      this.isSubscribed.set(active);
      return active;
    } catch {
      this.isSubscribed.set(false);
      return false;
    }
  }

  async subscribe(): Promise<boolean> {
    if (!this.isSupported()) {
      this.errorMessage.set("Tu navegador no soporta notificaciones Web Push.");
      return false;
    }
    this.isLoading.set(true);
    this.errorMessage.set(null);
    this.successMessage.set(null);

    try {
      const perm = await Notification.requestPermission();
      this.permission.set(perm);
      if (perm !== "granted") {
        this.errorMessage.set("Permiso de notificaciones denegado en el navegador.");
        this.isLoading.set(false);
        return false;
      }

      // Fetch VAPID public key
      const keyRes = await this.api.get<{ public_key: string }>("/api/v1/push/vapid-public-key");
      if (!keyRes.ok || !keyRes.data?.public_key) {
        this.errorMessage.set("No se pudo obtener la clave VAPID del servidor.");
        this.isLoading.set(false);
        return false;
      }

      const reg = await navigator.serviceWorker.ready;
      const convertedVapidKey = this.urlBase64ToUint8Array(keyRes.data.public_key);

      const subscription = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: convertedVapidKey
      });

      const subJson = subscription.toJSON();
      const payload = {
        endpoint: subscription.endpoint,
        keys: {
          p256dh: subJson.keys?.["p256dh"] || "",
          auth: subJson.keys?.["auth"] || ""
        },
        device_label: navigator.userAgent.slice(0, 100),
        categories: this.categories()
      };

      const saveRes = await this.api.post("/api/v1/push/subscriptions", payload);
      if (!saveRes.ok) {
        this.errorMessage.set(saveRes.error || "Error registrando suscripción en el servidor.");
        this.isLoading.set(false);
        return false;
      }

      this.isSubscribed.set(true);
      this.successMessage.set("Notificaciones Web Push activadas correctamente.");
      this.isLoading.set(false);
      return true;
    } catch (err: any) {
      this.errorMessage.set(err?.message || "Error al suscribir notificaciones.");
      this.isLoading.set(false);
      return false;
    }
  }

  async unsubscribe(): Promise<boolean> {
    if (!this.isSupported()) return false;
    this.isLoading.set(true);
    this.errorMessage.set(null);
    this.successMessage.set(null);

    try {
      const reg = await navigator.serviceWorker.ready;
      const sub = await reg.pushManager.getSubscription();
      if (sub) {
        const endpoint = sub.endpoint;
        await sub.unsubscribe();
        await this.api.delete("/api/v1/push/subscriptions", { endpoint });
      }
      this.isSubscribed.set(false);
      this.successMessage.set("Notificaciones desactivadas en este dispositivo.");
      this.isLoading.set(false);
      return true;
    } catch (err: any) {
      this.errorMessage.set(err?.message || "Error al desactivar notificaciones.");
      this.isLoading.set(false);
      return false;
    }
  }

  async sendTest(): Promise<boolean> {
    this.isLoading.set(true);
    this.errorMessage.set(null);
    this.successMessage.set(null);
    try {
      const res = await this.api.post<{ status: string; sent_count: number }>("/api/v1/push/test", {
        title: "Supervisión Móvil — mini me",
        body: "Prueba de notificación recibida exitosamente en tu dispositivo."
      });
      if (res.ok) {
        this.successMessage.set(`Notificación enviada a ${res.data?.sent_count ?? 1} dispositivo(s).`);
        this.isLoading.set(false);
        return true;
      } else {
        this.errorMessage.set(res.error || "No se pudo enviar la prueba.");
        this.isLoading.set(false);
        return false;
      }
    } catch (err: any) {
      this.errorMessage.set(err?.message || "Error al solicitar notificación de prueba.");
      this.isLoading.set(false);
      return false;
    }
  }

  updateCategory(category: keyof PushNotificationCategories, enabled: boolean): void {
    const updated = { ...this.categories(), [category]: enabled };
    this.categories.set(updated);
    // If subscribed, update preferences on server
    if (this.isSubscribed()) {
      navigator.serviceWorker.ready.then(async (reg) => {
        const sub = await reg.pushManager.getSubscription();
        if (sub) {
          const subJson = sub.toJSON();
          await this.api.post("/api/v1/push/subscriptions", {
            endpoint: sub.endpoint,
            keys: {
              p256dh: subJson.keys?.["p256dh"] || "",
              auth: subJson.keys?.["auth"] || ""
            },
            categories: updated
          });
        }
      });
    }
  }
}
