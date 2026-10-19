export function createSessionController({ fetch, loginSection, authenticatedContent, profileGroup, emailNode, onAuthenticated, onUnauthenticated }) {
  let currentUser = null;

  function showLogin() {
    currentUser = null;
    if (authenticatedContent) authenticatedContent.style.display = "none";
    if (profileGroup) profileGroup.style.display = "none";
    if (loginSection) loginSection.style.display = "flex";
    onUnauthenticated();
  }

  async function checkAuth() {
    try {
      const response = await fetch("/api/v1/auth/me");
      if (response.ok) {
        const data = await response.json();
        if (data.authenticated && data.operator) {
          currentUser = data.operator;
          if (loginSection) loginSection.style.display = "none";
          if (authenticatedContent) authenticatedContent.style.display = "block";
          if (profileGroup) profileGroup.style.display = "flex";
          if (emailNode) emailNode.textContent = currentUser.email;
          onAuthenticated(currentUser);
          return true;
        }
      }
    } catch (error) {
      console.error("Failed checking authentication:", error);
    }
    showLogin();
    return false;
  }

  async function logout() {
    try {
      await fetch("/api/v1/auth/logout", { method: "POST" });
    } catch (error) {
      console.error("Logout error:", error);
    }
    showLogin();
  }

  function bindLogout(button) {
    button?.addEventListener("click", logout);
  }

  return {
    checkAuth,
    logout,
    bindLogout,
    showLogin,
    get currentUser() { return currentUser; },
  };
}
