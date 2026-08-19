document.addEventListener("DOMContentLoaded", function () {
  // --- Reveal on scroll ---
  const revealEls = document.querySelectorAll(".reveal");
  const io = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add("visible");
          io.unobserve(entry.target);
        }
      });
    },
    { threshold: 0.12 }
  );
  revealEls.forEach((el) => io.observe(el));

  // --- Mobile menu ---
  const toggle = document.querySelector(".menu-toggle");
  const links = document.querySelector(".nav-links");
  if (toggle && links) {
    toggle.addEventListener("click", () => links.classList.toggle("open"));
  }

  // --- Cart badge bump ---
  const badge = document.querySelector(".cart-badge");
  if (badge) {
    const bump = () => {
      badge.classList.remove("bump");
      void badge.offsetWidth;
      badge.classList.add("bump");
    };
    const last = sessionStorage.getItem("cartBumpTime");
    const now = Date.now();
    if (last && now - parseInt(last, 10) < 4000) bump();
    badge.addEventListener("click", bump);
  }

  // --- Flash auto-hide (fallback sans JS toast) ---
  document.querySelectorAll(".flash").forEach((f) => {
    setTimeout(() => {
      f.style.transition = "opacity 0.5s, transform 0.5s";
      f.style.opacity = "0";
      f.style.transform = "translateX(120%)";
      setTimeout(() => f.remove(), 600);
    }, 4500);
  });

  // --- Toasts ---
  window.showToast = function (message, type) {
    type = type || "info";
    let container = document.getElementById("toast-container");
    if (!container) {
      container = document.createElement("div");
      container.id = "toast-container";
      container.className = "toasts";
      document.body.appendChild(container);
    }
    const t = document.createElement("div");
    t.className = "flash " + type;
    t.innerHTML = message;
    container.appendChild(t);
    setTimeout(() => {
      t.style.transition = "opacity 0.5s, transform 0.5s";
      t.style.opacity = "0";
      t.style.transform = "translateX(120%)";
      setTimeout(() => t.remove(), 600);
    }, 3500);
  };

  // --- AJAX add-to-cart (badge mis à jour sans rechargement) ---
  document.querySelectorAll("form[data-ajax-cart]").forEach((form) => {
    form.addEventListener("submit", (e) => {
      const btn = form.querySelector("button[type=submit]");
      if (btn && btn.disabled) {
        e.preventDefault();
        return;
      }
      e.preventDefault();
      const url = form.getAttribute("action");
      const body = new FormData(form);
      btn.disabled = true;
      const original = btn.innerHTML;
      btn.innerHTML = "⏳ Ajout en cours…";
      fetch(url, {
        method: "POST",
        body: body,
        headers: { "X-Requested-With": "XMLHttpRequest" },
      })
        .then((r) => r.json())
        .then((data) => {
          if (data && data.ok) {
            if (badge) {
              badge.textContent = data.count;
              bump();
            }
            showToast("🛒 " + (data.name || "Article") + " ajouté au panier", "success");
          } else if (data && data.need_login) {
            window.location.href = "/connexion?next=" + encodeURIComponent(window.location.pathname);
          }
        })
        .catch(() => {
          showToast("Ajout au panier impossible. Rechargez la page ou réessayez.", "error");
        })
        .finally(() => {
          btn.disabled = false;
          btn.innerHTML = original;
        });
      return false;
    });
  });

  // --- Boutons de panier classiques (non-AJAX, ex: compte) ---
  document.querySelectorAll("form[data-add-cart]:not([data-ajax-cart])").forEach((form) => {
    form.addEventListener("submit", () => {
      const btn = form.querySelector("button[type=submit]");
      if (btn && !btn.disabled) {
        const original = btn.innerHTML;
        btn.disabled = true;
        btn.innerHTML = "✓ Ajouté";
        setTimeout(() => {
          btn.disabled = false;
          btn.innerHTML = original;
        }, 1200);
        sessionStorage.setItem("cartBumpTime", String(Date.now()));
      }
    });
  });

  // --- Hero floating chips (parallax on mouse) ---
  const hero = document.querySelector(".hero-visual");
  if (hero) {
    hero.addEventListener("mousemove", (e) => {
      const r = hero.getBoundingClientRect();
      const x = (e.clientX - r.left) / r.width - 0.5;
      const y = (e.clientY - r.top) / r.height - 0.5;
      hero.querySelectorAll(".hero-chip").forEach((chip, i) => {
        const depth = i % 2 === 0 ? 12 : -12;
        chip.style.transform = `translate(${x * depth}px, ${y * depth}px)`;
      });
    });
  }

  // --- Quantity +/- buttons ---
  document.querySelectorAll("[data-qty-btn]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const input = document.querySelector(btn.dataset.qtyBtn);
      if (!input) return;
      let v = parseInt(input.value, 10) || 1;
      const min = parseInt(input.min, 10) || 1;
      const max = parseInt(input.max, 10) || 999;
      v = btn.dataset.dir === "plus" ? Math.min(v + 1, max) : Math.max(v - 1, min);
      input.value = v;
    });
  });

  // --- Validation client des formulaires ---
  const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
  const PHONE_RE = /^(\+221)?\s?([3677][0-9])\s?([0-9]{2})\s?([0-9]{2})\s?([0-9]{2})$/;
  const OTP_RE = /^[0-9]{6}$/;

  function fieldError(input, msg) {
    const wrap = input.closest(".field");
    if (!wrap) return;
    let err = wrap.querySelector(".field-error");
    if (!err) {
      err = document.createElement("div");
      err.className = "field-error";
      wrap.appendChild(err);
    }
    err.textContent = msg;
    input.classList.add("invalid");
  }

  function fieldClear(input) {
    const wrap = input.closest(".field");
    if (!wrap) return;
    const err = wrap.querySelector(".field-error");
    if (err) err.remove();
    input.classList.remove("invalid");
  }

  function validateField(input) {
    const rule = input.dataset.rule;
    const val = input.value.trim();
    fieldClear(input);
    if (input.required && !val) {
      fieldError(input, "Ce champ est obligatoire.");
      return false;
    }
    if (rule === "email" && val && !EMAIL_RE.test(val)) {
      fieldError(input, "Adresse email invalide.");
      return false;
    }
    if (rule === "phone" && val && !PHONE_RE.test(val)) {
      fieldError(input, "Numéro sénégalais attendu (ex : 77 123 45 67).");
      return false;
    }
    if (rule === "otp" && val && !OTP_RE.test(val)) {
      fieldError(input, "Le code doit contenir 6 chiffres.");
      return false;
    }
    const match = input.dataset.match;
    if (match) {
      const target = document.querySelector(match);
      if (target && val && val !== target.value) {
        fieldError(input, "Les mots de passe ne correspondent pas.");
        return false;
      }
    }
    return true;
  }

  document.querySelectorAll("form[data-validate]").forEach((form) => {
    const inputs = form.querySelectorAll("input[data-rule], input[required]");
    inputs.forEach((input) => {
      input.addEventListener("blur", () => validateField(input));
    });
    form.addEventListener("submit", (e) => {
      let ok = true;
      inputs.forEach((input) => {
        if (!validateField(input)) ok = false;
      });
      if (!ok) {
        e.preventDefault();
        showToast("Veuillez corriger les champs signalés.", "error");
      }
    });
  });

  // --- État de chargement des formulaires (anti double-clic) ---
  document.querySelectorAll("form[data-loading]").forEach((form) => {
    form.addEventListener("submit", () => {
      const btn = form.querySelector("button[type=submit]");
      if (btn && !btn.disabled) {
        const original = btn.innerHTML;
        btn.disabled = true;
        btn.dataset.original = original;
        btn.innerHTML = "⏳ Patientez…";
      }
    });
  });

  // --- Filtres catalogue : repliables sur mobile ---
  const filterAside = document.querySelector(".filter-aside");
  const filterToggle = document.querySelector(".filter-toggle");
  if (filterToggle && filterAside) {
    filterToggle.addEventListener("click", () => {
      filterAside.classList.toggle("open");
      filterToggle.textContent = filterAside.classList.contains("open") ? "✕ Fermer les filtres" : "⚙️ Filtres";
    });
  }
});