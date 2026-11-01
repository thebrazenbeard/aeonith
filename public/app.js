"use strict";

/* Aeonith's browser code never persists manuscript text, access tokens or reviews. */
const byId = (id) => document.getElementById(id);
const form = byId("review-form");
const titleInput = byId("work-title");
const manuscriptInput = byId("manuscript");
const tokenInput = byId("service-token");
const consentInput = byId("disclosure");
const submitButton = byId("submit-button");
const runtimeStatusNode = byId("runtime-status");
const statusNode = byId("status");
const errorNode = byId("error");
const resultsNode = byId("results");
const emptyNode = byId("reading-empty");
const countNode = byId("character-count");
const copyButton = byId("copy-result");
const copyStatus = byId("copy-status");
const MAX_MANUSCRIPT_CHARS = 12000;
const MAX_LENSES = 14;

const lensLabels = Object.freeze({
  psychological: "Psychological",
  literary_thematic: "Literary & thematic",
  narrative_structure: "Narrative structure",
  character_development: "Character development",
  historical_cultural: "Historical & cultural",
  philosophical: "Philosophical",
  genre_specific: "Genre-specific",
  stylistic: "Stylistic",
  sociological: "Sociological",
  moral_ethical: "Moral & ethical",
  symbolic: "Symbolic",
  reader_response: "Reader response",
  linguistic: "Linguistic",
  comparative: "Comparative"
});

let plainTextReview = "";
let requestInFlight = false;

async function checkLocalService() {
  // Readiness is configuration only: this probe sends no writing or token and
  // never calls the model. An enabled model can still fail during inference.
  try {
    const response = await fetch("/healthz", {
      method: "GET", credentials: "same-origin", redirect: "error", cache: "no-store"
    });
    if (!response.ok) throw new Error("health unavailable");
    const status = await response.json();
    if (status && status.service === "aeonith" && status.review_configured === true) {
      runtimeStatusNode.textContent = "Local model configured · A successful review is not guaranteed.";
      runtimeStatusNode.classList.add("runtime-ready");
    } else if (status && status.service === "aeonith" && status.review_configured === false) {
      runtimeStatusNode.textContent = "Local model disabled or unconfigured · Set up a local model to enable reviews.";
    } else {
      runtimeStatusNode.textContent = "Local service returned an unexpected health result.";
    }
  } catch {
    runtimeStatusNode.textContent = "Local service readiness unavailable · Reviews may not be available.";
  }
}

void checkLocalService();

function element(tag, value, className) {
  const node = document.createElement(tag);
  if (typeof value === "string") node.textContent = value;
  if (className) node.className = className;
  return node;
}

function resetResults() {
  plainTextReview = "";
  resultsNode.hidden = true;
  emptyNode.hidden = false;
  copyStatus.textContent = "";
  ["result-provenance", "result-synthesis", "lens-results", "result-uncertainties", "result-challenges"]
    .forEach((id) => byId(id).replaceChildren());
}

function showError(message) {
  errorNode.textContent = message;
  errorNode.hidden = false;
  statusNode.textContent = "No critique was generated.";
}

function clearError() {
  errorNode.textContent = "";
  errorNode.hidden = true;
}

function renderList(target, heading, values, className) {
  if (!Array.isArray(values)) return [];
  const entries = values.filter((value) => typeof value === "string" && value.trim());
  if (!entries.length) return [];
  const section = element("section", undefined, className || "result-section");
  section.append(element("h4", heading));
  const list = element("ul");
  entries.forEach((value) => list.append(element("li", value)));
  section.append(list);
  target.append(section);
  return [heading, ...entries, ""];
}

function renderReview(review) {
  if (!review || review.schema_version !== "aeonith.review.v1" ||
      review.status !== "completed" || typeof review.synthesis !== "string" ||
      !Array.isArray(review.lens_reviews) || review.lens_reviews.length === 0) {
    throw new Error("The service returned an incomplete critique; nothing was displayed.");
  }

  resetResults();
  const textual = ["Aeonith — provisional literary critique", "", "Overall synthesis", review.synthesis, ""];
  const provenance = review.provenance;
  if (provenance && typeof provenance.provider_name === "string" && provenance.provider_name) {
    byId("result-provenance").append(element("p", "Model provider: " + provenance.provider_name + ". Interpretations are not formal verification."));
  } else {
    byId("result-provenance").append(element("p", "Model-generated interpretation; no formal verification."));
  }

  const synthesis = element("section", undefined, "result-section");
  synthesis.append(element("h4", "Overall synthesis"), element("p", review.synthesis));
  byId("result-synthesis").append(synthesis);

  const sectionTarget = byId("lens-results");
  review.lens_reviews.forEach((item, index) => {
    if (!item || typeof item.lens !== "string" || typeof item.analysis !== "string" ||
        !Object.prototype.hasOwnProperty.call(lensLabels, item.lens)) {
      throw new Error("The service returned a malformed lens analysis; nothing was displayed.");
    }
    const label = lensLabels[item.lens];
    const section = element("article", undefined, "result-section");
    section.append(element("h4", `${index + 1}. ${label}`));
    if (item.basis === "insufficient_text") {
      section.append(element("p", "Insufficient textual basis for a firm interpretation.", "lens-basis"));
    }
    section.append(element("p", item.analysis));
    textual.push(label, item.analysis);

    if (Array.isArray(item.support)) {
      item.support.forEach((support) => {
        if (support && typeof support.quote === "string" && support.quote) {
          section.append(element("blockquote", support.quote));
          textual.push("Quoted evidence: " + support.quote);
        }
      });
    }
    if (Array.isArray(item.limitations)) {
      const limits = item.limitations.filter((entry) => typeof entry === "string" && entry.trim());
      if (limits.length) {
        section.append(element("p", "Limitations", "lens-basis"));
        const list = element("ul");
        limits.forEach((entry) => list.append(element("li", entry)));
        section.append(list);
        textual.push("Limitations", ...limits);
      }
    }
    textual.push("");
    sectionTarget.append(section);
  });

  textual.push(...renderList(byId("result-uncertainties"), "Uncertainties", review.uncertainties));
  if (Array.isArray(review.challenges)) {
    textual.push(...renderList(byId("result-challenges"), "Questions worth testing",
      review.challenges.map((entry) => (entry && typeof entry.text === "string" ? entry.text : ""))));
  }
  plainTextReview = textual.join("\n");
  resultsNode.hidden = false;
  emptyNode.hidden = true;
  statusNode.textContent = "A critique was returned. It reflects model interpretation, not established literary fact.";
  resultsNode.focus();
}

