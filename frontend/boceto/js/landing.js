// Portada: planeta de fondo y aparición al hacer scroll.

import { createPlanet, PALETTES } from "./planet.js";

const $ = (id) => document.getElementById(id);

createPlanet($("planet"), { palette: PALETTES.antares });

// Barra de navegación con fondo al bajar
const onScroll = () => $("nav").classList.toggle("scrolled", window.scrollY > 30);
window.addEventListener("scroll", onScroll, { passive: true }); onScroll();


// Aparición al entrar en pantalla, escalonada entre hermanos
const io = new IntersectionObserver((entries) => {
  for (const e of entries) if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); }
}, { threshold: 0.12 });
document.querySelectorAll(".reveal").forEach((el) => {
  const i = [...el.parentElement.children].filter((c) => c.classList.contains("reveal")).indexOf(el);
  el.style.setProperty("--rd", `${i * 0.09}s`);
  io.observe(el);
});

// Brillo de las tarjetas que sigue al ratón
document.addEventListener("pointermove", (e) => {
  const card = e.target.closest?.(".card");
  if (!card) return;
  const b = card.getBoundingClientRect();
  card.style.setProperty("--mx", `${e.clientX - b.left}px`);
  card.style.setProperty("--my", `${e.clientY - b.top}px`);
}, { passive: true });
