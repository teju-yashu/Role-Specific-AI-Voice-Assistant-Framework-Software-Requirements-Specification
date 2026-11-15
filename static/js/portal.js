const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content;
const adminDashboard = document.querySelector("#admin-dashboard");
const escalationList = document.querySelector("#escalation-list");
const portalStatus = document.querySelector("#portal-status");

async function apiRequest(url, options = {}) {
  const headers = {
    Accept: "application/json",
    ...(options.body ? { "Content-Type": "application/json" } : {}),
    ...(csrfToken ? { "X-CSRF-Token": csrfToken } : {}),
    ...(options.headers || {}),
  };
  let response;
  try {
    response = await fetch(url, { ...options, headers });
  } catch {
    throw new Error("The service could not be reached. Check the connection and try again.");
  }

  let data = null;
  try {
    const parsed = await response.json();
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      data = parsed;
    }
  } catch {
    data = null;
  }
  if (!response.ok) {
    throw new Error(
      data && typeof data.error === "string"
        ? data.error
        : `The request failed (HTTP ${response.status}).`,
    );
  }
  if (!data) {
    throw new Error("The service returned an invalid response.");
  }
  return data;
}

function setPortalStatus(message, isError = false) {
  if (!portalStatus) {
    return;
  }
  portalStatus.textContent = message;
  portalStatus.classList.toggle("is-error", isError);
}

function createTable(headers, rows) {
  const table = document.createElement("table");
  table.className = "portal-table";
  const head = document.createElement("thead");
  const headerRow = document.createElement("tr");
  for (const header of headers) {
    const cell = document.createElement("th");
    cell.scope = "col";
    cell.textContent = header;
    headerRow.append(cell);
  }
  head.append(headerRow);
  const body = document.createElement("tbody");
  for (const values of rows) {
    const row = document.createElement("tr");
    for (const value of values) {
      const cell = document.createElement("td");
      if (value instanceof Node) {
        cell.append(value);
      } else {
        cell.textContent = String(value ?? "");
      }
      row.append(cell);
    }
    body.append(row);
  }
  table.append(head, body);
  return table;
}

function renderMetricCards(metrics) {
  const container = document.querySelector("#metric-cards");
  if (!container) {
    return;
  }
  const cards = [
    ["Conversations", metrics.conversations.total],
    ["Active conversations", metrics.conversations.active],
    ["Workflow requests", metrics.workflow_requests],
    ["Workflow executions", metrics.workflow_executions],
    ["Successful workflow requests", metrics.successful_workflow_requests],
    ["Escalations", Object.values(metrics.escalations).reduce((sum, count) => sum + count, 0)],
  ];
  container.replaceChildren();
  for (const [label, value] of cards) {
    const card = document.createElement("div");
    card.className = "metric-card";
    const caption = document.createElement("span");
    caption.textContent = label;
    const count = document.createElement("strong");
    count.textContent = String(value ?? 0);
    card.append(caption, count);
    container.append(card);
  }
}

function renderAdminDashboard(metrics) {
  renderMetricCards(metrics);
  const rolesContainer = document.querySelector("#role-table");
  const roleRows = (metrics.roles || []).map((role) => {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = role.is_active ? "Deactivate" : "Activate";
    button.setAttribute(
      "aria-label",
      `${button.textContent} ${role.display_name}`,
    );
    button.disabled = role.workflow_status !== "configured" && !role.is_active;
    button.addEventListener("click", async () => {
      button.disabled = true;
      try {
        await apiRequest(
          `/api/admin/roles/${encodeURIComponent(role.role_key)}/active`,
          {
            method: "POST",
            body: JSON.stringify({ active: !role.is_active }),
          },
        );
        await loadAdminDashboard();
        setPortalStatus(`${role.display_name} configuration updated.`);
      } catch (error) {
        button.disabled = false;
        setPortalStatus(
          error instanceof Error ? error.message : "Role configuration failed.",
          true,
        );
      }
    });
    return [
      role.display_name,
      role.workflow_intent || "Unavailable",
      role.workflow_status,
      role.is_active ? "Active" : "Inactive",
      button,
    ];
  });
  if (rolesContainer) {
    rolesContainer.replaceChildren(
      createTable(
        ["Assistant", "Registered workflow", "Workflow status", "Availability", "Action"],
        roleRows,
      ),
    );
  }

  const workflowContainer = document.querySelector("#workflow-table");
  if (workflowContainer) {
    const rows = (metrics.workflow_outcomes || []).map((item) => [
      item.selected_role,
      item.intent,
      item.outcome,
      item.count,
    ]);
    workflowContainer.replaceChildren(
      rows.length
        ? createTable(["Assistant", "Intent", "Outcome", "Count"], rows)
        : document.createTextNode("No workflow requests recorded yet."),
    );
  }

  const activityContainer = document.querySelector("#activity-table");
  if (activityContainer) {
    const rows = (metrics.recent_activity || []).map((item) => [
      item.created_at,
      item.actor_role || "system",
      item.action,
      `${item.entity_type}${item.entity_id ? ` · ${item.entity_id}` : ""}`,
    ]);
    activityContainer.replaceChildren(
      rows.length
        ? createTable(["Time", "Actor role", "Activity", "Record"], rows)
        : document.createTextNode("No recent activity."),
    );
  }
}