function requestError(status, responseData) {
  const fixed = {
    400: "The request was invalid. Check the passage and selected lenses.",
    401: "Access denied. Check the service access token.",
    403: "The local service declined this request. Check that you opened the page on the same local host.",
    413: "This submission exceeds a local service limit. Try a shorter excerpt or fewer critical lenses.",
    422: "The service could not validate the proposed critique. No result will be shown.",
    500: "The service encountered an internal error. No critique was generated.",
    502: "The model provider failed or returned an unusable result. No critique was generated.",
    503: "Local model reviews are disabled, unconfigured, or temporarily unavailable. No critique was returned; check service readiness before retrying.",
    504: "The local model or service timed out. The request may still be processing on your computer."
  };
  const fallback = fixed[status] || `The service returned HTTP ${status}; no critique was generated.`;
  if (status >= 500 || [401, 403, 413].includes(status)) return fallback;
  const message = responseData && responseData.error && responseData.error.message;
  return typeof message === "string" && message.length <= 250 ? message : fallback;
}

manuscriptInput.addEventListener("input", () => {
  const size = manuscriptInput.value.length;
  countNode.textContent = `${size.toLocaleString()} / ${MAX_MANUSCRIPT_CHARS.toLocaleString()} characters`;
  // Disclosure applies to this particular writing, not future edits.
  consentInput.checked = false;
});
titleInput.addEventListener("input", () => { consentInput.checked = false; });

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  // Pressing Enter or dispatching a second submit event must not start
  // another provider request while the first is still in flight.
  if (requestInFlight) return;
  clearError();
  resetResults();

  const manuscript = manuscriptInput.value;
  const title = titleInput.value;
  const lenses = Array.from(form.querySelectorAll('input[name="lenses"]:checked'), (input) => input.value);
  const token = tokenInput.value.trim();
  if (!manuscript.trim()) return showError("Paste a manuscript or excerpt before requesting criticism.");
  if (manuscript.length > MAX_MANUSCRIPT_CHARS) return showError("Submit an excerpt of 12,000 characters or fewer.");
  if (title.length > 500) return showError("The title must contain 500 characters or fewer.");
  if (!lenses.length) return showError("Select at least one critical lens.");
  if (lenses.length > MAX_LENSES) return showError("Choose no more than fourteen lenses for a review.");
  if (!token) return showError("Enter your service access token to continue.");
  if (!consentInput.checked) return showError("Confirm that you have permission to submit this writing to the local model.");
  const payload = {
    schema_version: "aeonith.review.v1",
    work: { title, text: manuscript },
    lenses
  };
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 120000);
  requestInFlight = true;
  submitButton.disabled = true;
  form.setAttribute("aria-busy", "true");
  statusNode.textContent = `The service is preparing a critical reading across ${lenses.length} selected lens${lenses.length === 1 ? "" : "es"}…`;

  try {
    const response = await fetch("/api/review", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": `Bearer ${token}`
      },
      body: JSON.stringify(payload),
      signal: controller.signal,
      cache: "no-store",
      credentials: "same-origin",
      redirect: "error"
    });
    const responseText = await response.text();
    let data;
    try { data = JSON.parse(responseText); } catch { data = null; }
    if (!response.ok) return showError(requestError(response.status, data));
    if (!data || data.status !== "completed") return showError(requestError(503, data));
    try { renderReview(data); } catch {
      resetResults();
      showError("The service returned an incomplete or malformed critique. Nothing was displayed.");
    }
  } catch (error) {
    if (error && error.name === "AbortError") {
      showError("The browser stopped waiting after two minutes. The local model request may still be running.");
    } else {
      showError("The local service could not be reached. The earlier request might still be running; check its status with the operator before resubmitting.");
    }
  } finally {
    clearTimeout(timer);
    // Local model consent is specific to the submitted text, not future edits.
    consentInput.checked = false;
    requestInFlight = false;
    submitButton.disabled = false;
    form.removeAttribute("aria-busy");
  }
});

copyButton.addEventListener("click", async () => {
  copyStatus.textContent = "";
  if (!plainTextReview) return;
  try {
    await navigator.clipboard.writeText(plainTextReview);
    copyStatus.textContent = "Critique copied as plain text.";
  } catch {
    copyStatus.textContent = "Copying is unavailable in this browser. Select the visible text manually.";
  }
});
