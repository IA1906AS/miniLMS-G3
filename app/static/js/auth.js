"use strict";

const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || "";
const errorMessages = {
  INVALID_CREDENTIALS: "Email hoặc mật khẩu không đúng.",
  VALIDATION_ERROR: "Dữ liệu chưa hợp lệ. Vui lòng kiểm tra lại.",
  ACCOUNT_LOCKED: "Tài khoản bị khoá tạm thời, vui lòng thử lại sau 15 phút.",
  UNAUTHENTICATED: "Phiên làm việc không hợp lệ. Vui lòng tải lại trang.",
  FORBIDDEN: "Bạn không có quyền thực hiện thao tác này.",
  CONFLICT: "Email này đã được đăng ký.",
  MAIL_DELIVERY_FAILED: "Đã có lỗi, vui lòng thử lại.",
  INTERNAL_ERROR: "Đã có lỗi, vui lòng thử lại.",
  NOT_FOUND: "Liên kết đặt lại không hợp lệ hoặc đã hết hạn.",
};

function isEmail(value) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value.trim());
}

function passwordRules(value) {
  return {
    length: value.length >= 10,
    upper: /[A-Z]/.test(value) && /[a-z]/.test(value),
    number: /\d/.test(value),
  };
}

function setFieldError(form, name, message) {
  const input = form.elements.namedItem(name) || form.querySelector(`#${CSS.escape(name)}`);
  const error = form.querySelector(`#${CSS.escape(name)}-error`);
  if (input instanceof HTMLElement) {
    if (message) input.setAttribute("aria-invalid", "true");
    else input.removeAttribute("aria-invalid");
  }
  if (error) error.textContent = message || "";
}

function validateEmail(form) {
  const input = form.elements.namedItem("email");
  const value = input instanceof HTMLInputElement ? input.value.trim() : "";
  const message = !value
    ? "Vui lòng nhập email."
    : !isEmail(value)
      ? "Email chưa đúng định dạng."
      : "";
  setFieldError(form, "email", message);
  return !message;
}

function validatePassword(form) {
  const input = form.elements.namedItem("password");
  const value = input instanceof HTMLInputElement ? input.value : "";
  let message = "";
  const formType = form.dataset.authForm;

  if (!value) {
    message = "Vui lòng nhập mật khẩu.";
  } else if (formType === "login") {
    if (new TextEncoder().encode(value).length > 72) {
      message = "Mật khẩu không hợp lệ.";
    }
  } else {
    const rules = passwordRules(value);
    if (!Object.values(rules).every(Boolean)) {
      message = "Mật khẩu cần có ít nhất 10 ký tự, chữ hoa, chữ thường và chữ số.";
    }
  }

  setFieldError(form, "password", message);
  return !message;
}

function validateConfirmation(form) {
  const password = form.elements.namedItem("password");
  const confirmation = form.elements.namedItem("confirm_password");
  if (!(password instanceof HTMLInputElement) || !(confirmation instanceof HTMLInputElement)) {
    return true;
  }
  const message = !confirmation.value
    ? "Vui lòng xác nhận mật khẩu."
    : confirmation.value !== password.value
      ? "Hai mật khẩu không khớp."
      : "";
  setFieldError(form, "confirm-password", message);
  return !message;
}

function validateName(form) {
  const input = form.elements.namedItem("name");
  const value = input instanceof HTMLInputElement ? input.value.trim() : "";
  const message = !value ? "Vui lòng nhập họ tên." : value.length > 100 ? "Họ tên tối đa 100 ký tự." : "";
  setFieldError(form, "name", message);
  return !message;
}

function validateTerms(form) {
  const input = form.elements.namedItem("terms");
  const error = form.querySelector("#terms-error");
  const accepted = input instanceof HTMLInputElement && input.checked;
  if (input instanceof HTMLInputElement) {
    if (!accepted) input.setAttribute("aria-invalid", "true");
    else input.removeAttribute("aria-invalid");
  }
  if (error) error.textContent = accepted ? "" : "Bạn cần đồng ý với điều khoản để tiếp tục.";
  return accepted;
}

function updateStrength(input) {
  const strength = input.closest(".field")?.querySelector("[data-strength]");
  if (!strength) return;

  const rules = passwordRules(input.value);
  let score = Object.values(rules).filter(Boolean).length;
  if (input.value.length >= 14) score = Math.min(3, score + 1);
  if (!input.value) score = 0;
  strength.dataset.level = String(score);
  const label = strength.querySelector("[data-strength-label]");
  if (label) {
    label.textContent = score === 0
      ? "Chưa nhập"
      : score === 1
        ? "Yếu"
        : score === 2
          ? "Trung bình"
          : "Mạnh";
  }
  strength.querySelectorAll("[data-rule]").forEach((item) => {
    item.classList.toggle("is-met", Boolean(rules[item.dataset.rule]));
  });
}

function showFormError(form, message) {
  const box = form.parentElement?.querySelector(".form-error");
  if (!box) return;
  box.textContent = message;
  box.hidden = false;
}

function hideFormError(form) {
  const box = form.parentElement?.querySelector(".form-error");
  if (!box) return;
  box.textContent = "";
  box.hidden = true;
}

