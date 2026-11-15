const authStatus = document.querySelector("#auth-status");
const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content;

function setAuthStatus(message, isError = false) {
  authStatus.textContent = message;
  authStatus.classList.toggle("is-error", isError);
}

async function submitAuthForm(form, mode) {
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = form.querySelector('button[type="submit"]');
    button.disabled = true;
    setAuthStatus(mode === "login" ? "Signing in..." : "Creating account...");

    const fields = new FormData(form);
    try {
      const response = await fetch(form.action, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
          "X-CSRF-Token": csrfToken || "",
        },
        body: JSON.stringify({
          username: fields.get("username"),
          password: fields.get("password"),
        }),
      });

      let data = null;
      try {
        data = await response.json();
      } catch {
        data = null;
      }

      if (!response.ok) {
        const message =
          data &&
          typeof data === "object" &&
          !Array.isArray(data) &&
          typeof data.error === "string"
            ? data.error
            : "The account request could not be completed. Try again.";
        throw new Error(message);
      }

      if (mode === "login") {
        if (typeof data?.redirect_url !== "string") {
          throw new Error("The sign-in service returned an invalid response.");
        }
        window.location.assign(data.redirect_url);
      } else {
        if (data?.status !== "registered") {
          throw new Error("The registration service returned an invalid response.");
        }
        form.reset();
        setAuthStatus("Account created. Sign in with your new credentials.");
      }
    } catch (error) {
      setAuthStatus(
        error instanceof Error
          ? error.message
          : "The account request could not be completed. Check your connection and try again.",
        true,
      );
    } finally {
      button.disabled = false;
    }
  });
}

submitAuthForm(document.querySelector("#login-form"), "login");
submitAuthForm(document.querySelector("#register-form"), "register");
