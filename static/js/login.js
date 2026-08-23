/* AUTOMEX CarFlow — login page behavior (externalized from the template).
   Same logic as the original inline script; user-visible strings now arrive
   through data-* attributes set by the template so Django i18n translates
   them instead of hardcoding English (§11). */
(() => {
    "use strict";

    const form = document.getElementById("carflowLoginForm");
    const password = document.getElementById("id_password");
    const toggle = document.getElementById("togglePassword");
    const loginButton = document.getElementById("loginButton");

    if (toggle && password) {

        toggle.addEventListener("click", () => {

            const isVisible = password.type === "text";

            password.type = isVisible
                ? "password"
                : "text";

            toggle.setAttribute(
                "aria-label",
                isVisible
                    ? toggle.dataset.labelShow
                    : toggle.dataset.labelHide
            );

        });

    }


    if (form && loginButton) {

        form.addEventListener("submit", () => {

            loginButton.disabled = true;
            loginButton.textContent = loginButton.dataset.labelSubmit;

        });

    }

})();
