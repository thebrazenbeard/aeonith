"use strict";

/* Aeonith's browser code never persists manuscript text, access tokens or reviews. */
const byId = (id) => document.getElementById(id);
const form = byId("review-form");
const titleInput = byId("work-title");
const manuscriptInput = byId("manuscript");
const fileInput = byId("manuscript-file");
const importStatusNode = byId("import-status");
const tokenInput = byId("service-token");
const tokenLabel = byId("service-token-label");
const tokenNote = byId("token-note");
const sessionControls = byId("session-controls");
const sessionSignInButton = byId("session-sign-in");
const sessionSignOutButton = byId("session-sign-out");
const authStatusNode = byId("auth-status");
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
const MAX_IMPORT_BYTES = 65536;
const MAX_DOCX_BYTES = 2 * 1024 * 1024;
const DOCX_PARSE_TIMEOUT_MS = 8000;
const MAX_LENSES = 14;

// Display the remote-access warning for Tailscale's HTTPS machine.tailnet.ts.net
// hostnames only. Never construct endpoints or trust a URL supplied by a user.
if (window.location.protocol === "https:" &&
    /^[a-z0-9-]+\.[a-z0-9-]+\.ts\.net$/.test(window.location.hostname.toLowerCase())) {
  byId("funnel-privacy-note").hidden = false;
}

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
let manuscriptRevision = 0;
let latestFileSelection = 0;
let browserSessionActive = false;
let authRequestInFlight = false;
let authStateVersion = 0;

function updateAccessUI(active, message) {
  browserSessionActive = active;
  // A successful session must not leave a hidden bearer value in the DOM.
  if (active) tokenInput.value = "";
  tokenLabel.hidden = active;
  // The form stylesheet sets labels to display:block, so enforce hidden there.
  tokenLabel.style.display = active ? "none" : "";
  tokenInput.hidden = active;
  tokenNote.hidden = active;
  sessionSignInButton.hidden = active;
  sessionSignOutButton.hidden = !active;
  authStatusNode.textContent = message || (active ?
    "This browser is signed in for up to seven days. You can sign out at any time." :
    "Not signed in. Enter the operator-issued service token to review or authorize this browser.");
}

async function checkBrowserSession() {
  const version = authStateVersion;
  if (window.location.protocol !== "https:") {
    sessionControls.hidden = true;
    updateAccessUI(false, "Local HTTP: enter your service token for each review. Browser sessions require HTTPS.");
    return;
  }
  try {
    const response = await fetch("/api/session", {
      method: "GET", credentials: "same-origin", redirect: "error", cache: "no-store"
    });
    if (!response.ok) throw new Error("Session status unavailable");
    const data = await response.json();
    if (!data || typeof data.authenticated !== "boolean") throw new Error("Invalid session status");
    if (version !== authStateVersion) return;
    updateAccessUI(data.authenticated);
  } catch {
    if (version !== authStateVersion) return;
    updateAccessUI(false, "Saved session status unavailable. You can still use a service token for reviews.");
  }
}

sessionSignInButton.addEventListener("click", async () => {
  if (authRequestInFlight || requestInFlight) return;
  const token = tokenInput.value.trim();
  if (!token) {
    updateAccessUI(false, "Enter your service access token first to authorize this browser.");
    tokenInput.focus();
    return;
  }
  authRequestInFlight = true;
  authStateVersion += 1;
  sessionSignInButton.disabled = true;
  authStatusNode.textContent = "Authorizing this browser…";
  try {
    const response = await fetch("/api/session", {
      method: "POST",
      headers: { "Authorization": `Bearer ${token}`, "Accept": "application/json" },
      credentials: "same-origin", redirect: "error", cache: "no-store"
    });
    if (!response.ok) throw new Error(response.status === 401 ? "Token was rejected." : "Session could not be established.");
    const data = await response.json();
    if (!data || data.authenticated !== true) throw new Error("Server did not confirm the session.");
    // A successful Set-Cookie response does not guarantee that a browser with
    // cookies disabled actually retained it. Confirm the round trip before
    // concealing the token input or promising tokenless reviews.
    const verifiedResponse = await fetch("/api/session", {
      method: "GET", credentials: "same-origin", redirect: "error", cache: "no-store"
    });
    if (!verifiedResponse.ok) throw new Error("The browser session could not be verified.");
    const verified = await verifiedResponse.json();
    if (!verified || verified.authenticated !== true) {
      throw new Error("This browser did not retain the secure cookie. Continue using the service token for reviews.");
    }
    // Clear the bearer from the page once the server has issued an HttpOnly cookie.
    tokenInput.value = "";
    updateAccessUI(true);
  } catch (error) {
    updateAccessUI(false, error && error.message ? error.message + " Your token has not been stored." :
      "Could not authorize this browser. Token-only reviews remain available.");
  } finally {
    authRequestInFlight = false;
    sessionSignInButton.disabled = false;
  }
});

