"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const chatScript = fs.readFileSync(
  path.join(__dirname, "../../static/js/chat.js"),
  "utf8",
);

class FakeEvent {
  constructor(type) {
    this.type = type;
    this.defaultPrevented = false;
  }

  preventDefault() {
    this.defaultPrevented = true;
  }
}

class FakeClassList {
  constructor(element) {
    this.element = element;
    this.names = new Set();
  }

  replace(value) {
    this.names = new Set(value.split(/\s+/).filter(Boolean));
  }

  toggle(name, force) {
    const shouldAdd = force === undefined ? !this.names.has(name) : Boolean(force);
    if (shouldAdd) {
      this.names.add(name);
    } else {
      this.names.delete(name);
    }
    return shouldAdd;
  }

  contains(name) {
    return this.names.has(name);
  }
}

class FakeElement {
  constructor(tagName = "div") {
    this.tagName = tagName.toUpperCase();
    this.children = [];
    this.parentElement = null;
    this.listeners = new Map();
    this.attributes = {};
    this.dataset = {};
    this.style = {};
    this.classList = new FakeClassList(this);
    this.className = "";
    this.textContent = "";
    this.value = "";
    this.disabled = false;
    this.scrollHeight = 24;
    this.scrollTop = 0;
  }

  set className(value) {
    this._className = value;
    this.classList?.replace(value);
  }

  get className() {
    return this._className;
  }

  setAttribute(name, value) {
    this.attributes[name] = String(value);
  }

  getAttribute(name) {
    return this.attributes[name] ?? null;
  }

  addEventListener(type, listener) {
    const listeners = this.listeners.get(type) || [];
    listeners.push(listener);
    this.listeners.set(type, listeners);
  }

  dispatchEvent(event) {
    if (this.disabled && event.type === "click") {
      return true;
    }
    event.target = this;
    for (const listener of this.listeners.get(event.type) || []) {
      listener(event);
    }
    return !event.defaultPrevented;
  }

  click() {
    this.dispatchEvent(new FakeEvent("click"));
  }

  append(...elements) {
    for (const element of elements) {
      if (element.parentElement) {
        element.remove();
      }
      element.parentElement = this;
      this.children.push(element);
    }
  }

  remove() {
    if (!this.parentElement) {
      return;
    }
    const siblings = this.parentElement.children;
    const index = siblings.indexOf(this);
    if (index >= 0) {
      siblings.splice(index, 1);
    }
    this.parentElement = null;
  }

  matches(selector) {
    if (selector.startsWith(".")) {
      return selector
        .slice(1)
        .split(".")
        .every((name) => this.classList.contains(name));
    }
    if (selector.startsWith("#")) {
      return this.attributes.id === selector.slice(1);
    }
    return this.tagName.toLowerCase() === selector.toLowerCase();
  }

  querySelector(selector) {
    for (const child of this.children) {
      if (child.matches(selector)) {
        return child;
      }
      const descendant = child.querySelector(selector);
      if (descendant) {
        return descendant;
      }
    }
    return null;
  }

  querySelectorAll(selector) {
    const matches = [];
    for (const child of this.children) {
      if (child.matches(selector)) {
        matches.push(child);
      }
      matches.push(...child.querySelectorAll(selector));
    }
    return matches;
  }

  focus() {
    this.focused = true;
  }
}

function jsonResponse(data, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => data,
  };
}

