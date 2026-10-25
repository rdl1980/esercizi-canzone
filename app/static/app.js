/* Logica lato browser: chiamate alle API REST, errori nel form, aggiornamento dello stato. */
const App = (() => {
  async function api(metodo, url, corpo) {
    const opzioni = { method: metodo, headers: { Accept: "application/json" } };
    if (corpo !== undefined) {
      opzioni.headers["Content-Type"] = "application/json";
      opzioni.body = JSON.stringify(corpo);
    }
    let risposta;
    try {
      risposta = await fetch(url, opzioni);
    } catch (e) {
      throw new Error("Impossibile contattare il server. Controlla la connessione.");
    }
    if (risposta.status === 204) return null;
    let dati = null;
    try { dati = await risposta.json(); } catch (e) { /* risposta senza JSON */ }
    if (risposta.status === 401 && !location.pathname.startsWith("/login") && !location.pathname.startsWith("/registrati")) {
      location.href = "/login";
      throw new Error("Sessione scaduta: accedi di nuovo.");
    }
    if (!risposta.ok) {
      const msg = (dati && (typeof dati.detail === "string" ? dati.detail : JSON.stringify(dati.detail))) || `Errore ${risposta.status}`;
      throw new Error(msg);
    }
    return dati;
  }

  function mostraErrore(el, messaggio) {
    if (!el) return;
    if (messaggio) { el.textContent = messaggio; el.hidden = false; el.scrollIntoView({ block: "nearest" }); }
    else { el.textContent = ""; el.hidden = true; }
  }

  function datiForm(form) {
    const fd = new FormData(form);
    const d = {};
    for (const [k, v] of fd.entries()) d[k] = v;
    if ("n_parole" in d) {
      const n = d.n_parole.trim();
      d.n_parole = n === "" ? 0 : Number(n);
      if (!Number.isInteger(d.n_parole)) d.n_parole = n; // lascia al server il messaggio d'errore
    }
    return d;
  }

  function esc(s) {
    return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  // --- login / registrazione -------------------------------------------------
  function formAuth(form) {
    const errore = form.querySelector("#errore");
    form.addEventListener("submit", async ev => {
      ev.preventDefault();
      mostraErrore(errore, "");
      const btn = form.querySelector("button[type=submit]");
      btn.disabled = true;
      try {
        await api("POST", form.dataset.api, datiForm(form));
        location.href = form.dataset.vai || "/";
      } catch (e) {
        mostraErrore(errore, e.message);
      } finally {
        btn.disabled = false;
      }
    });
  }

  // --- creazione / rigenerazione -----------------------------------------------
  function formEsercizio(form) {
    const errore = form.querySelector("#errore");
    form.addEventListener("submit", async ev => {
      ev.preventDefault();
      mostraErrore(errore, "");
      const btn = form.querySelector("button[type=submit]");
      btn.disabled = true;
      try {
        const e = await api("POST", form.dataset.api, datiForm(form));
        location.href = `/esercizi/${e.id}`;
        if (location.pathname === `/esercizi/${e.id}`) location.reload();
      } catch (e) {
        mostraErrore(errore, e.message);
        btn.disabled = false;
      }
    });
  }

  // --- impostazioni (modalità locale) ----------------------------------------------
  function formImpostazioni(form) {
    const errore = form.querySelector("#errore");
    const ok = form.querySelector("#ok");
    form.addEventListener("submit", async ev => {
      ev.preventDefault();
      mostraErrore(errore, "");
      ok.hidden = true;
      const btn = form.querySelector("button[type=submit]");
      btn.disabled = true;
      btn.textContent = "Provo la chiave…";
      try {
        const r = await api("POST", form.dataset.api, datiForm(form));
        ok.hidden = false;
        form.querySelector("[name=chiave]").value = "";
        form.querySelector("[name=chiave]").placeholder = `salvata (termina con …${r.chiave_fine}): lascia vuoto per non cambiarla`;
      } catch (e) {
        mostraErrore(errore, e.message);
      } finally {
        btn.disabled = false;
        btn.textContent = "Salva e prova la chiave";
      }
    });
  }

  // --- elenco --------------------------------------------------------------------
  function cartaEsercizio(e) {
    const titolo = e.titolo_mostrato;
    const data = e.creato_il ? new Date(e.creato_il).toLocaleString("it-IT", { dateStyle: "short", timeStyle: "short" }) : "";
    const anteprima = e.anteprima_url
      ? `<a href="/esercizi/${e.id}"><img class="anteprima-mini" src="${e.anteprima_url}?t=${encodeURIComponent(e.aggiornato_il || "")}" alt="Anteprima"></a>`
      : "";
    const pdf = e.pdf_url ? `<a class="bottone primario" href="${e.pdf_url}">⬇ PDF</a>` : "";
    const fase = e.stato === "errore" ? `<p class="errore">${esc(e.errore || "Errore")}</p>`
      : (e.stato === "pronto" ? "" : `<p class="meta">${esc(e.fase || "")} · ${e.progresso || 0}%</p>`);
    return `<article class="carta-es" data-id="${e.id}">
      <div class="intestazione" style="margin:0"><h3><a href="/esercizi/${e.id}">${esc(titolo)}</a></h3>
        <span class="stato" data-stato="${e.stato}">${esc(e.stato_etichetta)}</span></div>
      <div class="meta">${esc(e.modalita_etichetta)} · ${e.n_parole ? e.n_parole + " parole" : "parole: decidi tu"} · ${esc(data)}</div>
      ${anteprima}${fase}
      <div class="azioni">${pdf}<a class="bottone" href="/esercizi/${e.id}">Apri</a>
        <button type="button" class="bottone pericolo btn-elimina" data-id="${e.id}" ${e.stato === "in_lavorazione" ? "disabled" : ""}>Elimina</button></div>
    </article>`;
  }

  function elenco() {
    const cont = document.getElementById("elenco");
    const errore = document.getElementById("errore");
    let timer = null;
    async function carica() {
      try {
        const { esercizi } = await api("GET", "/api/esercizi");
        if (!esercizi.length) {
          cont.innerHTML = document.getElementById("tpl-vuoto").innerHTML;
        } else {
          cont.innerHTML = esercizi.map(cartaEsercizio).join("");
        }
        const inCorso = esercizi.some(e => e.stato === "coda" || e.stato === "in_lavorazione");
        clearTimeout(timer);
        if (inCorso) timer = setTimeout(carica, 4000);
      } catch (e) {
        mostraErrore(errore, e.message);
      }
    }
    cont.addEventListener("click", async ev => {
      const btn = ev.target.closest(".btn-elimina");
      if (!btn) return;
      if (!confirm("Eliminare questo esercizio? Il PDF e le immagini verranno cancellati.")) return;
      try {
        await api("DELETE", `/api/esercizi/${btn.dataset.id}`);
        carica();
      } catch (e) {
        mostraErrore(errore, e.message);
      }
    });
    carica();
  }

  // --- dettaglio -----------------------------------------------------------------
  function dettaglio(id, inCorso) {
    const $ = s => document.querySelector(s);
    const formRig = $("#form-rigenera");
    const btnElimina = $("#btn-elimina");

    function aggiorna(e) {
      $("#titolo").textContent = e.titolo_mostrato;
      const stato = $("#stato");
      stato.dataset.stato = e.stato;
      stato.textContent = e.stato_etichetta;
      const lavorando = e.stato === "coda" || e.stato === "in_lavorazione";
      $("#avanzamento").hidden = !lavorando;
      $("#barra").style.width = `${e.progresso || 0}%`;
      $("#fase").textContent = e.fase || "";
      $("#percento").textContent = e.progresso || 0;
      mostraErrore($("#errore-generazione"), e.stato === "errore" ? e.errore : "");
      $("#pronto").hidden = e.stato !== "pronto";
      if (e.stato === "pronto") {
        $("#parole").textContent = (e.parole || []).join(", ");
        $("#anteprima").src = `${e.anteprima_url}?t=${encodeURIComponent(e.aggiornato_il || "")}`;
      }
      $("#dato-modalita").textContent = e.modalita_etichetta;
      $("#dato-n-parole").textContent = e.n_parole ? e.n_parole : "decidi tu";
      const video = $("#dato-video");
      video.href = e.url;
      video.textContent = e.titolo_video || e.url;
      $("#btn-rigenera").disabled = lavorando;
      btnElimina.disabled = e.stato === "in_lavorazione";
      return lavorando;
    }

    async function sonda() {
      try {
        const e = await api("GET", `/api/esercizi/${id}`);
        if (aggiorna(e)) setTimeout(sonda, 3000);
      } catch (err) {
        mostraErrore($("#errore-generazione"), err.message);
        setTimeout(sonda, 8000);
      }
    }
    if (inCorso) sonda();

    const errore = formRig.querySelector("#errore");
    formRig.addEventListener("submit", async ev => {
      ev.preventDefault();
      mostraErrore(errore, "");
      try {
        const e = await api("POST", formRig.dataset.api, datiForm(formRig));
        aggiorna(e);
        window.scrollTo({ top: 0, behavior: "smooth" });
        sonda();
      } catch (err) {
        mostraErrore(errore, err.message);
      }
    });
    btnElimina.addEventListener("click", async () => {
      if (!confirm("Eliminare questo esercizio? Il PDF e le immagini verranno cancellati.")) return;
      try {
        await api("DELETE", `/api/esercizi/${id}`);
        location.href = "/";
      } catch (err) {
        mostraErrore(errore, err.message);
      }
    });
  }

  // --- avvio ---------------------------------------------------------------------
  document.addEventListener("DOMContentLoaded", () => {
    const btnLogout = document.getElementById("btn-logout");
    if (btnLogout) btnLogout.addEventListener("click", async () => {
      try { await api("POST", "/api/auth/logout"); } finally { location.href = "/login"; }
    });
    const fl = document.getElementById("form-login");
    if (fl) formAuth(fl);
    const fr = document.getElementById("form-registrazione");
    if (fr) formAuth(fr);
  });

  return { api, elenco, formEsercizio, dettaglio, formImpostazioni };
})();