sessionSignOutButton.addEventListener("click", async () => {
  if (authRequestInFlight || requestInFlight) return;
  authRequestInFlight = true;
  authStateVersion += 1;
  sessionSignOutButton.disabled = true;
  authStatusNode.textContent = "Signing out of this browser…";
  try {
    const response = await fetch("/api/session/logout", {
      method: "POST", credentials: "same-origin", redirect: "error", cache: "no-store"
    });
    if (!response.ok) throw new Error("Sign-out failed. Try again or clear this site's cookies.");
    const data = await response.json();
    if (!data || data.authenticated !== false) throw new Error("Sign-out was not confirmed.");
    tokenInput.value = "";
    updateAccessUI(false, "Signed out. Enter your service token before the next review.");
  } catch (error) {
    updateAccessUI(true, error && error.message ? error.message : "Sign-out unavailable; try again.");
  } finally {
    authRequestInFlight = false;
    sessionSignOutButton.disabled = false;
  }
});

void checkBrowserSession();

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
    401: "Access denied. Your browser session may have expired; sign in again or check the service token.",
    403: "The service declined this request. Check that you opened the page at the intended localhost or HTTPS service address.",
    413: "This submission exceeds a local service limit. Try a shorter excerpt or fewer critical lenses.",
    422: "The service could not validate the proposed critique. No result will be shown.",
    500: "The service encountered an internal error. No critique was generated.",
    502: "The model provider failed or returned an unusable result. No critique was generated.",
    503: "Local model reviews are disabled, unconfigured, or temporarily unavailable. No critique was returned; check service readiness before retrying.",
    504: "The local model or service timed out. The request may still be processing on the operator's computer."
  };
  const fallback = fixed[status] || `The service returned HTTP ${status}; no critique was generated.`;
  if (status >= 500 || [401, 403, 413].includes(status)) return fallback;
  const message = responseData && responseData.error && responseData.error.message;
  return typeof message === "string" && message.length <= 250 ? message : fallback;
}

manuscriptInput.addEventListener("input", () => {
  manuscriptRevision += 1;
  const size = manuscriptInput.value.length;
  countNode.textContent = `${size.toLocaleString()} / ${MAX_MANUSCRIPT_CHARS.toLocaleString()} characters`;
  // Disclosure applies to this particular writing, not future edits.
  consentInput.checked = false;
});
titleInput.addEventListener("input", () => { consentInput.checked = false; });