function setup({
  recognitionSupported = true,
  speechSynthesisSupported = true,
  fetchImpl = async () => jsonResponse({ status: "success", response: "Assistant reply." }),
  voices = [{ name: "English", lang: "en-US", default: true }],
} = {}) {
  const selectors = [
    "#chat-form",
    "#message-input",
    "#selected-role",
    "#send-button",
    "#mic-button",
    "#speech-status",
    "#conversation",
    "#tts-status",
    "#ai-mode-status",
    ".welcome-note",
  ];
  const elements = Object.fromEntries(
    selectors.map((selector) => [selector, new FakeElement()]),
  );
  elements["#chat-form"].action = "/api/assistant/execute";
  elements["#selected-role"].value = "HR";

  const recognitionInstances = [];
  const submitPromises = [];
  class MockRecognition {
    constructor() {
      this.startCalls = 0;
      this.stopCalls = 0;
      recognitionInstances.push(this);
    }

    start() {
      this.startCalls += 1;
    }

    stop() {
      this.stopCalls += 1;
    }

    emitResult(transcript) {
      const result = [{ transcript }];
      result.isFinal = true;
      this.onresult?.({ resultIndex: 0, results: [result] });
    }

    emitError(error) {
      this.onerror?.({ error });
    }

    emitEnd() {
      this.onend?.();
    }
  }

  const utterances = [];
  class MockUtterance {
    constructor(text) {
      this.text = text;
      utterances.push(this);
    }
  }

  const speechCalls = [];
  const speechSynthesis = {
    getVoices: () => voices,
    speak: (utterance) => speechCalls.push(utterance),
    cancelCalls: 0,
    cancel() {
      this.cancelCalls += 1;
    },
  };

  const window = {};
  if (recognitionSupported) {
    window.SpeechRecognition = MockRecognition;
  }
  if (speechSynthesisSupported) {
    window.speechSynthesis = speechSynthesis;
    window.SpeechSynthesisUtterance = MockUtterance;
  }

  const document = {
    querySelector: (selector) => elements[selector] || null,
    createElement: (tagName) => new FakeElement(tagName),
    createElementNS: (_namespace, tagName) => new FakeElement(tagName),
  };
  elements["#chat-form"].requestSubmit = () => {
    const listener = elements["#chat-form"].listeners.get("submit")[0];
    const pending = listener(new FakeEvent("submit"));
    submitPromises.push(pending);
    return pending;
  };
  const context = {
    document,
    window,
    navigator: { language: "en-US" },
    fetch: fetchImpl,
    Event: FakeEvent,
    console: { error() {} },
  };
  if (speechSynthesisSupported) {
    context.SpeechSynthesisUtterance = MockUtterance;
  }
  vm.runInNewContext(chatScript, context, { filename: "chat.js" });

  async function submit() {
    const listener = elements["#chat-form"].listeners.get("submit")[0];
    const event = new FakeEvent("submit");
    const pending = listener(event);
    assert.equal(event.defaultPrevented, true);
    return pending;
  }

  return {
    elements,
    recognitionInstances,
    speechCalls,
    speechSynthesis,
    submitPromises,
    submit,
    utterances,
  };
}

function latestAssistantBubble(elements) {
  const messages = elements["#conversation"].querySelectorAll(".message.assistant");
  return messages.at(-1)?.querySelector(".message-bubble");
}

test("unsupported speech recognition reports a graceful fallback", () => {
  const { elements } = setup({ recognitionSupported: false });

  elements["#mic-button"].click();

  assert.match(elements["#speech-status"].textContent, /unavailable|not supported/i);
  assert.equal(elements["#message-input"].disabled, false);
});

test("the assistant mode indicator updates after an OpenAI-backed response", async () => {
  const { elements, submit } = setup({
    fetchImpl: async () => jsonResponse({
      status: "success",
      response: "Reply.",
      llm_mode: "openai",
    }),
  });
  elements["#message-input"].value = "Hello";

  await submit();

  assert.equal(
    elements["#ai-mode-status"].textContent,
    "AI mode: OpenAI connected.",
  );
});

test("a final recognition transcript is inserted for review without auto-submit", () => {
  let fetchCalls = 0;
  const { elements, recognitionInstances } = setup({
    fetchImpl: async () => {
      fetchCalls += 1;
      return jsonResponse({ status: "success", response: "Reply." });
    },
  });

  elements["#mic-button"].click();
  const recognition = recognitionInstances[0];
  recognition.onstart();
  recognition.emitResult("Check my leave balance.");

  assert.equal(elements["#message-input"].value, "Check my leave balance.");
  assert.match(elements["#speech-status"].textContent, /review or edit/i);
  assert.equal(fetchCalls, 0);
});

test("an empty recognition result leaves the composer unchanged and reports no speech", () => {
  const { elements, recognitionInstances } = setup();
  elements["#message-input"].value = "Existing draft";

  elements["#mic-button"].click();
  recognitionInstances[0].onstart();
  recognitionInstances[0].emitResult("   ");
  recognitionInstances[0].emitEnd();

  assert.equal(elements["#message-input"].value, "Existing draft");
  assert.match(elements["#speech-status"].textContent, /no speech/i);
});