function apiErrorMessage(payload, status) {
  if (status === 429) return errorMessages.ACCOUNT_LOCKED;
  if (status >= 500) return errorMessages.INTERNAL_ERROR;
  const code = payload && typeof payload.error === "string" ? payload.error : "";
  return errorMessages[code] || errorMessages.INTERNAL_ERROR;
}

function validateForm(form) {
  const type = form.dataset.authForm;
  let valid = true;
  if (type === "login" || type === "register" || type === "forgot-password") {
    valid = validateEmail(form) && valid;
  }
  if (type === "login" || type === "register" || type === "reset-password") {
    valid = validatePassword(form) && valid;
  }
  if (type === "register") {
    valid = validateName(form) && valid;
    valid = validateConfirmation(form) && valid;
    valid = validateTerms(form) && valid;
  }
  if (type === "reset-password") valid = validateConfirmation(form) && valid;
  return valid;
}

function requestForForm(form) {
  const type = form.dataset.authForm;
  const data = new FormData(form);
  let endpoint;
  let body;

  if (type === "login") {
    endpoint = "/auth/login";
    body = {
      email: String(data.get("email") || "").trim(),
      password: String(data.get("password") || ""),
      remember: data.get("remember") === "on",
    };
  } else if (type === "register") {
    endpoint = "/auth/register";
    body = {
      email: String(data.get("email") || "").trim(),
      name: String(data.get("name") || "").trim(),
      password: String(data.get("password") || ""),
      termsAccepted: data.get("terms") === "on",
    };
  } else if (type === "forgot-password") {
    endpoint = "/auth/forgot-password";
    body = { email: String(data.get("email") || "").trim() };
  } else {
    endpoint = "/auth/reset-password";
    body = {
      token: form.dataset.resetToken || "",
      password: String(data.get("password") || ""),
    };
  }

  return { endpoint, body, type };
}

function toggleLoading(form, loading) {
  const button = form.querySelector('button[type="submit"]');
  if (!button) return;
  button.disabled = loading;
  button.classList.toggle("is-loading", loading);
  button.setAttribute("aria-busy", String(loading));
}

function showSuccess(form, message) {
  const box = form.parentElement?.querySelector(".form-success");
  if (!box) return;
  box.textContent = message;
  box.hidden = false;
}

async function submitForm(form) {
  hideFormError(form);
  const valid = validateForm(form);
  if (!valid) {
    form.querySelector('[aria-invalid="true"]')?.focus();
    return;
  }

  const { endpoint, body, type } = requestForForm(form);
  toggleLoading(form, true);
  try {
    const response = await fetch(endpoint, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": csrfToken,
      },
      body: JSON.stringify(body),
    });
    const payload = await response.json().catch(() => ({}));

    if (!response.ok) {
      const message = type === "reset-password" && response.status === 400
        ? "Liên kết đặt lại không hợp lệ hoặc đã hết hạn."
        : apiErrorMessage(payload, response.status);
      showFormError(form, message);
      if (type === "reset-password" && response.status === 400) {
        const retry = form.parentElement?.querySelector(".reset-retry");
        if (retry) retry.hidden = false;
      }
      return;
    }

    if (type === "login") {
      window.location.assign("/");
    } else if (type === "register") {
      window.location.assign("/login?registered=1");
    } else if (type === "forgot-password") {
      form.reset();
      showSuccess(form, "Nếu email tồn tại, chúng tôi đã gửi hướng dẫn đặt lại mật khẩu.");
    } else {
      window.location.assign("/login?password_reset=1");
    }
  } catch {
    showFormError(form, errorMessages.INTERNAL_ERROR);
  } finally {
    toggleLoading(form, false);
  }
}

document.querySelectorAll("[data-password-toggle]").forEach((button) => {
  button.addEventListener("click", () => {
    const input = document.getElementById(button.dataset.passwordToggle || "");
    if (!(input instanceof HTMLInputElement)) return;
    const show = input.type === "password";
    input.type = show ? "text" : "password";
    button.setAttribute("aria-pressed", String(show));
    button.setAttribute("aria-label", show ? "Ẩn mật khẩu" : "Hiện mật khẩu");
  });
});

document.querySelectorAll("[data-auth-form]").forEach((form) => {
  if (!(form instanceof HTMLFormElement)) return;
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    void submitForm(form);
  });

  form.addEventListener("input", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLInputElement)) return;
    if (target.name === "password") {
      updateStrength(target);
      if (form.elements.namedItem("confirm_password")?.value) validateConfirmation(form);
    }
    if (target.name === "confirm_password") validateConfirmation(form);
    if (target.name === "email" && target.value) validateEmail(form);
    if (target.name === "name" && target.value) validateName(form);
  });

  form.addEventListener("change", (event) => {
    const target = event.target;
    if (target instanceof HTMLInputElement && target.name === "terms") validateTerms(form);
  });

  form.addEventListener("focusout", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLInputElement)) return;
    if (target.name === "email" && target.value) validateEmail(form);
    if (target.name === "password" && target.value && form.dataset.authForm !== "login") validatePassword(form);
    if (target.name === "confirm_password" && target.value) validateConfirmation(form);
  });
});
