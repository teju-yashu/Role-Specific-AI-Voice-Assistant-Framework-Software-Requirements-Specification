const form = document.querySelector("#chat-form");
const input = document.querySelector("#message-input");
const roleSelect = document.querySelector("#selected-role");
const sendButton = document.querySelector("#send-button");
const micButton = document.querySelector("#mic-button");
const speechStatus = document.querySelector("#speech-status");
const conversation = document.querySelector("#conversation");
const ttsStatus = document.querySelector("#tts-status");
let welcomeNote = document.querySelector(".welcome-note");
const logoutForm = document.querySelector("#logout-form");
const historyToggle = document.querySelector("#history-toggle");
const historyPanel = document.querySelector("#conversation-history");
const historyList = document.querySelector("#history-list");
const historyStatus = document.querySelector("#history-status");
const historyRefresh = document.querySelector("#history-refresh");
const newConversationButton = document.querySelector("#new-conversation-button");
const conversationStatus = document.querySelector("#conversation-status");
const aiModeStatus = document.querySelector("#ai-mode-status");
const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content;
let recognition = null;
let recognitionState = "idle";
let recognitionHadResult = false;
let recognitionErrorMessage = "";
let recognitionDiscardResults = false;
let requestInProgress = false;
let conversationId = null;
let activeSpeech = null;
const preferredSpeechLanguage = "en-US";
const speechSynthesisAvailable =
  "speechSynthesis" in window && "SpeechSynthesisUtterance" in window;

if (!speechSynthesisAvailable) {
  setTtsStatus("Speech playback is not supported in this browser.", true);
}

function scrollToLatestMessage() {
  conversation.scrollTop = conversation.scrollHeight;
}

function addMessage(role, text, status = null) {
  welcomeNote?.remove();

  const message = document.createElement("article");
  message.className = `message ${role}`;
  if (status) {
    message.dataset.status = status;
  }

  const author = document.createElement("span");
  author.className = "message-author";
  author.textContent = role === "user" ? "You" : role === "agent" ? "Human agent" : "Assistant";

  const bubble = document.createElement("div");
  bubble.className = "message-bubble";
  bubble.textContent = text;

  message.append(author, bubble);
  if (role === "assistant") {
    message.append(createSpeechControl(bubble));
  }
  conversation.append(message);
  scrollToLatestMessage();
}

function setTtsStatus(message, isError = false) {
  ttsStatus.textContent = message;
  ttsStatus.classList.toggle("is-error", isError);
}

function updateSpeechButton(button, isSpeaking) {
  button.classList.toggle("is-speaking", isSpeaking);
  button.setAttribute("aria-pressed", String(isSpeaking));
  button.setAttribute("aria-label", isSpeaking ? "Stop speaking this assistant message" : "Read this assistant message aloud");
  button.title = isSpeaking ? "Stop speaking" : "Read aloud";
  button.querySelector(".speak-label").textContent = isSpeaking ? "Stop" : "Listen";
}

function selectEnglishVoice(language = preferredSpeechLanguage) {
  const voices = window.speechSynthesis.getVoices();
  const exactLanguage = voices.filter((voice) => voice.lang.toLowerCase() === language.toLowerCase());
  return exactLanguage.find((voice) => voice.default) || exactLanguage[0] ||
    voices.find((voice) => /^en(-|$)/i.test(voice.lang) && voice.default) ||
    voices.find((voice) => /^en(-|$)/i.test(voice.lang)) ||
    null;
}

function stopSpeech(announce = true) {
  if (!activeSpeech) {
    return true;
  }

  const previousSpeech = activeSpeech;
  activeSpeech = null;
  updateSpeechButton(previousSpeech.button, false);

  try {
    window.speechSynthesis.cancel();
    if (announce) {
      setTtsStatus("Speech stopped.");
    }
    return true;
  } catch (error) {
    setTtsStatus("Unable to stop speech playback.", true);
    console.error("Could not stop speech playback:", error);
    return false;
  }
}