test("permission and recognition errors are presented to the user", () => {
  const { elements, recognitionInstances } = setup();
  elements["#mic-button"].click();
  const recognition = recognitionInstances[0];

  recognition.emitError("not-allowed");
  assert.match(elements["#speech-status"].textContent, /permission was denied/i);
  recognition.emitEnd();

  elements["#mic-button"].click();
  recognitionInstances[1].emitError("network");
  assert.match(elements["#speech-status"].textContent, /network connection/i);
});

test("recognition is stopped before submission and late results are discarded", async () => {
  let resolveFetch;
  const { elements, recognitionInstances } = setup({
    fetchImpl: () => new Promise((resolve) => {
      resolveFetch = resolve;
    }),
  });
  elements["#message-input"].value = "Submitted text";
  elements["#mic-button"].click();
  const recognition = recognitionInstances[0];
  recognition.onstart();

  const listener = elements["#chat-form"].listeners.get("submit")[0];
  const pending = listener(new FakeEvent("submit"));

  assert.equal(recognition.stopCalls, 1);
  recognition.emitResult("Late transcript");
  assert.equal(elements["#message-input"].value, "");

  resolveFetch(jsonResponse({ status: "success", response: "Done." }));
  await pending;
  assert.equal(elements["#message-input"].value, "");
  assert.equal(elements["#mic-button"].disabled, true);
  recognition.emitEnd();
  assert.equal(elements["#mic-button"].disabled, false);
  assert.equal(elements["#mic-button"].getAttribute("aria-pressed"), "false");
});

test("submission sends selected role and query to the existing assistant endpoint", async () => {
  let request;
  const { elements, submit } = setup({
    fetchImpl: async (url, options) => {
      request = { url, options };
      return jsonResponse({ status: "success", response: "Reply." });
    },
  });
  elements["#selected-role"].value = "IT Support";
  elements["#message-input"].value = "Cannot connect to Wi-Fi.";

  await submit();

  assert.equal(request.url, "/api/assistant/execute");
  assert.equal(request.options.method, "POST");
  assert.equal(request.options.headers["Content-Type"], "application/json");
  assert.deepEqual(JSON.parse(request.options.body), {
    selected_role: "IT Support",
    query: "Cannot connect to Wi-Fi.",
  });
});

test("a continued conversation sends its existing conversation identifier", async () => {
  const requests = [];
  const { elements, submit } = setup({
    fetchImpl: async (_url, options) => {
      requests.push(JSON.parse(options.body));
      return jsonResponse({
        status: "clarification_required",
        response: "What is your application ID?",
        conversation_id: "a".repeat(32),
      });
    },
  });
  elements["#selected-role"].value = "Admissions";
  elements["#message-input"].value = "Check my application status.";
  await submit();
  elements["#message-input"].value = "APP-42";
  await submit();

  assert.deepEqual(requests[0], {
    selected_role: "Admissions",
    query: "Check my application status.",
  });
  assert.deepEqual(requests[1], {
    selected_role: "Admissions",
    query: "APP-42",
    conversation_id: "a".repeat(32),
  });
});

test("duplicate Enter submissions are ignored and controls reset after success", async () => {
  let resolveFetch;
  let fetchCalls = 0;
  const { elements, submitPromises } = setup({
    fetchImpl: () => {
      fetchCalls += 1;
      return new Promise((resolve) => {
        resolveFetch = resolve;
      });
    },
  });
  elements["#message-input"].value = "Check my balance.";

  const enter = new FakeEvent("keydown");
  enter.key = "Enter";
  enter.shiftKey = false;
  enter.isComposing = false;
  elements["#message-input"].dispatchEvent(enter);
  const first = submitPromises[0];
  elements["#message-input"].dispatchEvent(enter);
  const second = submitPromises[1];
  assert.equal(fetchCalls, 1);
  assert.equal(elements["#send-button"].disabled, true);
  assert.equal(elements["#message-input"].disabled, true);
  assert.equal(elements["#selected-role"].disabled, true);
  assert.equal(elements["#mic-button"].disabled, true);
  assert.ok(elements["#conversation"].querySelector(".processing"));

  resolveFetch(jsonResponse({ status: "success", response: "Reply." }));
  await Promise.all([first, second]);

  assert.equal(elements["#send-button"].disabled, false);
  assert.equal(elements["#message-input"].disabled, false);
  assert.equal(elements["#selected-role"].disabled, false);
  assert.equal(elements["#mic-button"].disabled, false);
  assert.equal(elements["#conversation"].querySelector(".processing"), null);
});

