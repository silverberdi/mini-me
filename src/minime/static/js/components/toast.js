/** Owns the single accessible toast surface and its dismissal timer. */
export function createToastController({ documentRef = document, windowRef = window } = {}) {
  let dismissalTimer = null;
  return function showToast(message, type = 'info') {
    const toast = documentRef.getElementById('toastNotification');
    if (!toast) return;
    if (dismissalTimer !== null) windowRef.clearTimeout(dismissalTimer);
    toast.textContent = String(message ?? '');
    toast.className = `toast-notification toast-${type}`;
    toast.style.display = 'block';
    dismissalTimer = windowRef.setTimeout(() => {
      toast.style.display = 'none';
      dismissalTimer = null;
    }, 4000);
  };
}
