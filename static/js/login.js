/* AUTOMEX CarFlow — login page behavior.
   Strings arrive through data-* attributes set by the template, so every
   label is translated by Django i18n instead of hardcoded English (§11).
   Loaded with `defer` from the `extra_js` block of accounts/login.html. */
(() => {
    "use strict";

    const form = document.getElementById("carflowLoginForm");
    const password = document.getElementById("id_password");
    const toggle = document.getElementById("togglePassword");
    const loginButton = document.getElementById("loginButton");

    // Show/hide password with the eye icon flipping to the slashed state.
    if (toggle && password) {
        const eyeOpen = toggle.querySelector("[data-icon='eye-open']");
        const eyeClosed = toggle.querySelector("[data-icon='eye-closed']");

        toggle.addEventListener("click", () => {
            const isVisible = password.type === "text";
            password.type = isVisible ? "password" : "text";
            toggle.setAttribute(
                "aria-label",
                isVisible ? toggle.dataset.labelShow : toggle.dataset.labelHide
            );
            if (eyeOpen && eyeClosed) {
                eyeOpen.classList.toggle("hidden", !isVisible);
                eyeClosed.classList.toggle("hidden", isVisible);
            }
            password.focus();
        });
    }

    // Guard against double submits while the request is in flight.
    if (form && loginButton) {
        form.addEventListener("submit", () => {
            loginButton.disabled = true;
            loginButton.textContent = loginButton.dataset.labelSubmit;
        });
    }
})();