function createSpeechControl(bubble) {
  const actions = document.createElement("div");
  actions.className = "message-actions";

  const button = document.createElement("button");
  button.className = "speak-button";
  button.type = "button";
  button.setAttribute("aria-pressed", "false");
  button.disabled = !speechSynthesisAvailable;
  button.setAttribute(
    "aria-label",
    speechSynthesisAvailable
      ? "Read this assistant message aloud"
      : "Speech playback is not supported in this browser",
  );
  button.title = speechSynthesisAvailable ? "Read aloud" : "Speech playback unavailable";

  const icon = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  icon.setAttribute("viewBox", "0 0 24 24");
  icon.setAttribute("fill", "none");
  icon.setAttribute("aria-hidden", "true");
  const speaker = document.createElementNS("http://www.w3.org/2000/svg", "path");
  speaker.setAttribute("d", "M4 10v4h4l5 4V6l-5 4H4Zm12.5-2a6 6 0 0 1 0 8m2.5-10a9 9 0 0 1 0 12");
  speaker.setAttribute("stroke", "currentColor");
  speaker.setAttribute("stroke-width", "1.8");
  speaker.setAttribute("stroke-linecap", "round");
  speaker.setAttribute("stroke-linejoin", "round");
  icon.append(speaker);

  const label = document.createElement("span");
  label.className = "speak-label";
  label.textContent = "Listen";
  button.append(icon, label);
  button.addEventListener("click", () => {
    if (!speechSynthesisAvailable) {
      setTtsStatus("Speech playback is not supported in this browser.", true);
      return;
    }

    if (activeSpeech?.button === button) {
      stopSpeech();
      return;
    }

    if (activeSpeech && !stopSpeech(false)) {
      return;
    }

    const text = bubble.textContent.trim();
    if (!text) {
      setTtsStatus("There is no text in this assistant message to read aloud.", true);
      return;
    }

    let utterance;
    try {
      utterance = new SpeechSynthesisUtterance(text);
      utterance.lang = preferredSpeechLanguage;
      const voice = selectEnglishVoice();
      if (voice) {
        utterance.voice = voice;
      }
    } catch (error) {
      setTtsStatus("Speech playback could not be prepared. Try again.", true);
      console.error("Could not prepare speech playback:", error);
      return;
    }

    const playback = { utterance, button };
    activeSpeech = playback;
    updateSpeechButton(button, true);
    setTtsStatus("Starting speech playback...");

    utterance.onstart = () => {
      if (activeSpeech === playback) {
        setTtsStatus("Speaking assistant message.");
      }
    };

    utterance.onend = () => {
      if (activeSpeech === playback) {
        activeSpeech = null;
        updateSpeechButton(button, false);
        setTtsStatus("Finished reading assistant message.");
      }
    };

    utterance.onerror = (event) => {
      if (activeSpeech === playback) {
        activeSpeech = null;
        updateSpeechButton(button, false);
        setTtsStatus("Speech playback failed. Try again or check your browser's speech settings.", true);
        console.error("Speech playback failed:", event.error);
      }
    };

    try {
      window.speechSynthesis.speak(utterance);
    } catch (error) {
      if (activeSpeech === playback) {
        activeSpeech = null;
        updateSpeechButton(button, false);
      }
      setTtsStatus("Speech playback could not be started. Try again.", true);
      console.error("Could not start speech playback:", error);
    }
  });

  actions.append(button);
  return actions;
}

