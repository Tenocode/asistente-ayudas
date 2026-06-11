(function () {
  const script = document.currentScript;
  if (!script) return;

  const baseUrl = new URL(script.src, window.location.href).origin;
  const entidad = script.dataset.entidad || "Asistente de ayudas";
  const comunidad = script.dataset.comunidad || "";
  const categoria = script.dataset.categoria || "";
  const modo = script.dataset.modo || "floating";
  const color = script.dataset.color || "#0f766e";

  const qs = new URLSearchParams();
  qs.set("entidad", entidad);
  if (comunidad) qs.set("comunidad", comunidad);
  if (categoria) qs.set("categoria", categoria);

  const iframe = document.createElement("iframe");
  iframe.src = `${baseUrl}/widget?${qs.toString()}`;
  iframe.title = entidad;
  iframe.loading = "lazy";
  iframe.style.border = "0";
  iframe.style.background = "white";

  if (modo === "inline") {
    iframe.style.width = script.dataset.width || "100%";
    iframe.style.height = script.dataset.height || "560px";
    iframe.style.borderRadius = script.dataset.radius || "10px";
    iframe.style.boxShadow = script.dataset.shadow || "0 8px 28px rgba(15, 23, 42, 0.12)";

    const targetId = script.dataset.target || "asistente-ayudas-widget";
    const target = document.getElementById(targetId);
    if (target) {
      target.appendChild(iframe);
    } else {
      script.parentNode.insertBefore(iframe, script);
    }
    return;
  }

  const button = document.createElement("button");
  button.type = "button";
  button.textContent = script.dataset.label || "Ayudas";
  button.setAttribute("aria-expanded", "false");
  button.style.position = "fixed";
  button.style.right = "18px";
  button.style.bottom = "18px";
  button.style.zIndex = "2147483646";
  button.style.border = "0";
  button.style.borderRadius = "999px";
  button.style.padding = "12px 16px";
  button.style.background = color;
  button.style.color = "white";
  button.style.font = "700 14px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
  button.style.boxShadow = "0 10px 28px rgba(15, 23, 42, 0.22)";
  button.style.cursor = "pointer";

  const panel = document.createElement("div");
  panel.style.position = "fixed";
  panel.style.right = "18px";
  panel.style.bottom = "72px";
  panel.style.zIndex = "2147483646";
  panel.style.width = "min(390px, calc(100vw - 24px))";
  panel.style.height = "min(620px, calc(100vh - 96px))";
  panel.style.borderRadius = "14px";
  panel.style.overflow = "hidden";
  panel.style.boxShadow = "0 18px 50px rgba(15, 23, 42, 0.26)";
  panel.style.display = "none";

  iframe.style.width = "100%";
  iframe.style.height = "100%";
  panel.appendChild(iframe);

  button.addEventListener("click", () => {
    const open = panel.style.display !== "none";
    panel.style.display = open ? "none" : "block";
    button.setAttribute("aria-expanded", String(!open));
    button.textContent = open ? (script.dataset.label || "Ayudas") : "Cerrar";
  });

  document.body.appendChild(panel);
  document.body.appendChild(button);
})();