function extractDocxInWorker(buffer) {
  // An untrusted compressed document is never parsed on the UI thread or
  // sent to the Aeonith server. The worker streams only bounded Word XML.
  return new Promise((resolve, reject) => {
    if (typeof Worker !== "function") {
      reject(new Error("DOCX import requires Web Worker support in this browser."));
      return;
    }
    let worker;
    try { worker = new Worker("/docx-import-worker.js"); } catch {
      reject(new Error("This browser cannot start the local DOCX parser."));
      return;
    }
    let finished = false;
    const complete = (error, value) => {
      if (finished) return;
      finished = true;
      clearTimeout(timer);
      worker.terminate();
      if (error) reject(error);
      else resolve(value);
    };
    const timer = setTimeout(() => complete(new Error("DOCX parsing timed out; your writing was not changed.")), DOCX_PARSE_TIMEOUT_MS);
    worker.onmessage = (event) => {
      const message = event.data;
      if (!message || message.ok !== true || typeof message.xml !== "string") {
        complete(new Error(message && typeof message.error === "string" ? message.error : "The DOCX parser rejected this document."));
      } else {
        complete(null, message.xml);
      }
    };
    worker.onerror = () => complete(new Error("The local DOCX parser failed. Your writing was not changed."));
    worker.onmessageerror = () => complete(new Error("The local DOCX parser returned an unreadable result."));
    try { worker.postMessage({ buffer }, [buffer]); } catch {
      complete(new Error("The browser could not transfer this DOCX document to its local parser."));
    }
  });
}

function extractDocxText(xml) {
  // DOMParser is a Window API, not available in Web Workers. Only the
  // worker's strictly bounded document XML enters this detached XML DOM.
  // Never render, insert, or evaluate nodes from an imported document.
  if (typeof DOMParser !== "function" || typeof xml !== "string" ||
      xml.length > 2 * 1024 * 1024 || /<!DOCTYPE|<!ENTITY/i.test(xml)) {
    throw new Error("The browser cannot safely parse this Word document's XML.");
  }
  const documentXml = new DOMParser().parseFromString(xml, "application/xml");
  if (documentXml.getElementsByTagName("parsererror").length !== 0) {
    throw new Error("The Word document contains malformed XML.");
  }
  // Keep this as a literal namespace match while retaining the established
  // no-absolute-URL invariant for the browser script.
  const wordNamespace = "http:" + "//schemas.openxmlformats.org/wordprocessingml/2006/main";
  const root = documentXml.documentElement;
  if (!root || root.namespaceURI !== wordNamespace || root.localName !== "document") {
    throw new Error("The Word document XML has an unexpected root element.");
  }
  const body = root.getElementsByTagNameNS(wordNamespace, "body")[0];
  if (!body) throw new Error("The Word document has no readable body.");
  // Walk each element exactly once. Descendant searches inside every nested
  // paragraph/text node can otherwise turn attacker-controlled XML into
  // quadratic work or duplicate arbitrarily large descendant text.
  const walker = documentXml.createTreeWalker(body, NodeFilter.SHOW_ELEMENT);
  const lines = [];
  let pieces = [];
  let characters = 0;
  let visited = 0;
  const add = (value) => {
    characters += value.length;
    if (characters > MAX_MANUSCRIPT_CHARS) {
      throw new Error("The file exceeds 12,000 characters. No text was replaced or truncated; choose a shorter excerpt.");
    }
    pieces.push(value);
  };
  const flush = () => {
    if (pieces.length) lines.push(pieces.join(""));
    pieces = [];
  };
  let element;
  while ((element = walker.nextNode())) {
    if (++visited > 50000) {
      throw new Error("This Word document contains too many XML elements to import safely.");
    }
    if (element.namespaceURI !== wordNamespace) continue;
    if (element.localName === "altChunk") {
      throw new Error("This Word document uses unsupported embedded body content. Export it as plain text first.");
    }
    if (element.localName === "p") {
      flush();
    } else if (element.localName === "t") {
      let value = "";
      for (const child of element.childNodes) {
        if (child.nodeType !== 3 && child.nodeType !== 4) {
          throw new Error("This Word document contains unsupported nested text markup.");
        }
        value += child.nodeValue || "";
        if (characters + value.length > MAX_MANUSCRIPT_CHARS) {
          throw new Error("The file exceeds 12,000 characters. No text was replaced or truncated; choose a shorter excerpt.");
        }
      }
      add(value);
    } else if (element.localName === "tab") {
      add("\t");
    } else if (element.localName === "br" || element.localName === "cr") {
      add("\n");
    }
  }
  flush();
  const text = lines.join("\n\n");
  if (text.length > MAX_MANUSCRIPT_CHARS) {
    throw new Error("The file exceeds 12,000 characters. No text was replaced or truncated; choose a shorter excerpt.");
  }
  if (!text.trim() || text.includes("\u0000")) {
    throw new Error("This Word document contains no usable body text.");
  }
  return text;
}