async function submitMessage(selectedRole, query) {
  let response;
  try {
    const requestBody = { selected_role: selectedRole, query };
    if (conversationId) {
      requestBody.conversation_id = conversationId;
    }
    response = await fetch(form.action, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        ...(csrfToken ? { "X-CSRF-Token": csrfToken } : {}),
      },
      body: JSON.stringify(requestBody),
    });
  } catch {
    throw new Error("Unable to reach the conversation service. Check your connection and try again.");
  }

  const data = await readResponseJson(response);

  if (!response.ok) {
    const message =
      data &&
      typeof data === "object" &&
      !Array.isArray(data) &&
      typeof data.error === "string"
        ? data.error
        : `The conversation service returned an error (HTTP ${response.status}).`;
    throw new Error(message);
  }

  if (!data || typeof data !== "object" || Array.isArray(data)) {
    throw new Error("The conversation service returned an invalid response. Please try again.");
  }

  if (typeof data.response !== "string" || !data.response.trim()) {
    throw new Error("The conversation service returned an invalid response. Please try again.");
  }

  let text = data.response;
  if (data.status === "clarification_required") {
    text = data.response || data.clarification_question;
  } else if (data.status === "unknown_intent") {
    text = data.response || data.message;
  } else if (data.status === "escalation_required") {
    text = data.response || "This request needs human review.";
  }
  return {
    text,
    status: data.status,
    conversationId: data.conversation_id,
    escalationStatus: data.escalation_status,
    llmMode: data.llm_mode,
  };
}

async function readResponseJson(response) {
  try {
    const data = await response.json();
    return data && typeof data === "object" && !Array.isArray(data) ? data : null;
  } catch {
    return null;
  }
}

function setConversationStatus(message, isError = false) {
  if (!conversationStatus) {
    return;
  }
  conversationStatus.textContent = message;
  conversationStatus.classList.toggle("is-error", isError);
}

function setLlmMode(mode) {
  if (!aiModeStatus) {
    return;
  }
  aiModeStatus.textContent =
    mode === "openai"
      ? "AI mode: OpenAI connected."
      : "AI mode: Rule-based assistant (fallback).";
}

function showProcessingIndicator() {
  const indicator = document.createElement("div");
  indicator.className = "message assistant";
  indicator.setAttribute("role", "status");

  const label = document.createElement("span");
  label.className = "sr-only";
  label.textContent = "Assistant is processing your message";

  const dots = document.createElement("div");
  dots.className = "processing";
  dots.setAttribute("aria-hidden", "true");
  for (let i = 0; i < 3; i += 1) {
    dots.append(document.createElement("span"));
  }

  indicator.append(label, dots);
  conversation.append(indicator);
  scrollToLatestMessage();
  return indicator;
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const originalText = input.value;
  const text = originalText.trim();
  if (!text || requestInProgress || sendButton.disabled) {
    return;
  }

  requestInProgress = true;
  if (recognition) {
    stopRecognition(true);
  }

  const selectedRole = roleSelect.value;
  addMessage("user", text);
  input.value = "";
  input.style.height = "";
  sendButton.disabled = true;
  input.disabled = true;
  roleSelect.disabled = true;
  micButton.disabled = true;
  if (newConversationButton) newConversationButton.disabled = true;
  if (historyToggle) historyToggle.disabled = true;
  const indicator = showProcessingIndicator();

  try {
    const result = await submitMessage(selectedRole, text);
    indicator.remove();
    if (typeof result.conversationId === "string") {
      conversationId = result.conversationId;
    }
    if (typeof result.llmMode === "string") {
      setLlmMode(result.llmMode);
    }
    addMessage("assistant", result.text, result.status);
    if (result.escalationStatus === "pending") {
      setConversationStatus("A human agent review is pending. You can check its status in conversation history.");
    } else if (result.status === "clarification_required") {
      setConversationStatus("Conversation context saved. Reply here to continue.");
    } else {
      setConversationStatus("");
    }
  } catch (error) {
    indicator.remove();
    setConversationStatus(
      error instanceof Error ? error.message : "The request could not be completed.",
      true,
    );
    if (input.value === "") {
      input.value = originalText;
      input.dispatchEvent(new Event("input", { bubbles: true }));
    }
    addMessage(
      "assistant",
      error instanceof Error
        ? error.message
        : "The request could not be completed. Please try again.",
      "error",
    );
    console.error("Conversation request failed:", error);
  } finally {
    sendButton.disabled = false;
    input.disabled = false;
    roleSelect.disabled = false;
    requestInProgress = false;
    micButton.disabled =
      recognition !== null && recognitionState === "stopping";
    if (newConversationButton) newConversationButton.disabled = false;
    if (historyToggle) historyToggle.disabled = false;
    input.focus();
  }
});

