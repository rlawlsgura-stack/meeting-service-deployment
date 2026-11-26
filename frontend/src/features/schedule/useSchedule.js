import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useAuth } from "../../auth/AuthProvider.jsx";
import { createScheduleApi } from "../../api/scheduleApi.js";

const storageKey = (user, workspace) => `moim.workspace.${user}.${workspace}.inquiry`;
function stored(key) { try { return sessionStorage.getItem(key); } catch { return null; } }
function forget(key) { try { sessionStorage.removeItem(key); } catch { /* Persistence is optional. */ } }

export function comparisonFor(before, packet, existing) {
  if (!before || before.id !== packet.id || !packet.request) return null;
  const requestChanged = before.request && before.request.request_id === packet.request.request_id && before.request.revision !== packet.request.revision;
  const proposalChanged = before.pending && packet.pending && before.pending.proposal_id !== packet.pending.proposal_id;
  return requestChanged || proposalChanged ? {
    before: { request: before.request, content: before.pending?.content || before.event?.content || null },
    after: { request: packet.request, content: packet.pending?.content || packet.event?.content || null },
  } : existing;
}

export default function useSchedule() {
  const auth = useAuth();
  const userId = auth.user.id;
  const api = useMemo(() => createScheduleApi({ getAccessToken: () => auth.getAccessToken(userId),
    refreshAccessToken: () => auth.refreshAccessToken(userId), onUnauthorized: () => auth.invalidateSession(userId) }),
  [auth.getAccessToken, auth.refreshAccessToken, auth.invalidateSession, userId]);
  const [me, setMe] = useState(null);
  const [catalog, setCatalog] = useState(null);
  const [session, setSession] = useState(null);
  const [events, setEvents] = useState([]);
  const [history, setHistory] = useState([]);
  const [comparison, setComparison] = useState(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState(null);
  const [reload, setReload] = useState(0);
  const alive = useRef(true), running = useRef(false), workspace = useRef(null), previous = useRef(null);
  const capabilities = { time: true, rooms: false, parallel: false, collaboration: false, registration: false, feedback: false, ...catalog?.capabilities };
  const current = useCallback(() => alive.current && auth.isCurrentUser(userId), [auth.isCurrentUser, userId]);

  const apply = useCallback((packet) => {
    if (!current()) return;
    const before = previous.current;
    setComparison((existing) => comparisonFor(before, packet, existing));
    previous.current = packet;
    setSession(packet);
    if (workspace.current) try { sessionStorage.setItem(storageKey(userId, workspace.current), packet.id); } catch { /* Persistence is optional. */ }
  }, [current, userId]);

  useEffect(() => {
    alive.current = true;
    let active = true;
    setBusy(true); setError(null);
    async function initialize() {
      const identity = await api.getMe();
      if (!active || !current()) return;
      setMe(identity); workspace.current = identity.workspace.id;
      if (!identity.membership) return;
      const sourceCatalog = await api.getCatalog();
      if (!active || !current()) return;
      setCatalog(sourceCatalog);
      const key = storageKey(userId, identity.workspace.id), inquiryId = stored(key);
      if (inquiryId) {
        try { const packet = await api.getSession(inquiryId); if (active) apply(packet); }
        catch (failure) { if ([403, 404].includes(failure.status)) forget(key); else throw failure; }
      }
      if (sourceCatalog.capabilities?.registration) {
        const packet = await api.listEvents();
        if (active && current()) setEvents(packet.events || []);
      }
    }
    initialize().catch((failure) => active && current() && setError(failure)).finally(() => active && current() && setBusy(false));
    return () => { active = false; alive.current = false; };
  }, [api, apply, current, reload, userId]);

  async function run(operation) {
    if (running.current || !auth.isCurrentUser(userId) || !me?.membership) return;
    running.current = true; setBusy(true); setError(null);
    try { return await operation(); }
    catch (failure) { if (current()) setError(failure); }
    finally { running.current = false; if (current()) setBusy(false); }
  }

  const sendMessage = (text) => run(async () => {
    const inquiry = session || await api.createSession();
    const packet = await api.sendMessage(inquiry.id, text);
    apply(packet);
    if (current()) {
      setHistory((previous) => [...previous.slice(-7), { text, reply: packet.reply }]);
      return packet;
    }
  });

  const decide = (action, message = "") => run(async () => {
    if (!session?.pending) return;
    const pending = session.pending;
    const packet = await api.decide(session.id, { action, proposal_id: pending.proposal_id,
      revision: pending.revision, content: pending.content, ...(message ? { message } : {}) });
    apply(packet);
    if (packet.status === "saved" && capabilities.registration) {
      const saved = await api.listEvents();
      if (current()) setEvents(saved.events || []);
    }
  });

  return { me, catalog, capabilities, session, events, history, comparison, busy, error, sendMessage, decide,
    reloadWorkspace: () => setReload((value) => value + 1),
    clearError: () => setError(null),
    resetInquiry: () => {
      setSession(null); setHistory([]); setError(null); setComparison(null); previous.current = null;
      if (workspace.current) forget(storageKey(userId, workspace.current));
    },
    refreshEvents: () => run(async () => {
      if (!capabilities.registration) return;
      const packet = await api.listEvents(); if (current()) setEvents(packet.events || []);
    }),
  };
}
