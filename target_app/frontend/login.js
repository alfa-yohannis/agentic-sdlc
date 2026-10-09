(function () {
  "use strict";

  // VR-E reference regex, exactly as in section 3.1 of the specification.
  var EMAIL_PATTERN = /^[A-Za-z0-9_%+-]+(\.[A-Za-z0-9_%+-]+)*@([A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?\.)+[A-Za-z]{2,}$/;
  var EMAIL_MAX = 254;
  var EMAIL_LOCAL_MAX = 64;
  var PASSWORD_MAX = 128;
  var PASSWORD_MIN_WORDS = 3;
  var PASSWORD_MIN_SPACES = 2;

  var MSG = {
    emailEmpty: "Please enter your email address.",
    emailInvalid: "Please enter a valid email address, for example name@example.com.",
    passwordEmpty: "Please enter your password.",
    passwordInvalid:
      "Your password must have at least 3 words separated by spaces, for example: green apple house.",
    serverError: "Something went wrong. Please try again later.",
    lockOver: "You can try logging in again."
  };

  function attemptsLeftMessage(n) {
    return "Email or password is incorrect. You have " + n + " " +
      (n === 1 ? "attempt" : "attempts") + " left.";
  }

  function secondsText(s) {
    return s + " " + (s === 1 ? "second" : "seconds");
  }

  var form = document.getElementById("login-form");
  var email = document.getElementById("email");
  var emailError = document.getElementById("email-error");
  var password = document.getElementById("password");
  var passwordError = document.getElementById("password-error");
  var toggle = document.getElementById("toggle-password");
  var loginButton = document.getElementById("login-button");
  var formMessage = document.getElementById("form-message");

  var busy = false;
  var lockTimer = null;

  // --- Validation (VR-E, VR-P) ---------------------------------------------

  function emailProblem(value) {
    var trimmed = value.trim();
    if (trimmed === "") return MSG.emailEmpty;
    if (trimmed.length > EMAIL_MAX ||
        trimmed.indexOf("@") > EMAIL_LOCAL_MAX ||
        !EMAIL_PATTERN.test(trimmed)) {
      return MSG.emailInvalid;
    }
    return "";
  }

  function passwordProblem(value) {
    if (value === "") return MSG.passwordEmpty;
    // Only U+0020 separates words; tabs and other whitespace do not.
    var parts = value.split(" ");
    var words = parts.filter(function (w) { return w !== ""; }).length;
    var spaces = parts.length - 1;
    if (value.length > PASSWORD_MAX || words < PASSWORD_MIN_WORDS ||
        spaces < PASSWORD_MIN_SPACES) {
      return MSG.passwordInvalid;
    }
    return "";
  }

  function setFieldError(field, errorEl, message) {
    errorEl.textContent = message;
    if (message) {
      field.setAttribute("aria-invalid", "true");
    } else {
      field.removeAttribute("aria-invalid");
    }
  }

  // --- Form-level message -------------------------------------------------

  function setFormMessage(message) {
    formMessage.textContent = message;
  }

  // The whole lock message is announced once. After that only the number
  // changes, inside an aria-live="off" span, so screen readers are not
  // interrupted every second (NFR-14).
  function setCountdown(seconds) {
    var span = formMessage.querySelector(".countdown");
    if (!span) {
      formMessage.textContent = "";
      span = document.createElement("span");
      span.className = "countdown";
      span.setAttribute("aria-live", "off");
      formMessage.appendChild(document.createTextNode("Too many failed attempts. Please wait "));
      formMessage.appendChild(span);
      formMessage.appendChild(document.createTextNode(" before trying again."));
    }
    span.textContent = secondsText(seconds);
  }

  // --- Lock (FR-21, FR-22) ------------------------------------------------

  function startLockout(seconds) {
    var remaining = Math.max(1, Math.ceil(Number(seconds) || 1));
    if (lockTimer) clearInterval(lockTimer);
    loginButton.disabled = true;
    setCountdown(remaining);
    lockTimer = setInterval(function () {
      remaining -= 1;
      if (remaining > 0) {
        setCountdown(remaining);
        return;
      }
      clearInterval(lockTimer);
      lockTimer = null;
      setFormMessage(MSG.lockOver);
      loginButton.disabled = false;
    }, 1000);
  }

  // --- Login request (FR-12 to FR-17, FR-28) -------------------------------

  function finishRequest() {
    busy = false;
    if (!lockTimer) loginButton.disabled = false;
  }

  // FR-13: the server repeats the validation; show its messages like ours.
  function showServerFieldErrors(fields) {
    var emailMsg = typeof fields.email === "string" ? fields.email : "";
    var passwordMsg = typeof fields.password === "string" ? fields.password : "";
    if (!emailMsg && !passwordMsg) {
      setFormMessage(MSG.serverError);
      return;
    }
    setFieldError(email, emailError, emailMsg);
    setFieldError(password, passwordError, passwordMsg);
    (emailMsg ? email : password).focus();
  }

  function handleResponse(response) {
    return response.json().catch(function () { return {}; }).then(function (data) {
      var status = response.status;
      if (status === 200 && typeof data.redirect === "string") {
        window.location.assign(data.redirect);
        return;
      }
      if (status === 401 && typeof data.attempts_remaining === "number") {
        setFormMessage(attemptsLeftMessage(data.attempts_remaining));
        password.value = "";
        password.focus();
      } else if (status === 423) {
        startLockout(data.retry_after);
      } else if (status === 422 && data.fields && typeof data.fields === "object") {
        showServerFieldErrors(data.fields);
      } else {
        setFormMessage(MSG.serverError);
      }
      finishRequest();
    });
  }

  function sendLogin() {
    busy = true;
    loginButton.disabled = true;
    setFormMessage("");
    fetch("/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify({ email: email.value, password: password.value })
    })
      .then(handleResponse)
      .catch(function () {
        setFormMessage(MSG.serverError);
        finishRequest();
      });
  }

  // --- Events ---------------------------------------------------------------

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    if (busy || lockTimer) return;

    var emailMsg = emailProblem(email.value);
    var passwordMsg = passwordProblem(password.value);
    setFieldError(email, emailError, emailMsg);
    setFieldError(password, passwordError, passwordMsg);

    if (emailMsg) {
      email.focus();
      return;
    }
    if (passwordMsg) {
      password.focus();
      return;
    }
    sendLogin();
  });

  email.addEventListener("input", function () {
    setFieldError(email, emailError, "");
  });

  password.addEventListener("input", function () {
    setFieldError(password, passwordError, "");
  });

  toggle.addEventListener("click", function () {
    var show = password.type === "password";
    password.type = show ? "text" : "password";
    toggle.textContent = show ? "Hide" : "Show";
    toggle.setAttribute("aria-label", show ? "Hide password" : "Show password");
    toggle.setAttribute("aria-pressed", show ? "true" : "false");
  });
})();
