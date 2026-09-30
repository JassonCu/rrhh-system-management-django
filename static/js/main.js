/**
 * JavaScript base.
 *
 * Se carga como archivo externo del propio origen: la CSP estricta prohíbe el
 * código en línea y los manejadores onclick= (ADR-007). Todo comportamiento se
 * engancha con addEventListener sobre atributos data-*.
 */
"use strict";

document.addEventListener("DOMContentLoaded", () => {
  // Envío automático del selector de idioma. Sin JS, el <noscript> muestra el
  // botón: la funcionalidad no depende del script.
  document.querySelectorAll("select[data-autosubmit='true']").forEach((select) => {
    select.addEventListener("change", () => {
      const form = select.closest("form");
      if (form) {
        form.submit();
      }
    });
  });

  // Mostrar u ocultar la contraseña. El botón viene con `hidden`: sin JS no se
  // ve, así que nunca queda un control que no hace nada.
  document.querySelectorAll("[data-password-toggle]").forEach((button) => {
    const input = document.getElementById(button.dataset.passwordToggle);
    if (!input) {
      return;
    }
    button.hidden = false;
    button.addEventListener("click", () => {
      const reveal = input.type === "password";
      input.type = reveal ? "text" : "password";
      button.setAttribute("aria-pressed", String(reveal));
      button.textContent = reveal ? button.dataset.labelHide : button.dataset.labelShow;
      input.focus();
    });
  });

  // Selector agrupado (puestos por departamento, ADR-011): se añade un filtro
  // por área delante. Sin JS el <select> ya viene agrupado con <optgroup>, así
  // que la elección sigue siendo posible; esto solo la acorta.
  document.querySelectorAll("select[data-grouped-select]").forEach((select) => {
    const groups = [...select.querySelectorAll("optgroup")];
    if (groups.length < 2) {
      return;
    }
    const wrapper = document.createElement("div");
    wrapper.className = "field select-filter";

    const label = document.createElement("label");
    const filter = document.createElement("select");
    filter.id = `${select.id}-filter`;
    label.setAttribute("for", filter.id);
    label.textContent = select.dataset.groupedSelect;

    const all = document.createElement("option");
    all.value = "";
    all.textContent = select.dataset.groupedAll || "—";
    filter.append(all);
    groups.forEach((group) => {
      const option = document.createElement("option");
      option.value = group.label;
      option.textContent = group.label;
      filter.append(option);
    });

    filter.addEventListener("change", () => {
      groups.forEach((group) => {
        group.hidden = Boolean(filter.value) && group.label !== filter.value;
      });
      const selected = select.selectedOptions[0];
      if (selected && selected.parentElement instanceof HTMLOptGroupElement && selected.parentElement.hidden) {
        select.value = "";
      }
    });

    wrapper.append(label, filter);
    select.parentElement.insertBefore(wrapper, select);
  });

  // Barra lateral plegable. El HTML la entrega abierta (sin JS se ve completa);
  // aquí se cierra en pantallas estrechas y se reabre al volver a escritorio.
  const navs = document.querySelectorAll("details[data-responsive-nav]");
  if (navs.length > 0) {
    const desktop = window.matchMedia("(min-width: 64.0625rem)");
    const sync = () => {
      navs.forEach((details) => {
        details.open = desktop.matches;
      });
    };
    sync();
    desktop.addEventListener("change", sync);
  }
});