async function loadAdminDashboard() {
  setPortalStatus("Loading prototype metrics...");
  try {
    const metrics = await apiRequest("/api/admin/dashboard");
    renderAdminDashboard(metrics);
    setPortalStatus("Prototype metrics loaded.");
  } catch (error) {
    setPortalStatus(
      error instanceof Error ? error.message : "Dashboard could not be loaded.",
      true,
    );
  }
}

function renderEscalation(item) {
  const card = document.createElement("article");
  card.className = "escalation-card";
  const heading = document.createElement("h2");
  heading.textContent = `${item.selected_role} · ${item.title || "Conversation"}`;
  const summary = document.createElement("p");
  summary.textContent = `Status: ${item.status} · Created: ${item.created_at}`;
  const reason = document.createElement("p");
  reason.textContent = `Reason: ${item.reason}`;
  card.append(heading, summary, reason);

  const messages = document.createElement("div");
  messages.className = "escalation-messages";
  messages.setAttribute("aria-label", "Conversation messages");
  for (const message of item.messages || []) {
    const line = document.createElement("p");
    const sender =
      message.sender === "agent"
        ? "Human agent"
        : message.sender === "user"
          ? "User"
          : "Assistant";
    line.textContent = `${sender}: ${message.body}`;
    messages.append(line);
  }
  card.append(messages);

  if (item.status === "pending") {
    const accept = document.createElement("button");
    accept.type = "button";
    accept.textContent = "Accept escalation";
    accept.addEventListener("click", async () => {
      accept.disabled = true;
      try {
        await apiRequest(`/api/agent/escalations/${encodeURIComponent(item.id)}/accept`, {
          method: "POST",
        });
        await loadEscalations();
      } catch (error) {
        accept.disabled = false;
        setPortalStatus(
          error instanceof Error ? error.message : "Escalation could not be accepted.",
          true,
        );
      }
    });
    card.append(accept);
  } else if (item.can_resolve) {
    const responseLabel = document.createElement("label");
    responseLabel.textContent = "Response to the user";
    const responseInput = document.createElement("textarea");
    responseInput.maxLength = 5000;
    responseInput.required = true;
    responseLabel.append(responseInput);
    const resolve = document.createElement("button");
    resolve.type = "button";
    resolve.textContent = "Resolve and send response";
    resolve.addEventListener("click", async () => {
      if (!responseInput.value.trim()) {
        responseInput.focus();
        setPortalStatus("Enter a response before resolving the escalation.", true);
        return;
      }
      resolve.disabled = true;
      try {
        await apiRequest(`/api/agent/escalations/${encodeURIComponent(item.id)}/resolve`, {
          method: "POST",
          body: JSON.stringify({ response: responseInput.value }),
        });
        await loadEscalations();
      } catch (error) {
        resolve.disabled = false;
        setPortalStatus(
          error instanceof Error ? error.message : "Escalation could not be resolved.",
          true,
        );
      }
    });
    card.append(responseLabel, resolve);
  }
  return card;
}

async function loadEscalations() {
  if (!escalationList) {
    return;
  }
  setPortalStatus("Loading escalation queue...");
  try {
    const data = await apiRequest("/api/agent/escalations");
    escalationList.replaceChildren();
    for (const item of data.escalations || []) {
      escalationList.append(renderEscalation(item));
    }
    setPortalStatus(
      data.escalations?.length
        ? `${data.escalations.length} escalation(s) in this queue.`
        : "No escalations are currently assigned or waiting.",
    );
  } catch (error) {
    setPortalStatus(
      error instanceof Error ? error.message : "Escalation queue could not be loaded.",
      true,
    );
  }
}

const logoutForm = document.querySelector("#logout-form");
logoutForm?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = logoutForm.querySelector('button[type="submit"]');
  button.disabled = true;
  try {
    const data = await apiRequest(logoutForm.action, { method: "POST" });
    if (typeof data.redirect_url !== "string") {
      throw new Error("Sign out could not be completed.");
    }
    window.location.assign(data.redirect_url);
  } catch (error) {
    button.disabled = false;
    setPortalStatus(
      error instanceof Error ? error.message : "Sign out could not be completed.",
      true,
    );
  }
});

document.querySelector("#refresh-escalations")?.addEventListener("click", loadEscalations);
if (adminDashboard) {
  loadAdminDashboard();
}
if (escalationList) {
  loadEscalations();
}
