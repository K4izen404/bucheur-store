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

  // --- Flash auto-hide ---
  document.querySelectorAll(".flash").forEach((f) => {
    setTimeout(() => {
      f.style.transition = "opacity 0.5s, transform 0.5s";
      f.style.opacity = "0";
      f.style.transform = "translateX(120%)";
      setTimeout(() => f.remove(), 600);
    }, 4500);
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

  // --- Add-to-cart feedback ---
  document.querySelectorAll("form[data-add-cart]").forEach((form) => {
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
});