fileInput.addEventListener("change", async () => {
  const file = fileInput.files && fileInput.files[0];
  if (!file) return;
  const selection = ++latestFileSelection;
  const originalRevision = manuscriptRevision;
  importStatusNode.textContent = "";
  try {
    if (requestInFlight) {
      importStatusNode.textContent = "Wait for the current critique to finish before importing another passage.";
      return;
    }
    // The file picker accept= filter is advisory; legacy .doc is binary and
    // cannot be renamed into a valid DOCX ZIP document.
    const isDocx = /\.docx$/i.test(file.name);
    if (!isDocx && !/\.(?:txt|text|md|markdown)$/i.test(file.name)) {
      importStatusNode.textContent = "Choose a UTF-8 text/Markdown file or Word .docx. Legacy .doc and PDF files must be converted first.";
      return;
    }
    if (file.size === 0 || file.size > (isDocx ? MAX_DOCX_BYTES : MAX_IMPORT_BYTES)) {
      importStatusNode.textContent = isDocx ? "DOCX files must be nonempty and no larger than 2 MiB. Choose a shorter document." :
        "The text file must be nonempty and no larger than 64 KiB. Import a shorter text excerpt.";
      return;
    }
    // Nothing is uploaded. Text is decoded locally; DOCX is parsed in an
    // isolated worker with ZIP metadata/CRC verification, streaming byte caps,
    // and timeout; only bounded XML is parsed into a detached DOM.
    const bytes = await file.arrayBuffer();
    const text = isDocx ? extractDocxText(await extractDocxInWorker(bytes)) :
      new TextDecoder("utf-8", { fatal: true }).decode(bytes);
    if (!text.trim() || text.includes("\u0000")) {
      importStatusNode.textContent = "The selected file does not contain usable plain text.";
      return;
    }
    if (text.length > MAX_MANUSCRIPT_CHARS) {
      importStatusNode.textContent = "The file exceeds 12,000 characters. No text was replaced or truncated; choose a shorter excerpt.";
      return;
    }
    // A delayed file read must never overwrite changes made in the editor,
    // nor a more recently selected file or a review in progress.
    if (selection !== latestFileSelection || originalRevision !== manuscriptRevision || requestInFlight) {
      importStatusNode.textContent = "Import cancelled because the editor or review state changed. Select the file again.";
      return;
    }
    if (manuscriptInput.value && !window.confirm("Replace the current editor text with this file's contents?")) {
      importStatusNode.textContent = "Import cancelled; your existing text is unchanged.";
      return;
    }
    manuscriptInput.value = text;
    manuscriptInput.dispatchEvent(new Event("input", { bubbles: true }));
    resetResults();
    clearError();
    statusNode.textContent = "Imported text is ready for a new critique.";
    importStatusNode.textContent = `Imported ${file.name} into the editor (${text.length.toLocaleString()} characters).`;
    manuscriptInput.focus();
  } catch (error) {
    importStatusNode.textContent = error && error.message && /\.docx$/i.test(file.name) ? error.message :
      "The file could not be read as UTF-8 text. Your existing writing was not replaced.";
  } finally {
    if (selection === latestFileSelection) fileInput.value = "";
  }
});

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
  if (!token && !browserSessionActive) return showError("Enter your service token or sign in this browser to continue.");
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
        ...(token ? { "Authorization": `Bearer ${token}` } : {})
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
    if (!response.ok) {
      if (response.status === 401 && browserSessionActive) {
        updateAccessUI(false, "Browser session expired or was revoked. Enter the token and sign in again.");
      }
      return showError(requestError(response.status, data));
    }
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