test("API failures restore the submitted message and show the server error", async () => {
  const { elements, submit } = setup({
    fetchImpl: async () => jsonResponse({ error: "Invalid role." }, 400),
  });
  elements["#message-input"].value = "My original message";

  await submit();

  assert.equal(elements["#message-input"].value, "My original message");
  assert.equal(elements["#message-input"].disabled, false);
  assert.match(
    latestAssistantBubble(elements).textContent,
    /Invalid role\./,
  );
});

test("network and non-JSON HTTP failures are handled and drafts remain retryable", async (t) => {
  await t.test("network failure", async () => {
    const { elements, submit } = setup({
      fetchImpl: async () => {
        throw new TypeError("network unavailable");
      },
    });
    elements["#message-input"].value = "Try again";

    await submit();

    assert.equal(elements["#message-input"].value, "Try again");
    assert.match(latestAssistantBubble(elements).textContent, /Unable to reach/i);
    assert.equal(elements["#mic-button"].disabled, false);
  });

  await t.test("non-JSON HTTP response", async () => {
    const { elements, submit } = setup({
      fetchImpl: async () => ({
        ok: false,
        status: 502,
        json: async () => {
          throw new SyntaxError("not JSON");
        },
      }),
    });
    elements["#message-input"].value = "Retry this";

    await submit();

    assert.equal(elements["#message-input"].value, "Retry this");
    assert.match(latestAssistantBubble(elements).textContent, /HTTP 502/);
  });
});

test("failure recovery preserves newer composer text", async () => {
  const { elements, submit } = setup({
    fetchImpl: async () => jsonResponse({ error: "Request failed." }, 503),
  });
  elements["#message-input"].value = "Submitted message";
  const pending = submit();
  elements["#message-input"].value = "Newer draft";

  await pending;

  assert.equal(elements["#message-input"].value, "Newer draft");
});

test("assistant responses can be spoken using browser speech synthesis", async () => {
  const { elements, speechCalls, submit } = setup();
  elements["#message-input"].value = "Check leave balance.";
  await submit();

  const button = elements["#conversation"].querySelector(".speak-button");
  button.click();

  assert.equal(speechCalls.length, 1);
  assert.equal(speechCalls[0].text, "Assistant reply.");
  assert.equal(speechCalls[0].lang, "en-US");
  assert.equal(speechCalls[0].voice.name, "English");
  assert.equal(button.getAttribute("aria-pressed"), "true");
});

test("speech playback can be cancelled", async () => {
  const { elements, speechSynthesis, submit } = setup();
  elements["#message-input"].value = "Question";
  await submit();
  const button = elements["#conversation"].querySelector(".speak-button");

  button.click();
  button.click();

  assert.equal(speechSynthesis.cancelCalls, 1);
  assert.equal(button.getAttribute("aria-pressed"), "false");
  assert.match(elements["#tts-status"].textContent, /stopped/i);
});

test("missing speech synthesis disables playback without breaking chat", async () => {
  const { elements, submit } = setup({ speechSynthesisSupported: false });
  elements["#message-input"].value = "Question";

  await submit();

  assert.match(elements["#tts-status"].textContent, /not supported/i);
  assert.equal(elements["#conversation"].querySelector(".speak-button").disabled, true);
});

test("playback errors reset the control and allow another attempt", async () => {
  const { elements, speechCalls, submit, utterances } = setup();
  elements["#message-input"].value = "Question";
  await submit();
  const button = elements["#conversation"].querySelector(".speak-button");

  button.click();
  utterances[0].onerror({ error: "synthesis-failed" });

  assert.equal(button.getAttribute("aria-pressed"), "false");
  assert.match(elements["#tts-status"].textContent, /playback failed/i);
  button.click();
  assert.equal(speechCalls.length, 2);
});
