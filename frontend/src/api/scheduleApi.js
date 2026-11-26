export class ScheduleApiError extends Error {
  constructor(message, status, packet = null) { super(message); this.status = status; this.packet = packet; }
}

export function createScheduleApi({ getAccessToken, refreshAccessToken, onUnauthorized }) {
  async function request(path, { method = "GET", body } = {}) {
    const token = await getAccessToken();
    if (!token) throw new ScheduleApiError("로그인이 필요합니다.", 401);
    async function send(accessToken) {
      try {
        return await fetch(`/api${path}`, { method, cache: "no-store",
          headers: { "Content-Type": "application/json", Authorization: `Bearer ${accessToken}` },
          ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
        });
      } catch { throw new ScheduleApiError("서버에 연결하지 못했습니다. 연결을 확인해주세요.", 0); }
    }
    let response = await send(token);
    if (response.status === 401) {
      const refreshed = await refreshAccessToken();
      if (refreshed) response = await send(refreshed);
    }
    if (response.status === 401) {
      onUnauthorized?.();
      throw new ScheduleApiError("로그인이 만료되었습니다. 다시 로그인해주세요.", 401);
    }
    let packet;
    try { packet = await response.json(); }
    catch { throw new ScheduleApiError("서비스 응답을 확인하지 못했습니다. 다시 시도해주세요.", response.status); }
    if (!response.ok) throw new ScheduleApiError(typeof packet.detail === "string" ? packet.detail : "요청을 처리하지 못했습니다.", response.status, packet);
    return packet;
  }
  return {
    getMe: () => request("/me"), getCatalog: () => request("/catalog"),
    createSession: () => request("/sessions", { method: "POST" }),
    getSession: (id) => request(`/sessions/${encodeURIComponent(id)}`),
    sendMessage: (id, message) => request(`/sessions/${encodeURIComponent(id)}/messages`, { method: "POST", body: { message } }),
    decide: (id, body) => request(`/sessions/${encodeURIComponent(id)}/decision`, { method: "POST", body }),
    listEvents: () => request("/events"),
  };
}