logoutForm?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = logoutForm.querySelector('button[type="submit"]');
  button.disabled = true;
  try {
    const response = await fetch(logoutForm.action, {
      method: "POST",
      headers: {
        Accept: "application/json",
        ...(csrfToken ? { "X-CSRF-Token": csrfToken } : {}),
      },
    });
    const data = await response.json();
    if (!response.ok || typeof data.redirect_url !== "string") {
      throw new Error("Sign out could not be completed.");
    }
    window.location.assign(data.redirect_url);
  } catch (error) {
    setSpeechStatus(
      error instanceof Error ? error.message : "Sign out could not be completed.",
      true,
    );
    button.disabled = false;
  }
});

function renderWelcomeNote() {
  const note = document.createElement("p");
  note.className = "welcome-note";
  note.textContent = "Send a message to start a conversation.";
  conversation.append(note);
  welcomeNote = note;
}

function clearConversationView() {
  conversation.replaceChildren();
  welcomeNote = null;
}

async function loadConversationHistory() {
  if (!historyList || !historyStatus) {
    return;
  }
  historyStatus.textContent = "Loading conversation history...";
  historyStatus.classList.remove("is-error");
  try {
    const response = await fetch("/api/conversations", {
      headers: { Accept: "application/json" },
    });
    const data = await readResponseJson(response);
    if (!response.ok || !data || !Array.isArray(data.conversations)) {
      throw new Error(
        data && typeof data.error === "string"
          ? data.error
          : `Conversation history could not be loaded (HTTP ${response.status}).`,
      );
    }

    historyList.replaceChildren();
    for (const item of data.conversations) {
      if (!item || typeof item.id !== "string") {
        continue;
      }
      const listItem = document.createElement("li");
      const button = document.createElement("button");
      button.className = "history-item";
      button.type = "button";
      const title = document.createElement("span");
      title.textContent = item.title || item.last_message || "Conversation";
      const status = document.createElement("span");
      status.className = "history-item-status";
      status.textContent = item.escalation_status
        ? `Escalation ${item.escalation_status}`
        : item.status || "";
      button.append(title, status);
      button.addEventListener("click", () => loadConversation(item.id));
      listItem.append(button);
      historyList.append(listItem);
    }
    historyStatus.textContent = data.conversations.length
      ? ""
      : "No previous conversations.";
  } catch (error) {
    historyStatus.textContent =
      error instanceof Error ? error.message : "Conversation history could not be loaded.";
    historyStatus.classList.add("is-error");
  }
}

async function loadConversation(id) {
  if (requestInProgress) {
    return;
  }
  historyStatus.textContent = "Loading conversation...";
  historyStatus.classList.remove("is-error");
  try {
    const response = await fetch(`/api/conversations/${encodeURIComponent(id)}`, {
      headers: { Accept: "application/json" },
    });
    const data = await readResponseJson(response);
    if (
      !response.ok ||
      !data ||
      !data.conversation ||
      !Array.isArray(data.messages)
    ) {
      throw new Error(
        data && typeof data.error === "string"
          ? data.error
          : `Conversation could not be loaded (HTTP ${response.status}).`,
      );
    }

    clearConversationView();
    conversationId = data.conversation.id;
    roleSelect.value = data.conversation.selected_role;
    for (const message of data.messages) {
      if (message && ["user", "assistant", "agent"].includes(message.sender)) {
        addMessage(message.sender, String(message.body || ""), message.status);
      }
    }
    if (data.escalation) {
      setConversationStatus(`Escalation status: ${data.escalation.status}.`);
    } else {
      setConversationStatus("Conversation loaded. Continue by sending a message.");
    }
    historyStatus.textContent = "";
    const roleIsAvailable = Array.from(roleSelect.options || []).some(
      (option) => option.value === data.conversation.selected_role,
    );
    roleSelect.disabled = !roleIsAvailable;
    input.disabled = !roleIsAvailable;
    sendButton.disabled = !roleIsAvailable;
    micButton.disabled = !roleIsAvailable;
    if (!roleIsAvailable) {
      setConversationStatus(
        "This assistant role is inactive. You can view the conversation but cannot continue it.",
        true,
      );
    }
  } catch (error) {
    historyStatus.textContent =
      error instanceof Error ? error.message : "Conversation could not be loaded.";
    historyStatus.classList.add("is-error");
  }
}

