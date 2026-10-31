const CHAT_ENDPOINT = "/api/chat";

const form = document.querySelector("#chat-form");
const input = document.querySelector("#message-input");
const sendButton = document.querySelector("#send-button");
const micButton = document.querySelector("#mic-button");
const speechStatus = document.querySelector("#speech-status");
const conversation = document.querySelector("#conversation");
const ttsStatus = document.querySelector("#tts-status");
const welcomeNote = document.querySelector(".welcome-note");
let serviceNotice = null;
let recognition = null;
let recognitionState = "idle";
let recognitionHadResult = false;
let recognitionErrorMessage = "";
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

function addMessage(role, text) {
  welcomeNote?.remove();
  serviceNotice?.remove();
  serviceNotice = null;

  const message = document.createElement("article");
  message.className = `message ${role}`;

  const author = document.createElement("span");
  author.className = "message-author";
  author.textContent = role === "user" ? "You" : "Assistant";

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

async function submitMessage(text) {
  const response = await fetch(CHAT_ENDPOINT, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
    },
    body: JSON.stringify({ message: text }),
  });

  if (!response.ok) {
    throw new Error("The conversation service returned an error.");
  }

  const data = await response.json();
  if (typeof data.response !== "string" || !data.response.trim()) {
    throw new Error("The conversation service returned an invalid response.");
  }

  return data.response;
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
  const text = input.value.trim();
  if (!text || sendButton.disabled) {
    return;
  }

  addMessage("user", text);
  input.value = "";
  input.style.height = "";
  sendButton.disabled = true;
  input.disabled = true;
  const indicator = showProcessingIndicator();

  try {
    const assistantText = await submitMessage(text);
    indicator.remove();
    addMessage("assistant", assistantText);
  } catch (error) {
    indicator.remove();
    serviceNotice = document.createElement("p");
    serviceNotice.className = "welcome-note";
    serviceNotice.setAttribute("role", "alert");
    serviceNotice.textContent = "Unable to get a response from the conversation service. Please try again later.";
    conversation.append(serviceNotice);
    scrollToLatestMessage();
    console.error("Conversation request failed:", error);
  } finally {
    sendButton.disabled = false;
    input.disabled = false;
    input.focus();
  }
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

function stopRecognition() {
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
  if (input.disabled) {
    setSpeechStatus("Wait for the current response to finish before using the microphone.");
    return;
  }

  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    setSpeechStatus("Speech recognition is not supported in this browser. Try a supported browser such as Chrome or Edge.", true);
    return;
  }

  if (recognitionState !== "idle") {
    return;
  }

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
    setRecognitionState("listening");
    setSpeechStatus("Listening... Speak now, then click the microphone to stop.");
  };

  activeRecognition.onresult = (event) => {
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
    recognitionErrorMessage = getRecognitionErrorMessage(event.error);
    setSpeechStatus(recognitionErrorMessage, true);
  };

  activeRecognition.onend = () => {
    if (!recognitionErrorMessage) {
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
    if (recognition === activeRecognition) {
      recognition = null;
      setRecognitionState("idle");
    }
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