historyToggle?.addEventListener("click", async () => {
  const isExpanded = historyToggle.getAttribute("aria-expanded") === "true";
  historyToggle.setAttribute("aria-expanded", String(!isExpanded));
  if (historyPanel) {
    historyPanel.hidden = isExpanded;
  }
  if (!isExpanded) {
    await loadConversationHistory();
  }
});

historyRefresh?.addEventListener("click", loadConversationHistory);

newConversationButton?.addEventListener("click", () => {
  if (requestInProgress) {
    return;
  }
  conversationId = null;
  roleSelect.disabled = false;
  input.disabled = false;
  sendButton.disabled = false;
  micButton.disabled = false;
  clearConversationView();
  renderWelcomeNote();
  setConversationStatus("Started a new conversation.");
  input.focus();
});

roleSelect?.addEventListener("change", () => {
  if (!conversationId || requestInProgress) {
    return;
  }
  conversationId = null;
  clearConversationView();
  renderWelcomeNote();
  setConversationStatus("Assistant role changed. A new conversation will be started.");
});

input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    form.requestSubmit();
  }
});

input.addEventListener("input", () => {
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 140)}px`;
});

function setSpeechStatus(message, isError = false) {
  speechStatus.textContent = message;
  speechStatus.classList.toggle("is-error", isError);
}

function setRecognitionState(state) {
  recognitionState = state;
  const isActive = state === "starting" || state === "listening" || state === "stopping";
  micButton.classList.toggle("is-listening", state === "listening");
  micButton.setAttribute("aria-pressed", String(isActive));

  const label = isActive ? "Stop speech recognition" : "Start speech recognition";
  micButton.setAttribute("aria-label", label);
  micButton.title = label;
}

function getRecognitionErrorMessage(error) {
  switch (error) {
    case "not-allowed":
      return "Microphone permission was denied. Allow microphone access in your browser settings and try again.";
    case "service-not-allowed":
      return "The browser blocked access to microphone or speech recognition. Check browser permissions and try again.";
    case "no-speech":
      return "No speech was detected. Try again and speak after the listening indicator appears.";
    case "audio-capture":
      return "No microphone is available. Connect or enable a microphone, then try again.";
    case "network":
      return "Speech recognition needs a network connection. Check your connection and try again.";
    case "aborted":
      return "Speech recognition was stopped.";
    default:
      return "Speech recognition could not start. Check your microphone and try again.";
  }
}

function getStartupErrorMessage(error) {
  if (error?.name === "NotAllowedError" || error?.name === "SecurityError") {
    return getRecognitionErrorMessage("not-allowed");
  }
  if (
    error?.name === "NotFoundError" ||
    error?.name === "DevicesNotFoundError" ||
    error?.name === "NotReadableError"
  ) {
    return getRecognitionErrorMessage("audio-capture");
  }
  return getRecognitionErrorMessage("unknown");
}

function clearRecognitionHandlers(activeRecognition) {
  activeRecognition.onstart = null;
  activeRecognition.onresult = null;
  activeRecognition.onerror = null;
  activeRecognition.onend = null;
}

function stopRecognition(discardResults = false) {
  if (discardResults) {
    recognitionDiscardResults = true;
  }

  if (!recognition || recognitionState === "idle" || recognitionState === "stopping") {
    return;
  }

  const previousState = recognitionState;
  setRecognitionState("stopping");
  setSpeechStatus("Stopping speech recognition...");
  try {
    recognition.stop();
  } catch (error) {
    setRecognitionState(previousState);
    setSpeechStatus("Unable to stop speech recognition. It may still be listening; try stopping again.", true);
    console.error("Could not stop speech recognition:", error);
  }
}

function startRecognition() {
  if (input.disabled || requestInProgress) {
    setSpeechStatus("Wait for the current response to finish before using the microphone.");
    return;
  }

  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    setSpeechStatus("Speech recognition is unavailable in this browser. You can continue by typing.", true);
    return;
  }

  if (recognitionState !== "idle") {
    return;
  }

  recognitionDiscardResults = false;
  recognitionHadResult = false;
  recognitionErrorMessage = "";
  let activeRecognition;
  try {
    activeRecognition = new SpeechRecognition();
    activeRecognition.continuous = false;
    activeRecognition.interimResults = false;
    activeRecognition.lang = navigator.language || "en-US";
    recognition = activeRecognition;
  } catch (error) {
    recognitionErrorMessage = getStartupErrorMessage(error);
    setSpeechStatus(recognitionErrorMessage, true);
    console.error("Could not initialize speech recognition:", error);
    return;
  }

  activeRecognition.onstart = () => {
    if (
      recognition !== activeRecognition ||
      recognitionDiscardResults ||
      requestInProgress
    ) {
      return;
    }
    setRecognitionState("listening");
    setSpeechStatus("Listening... Speak now, then click the microphone to stop.");
  };

  activeRecognition.onresult = (event) => {
    if (
      recognition !== activeRecognition ||
      recognitionDiscardResults ||
      requestInProgress
    ) {
      return;
    }

    const transcript = Array.from(event.results)
      .slice(event.resultIndex)
      .filter((result) => result.isFinal)
      .map((result) => result[0].transcript)
      .join("")
      .trim();

    if (!transcript) {
      return;
    }

    recognitionHadResult = true;
    input.value = transcript;
    input.dispatchEvent(new Event("input", { bubbles: true }));
    setSpeechStatus("Speech recognized. Review or edit the message before sending.");
  };

  activeRecognition.onerror = (event) => {
    if (
      recognition !== activeRecognition ||
      recognitionDiscardResults ||
      requestInProgress
    ) {
      return;
    }

    recognitionErrorMessage = getRecognitionErrorMessage(event.error);
    setSpeechStatus(recognitionErrorMessage, true);
  };

  activeRecognition.onend = () => {
    if (recognition !== activeRecognition) {
      clearRecognitionHandlers(activeRecognition);
      return;
    }

    if (recognitionDiscardResults || requestInProgress) {
      if (recognitionState === "stopping") {
        setSpeechStatus("Speech recognition stopped.");
      }
    } else if (!recognitionErrorMessage) {
      if (recognitionHadResult) {
        setSpeechStatus("Speech recognized. Review or edit the message before sending.");
      } else if (recognitionState === "stopping") {
        setSpeechStatus("Speech recognition stopped.");
      } else {
        recognitionErrorMessage = getRecognitionErrorMessage("no-speech");
        setSpeechStatus(recognitionErrorMessage, true);
      }
    }

    clearRecognitionHandlers(activeRecognition);
    recognition = null;
    recognitionDiscardResults = false;
    setRecognitionState("idle");
    micButton.disabled = requestInProgress;
  };

  setRecognitionState("starting");
  setSpeechStatus("Requesting microphone permission...");
  try {
    activeRecognition.start();
  } catch (error) {
    clearRecognitionHandlers(activeRecognition);
    recognition = null;
    setRecognitionState("idle");
    recognitionErrorMessage = getStartupErrorMessage(error);
    setSpeechStatus(recognitionErrorMessage, true);
    console.error("Could not start speech recognition:", error);
  }
}

micButton.addEventListener("click", () => {
  if (recognitionState === "idle") {
    startRecognition();
  } else {
    stopRecognition();
  }
});
