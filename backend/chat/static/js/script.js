const $ = (id) => document.getElementById(id);
const configUrl = JSON.parse($("rtc-config").textContent).url;
let configRequest;
let socket, stream, peer, matchId, heartbeat, connectTimer, reconnectTimer;
let generation = 0,
  active = false,
  candidates = [],
  chain = Promise.resolve();
let reconnects = 0,
  lastPong = 0,
  nextAllowed = 0;
let nextTimer;
// The last partner stays reportable after they leave, until the next match or stop.
let lastMatch = null;
// While set, a dropped socket keeps the call and the next socket resumes it.
let resumeToken = null;
let initiator = false,
  matchedAt = 0,
  everConnected = false,
  sharedLabel = "";
// ICE restart: only the initiator offers (no glare); the other side asks for one.
let restarting = false,
  restartStarted = 0,
  restartAttempts = 0,
  restartTimer,
  disconnectTimer;

const PREFS_KEY = "videochat:preferences";
const interestLabel = (code) =>
  document.querySelector(`input[name="interests"][value="${code}"]`)
    ?.nextElementSibling.textContent || code;

function preferences() {
  return {
    lang: $("pref-lang").value,
    interests: [
      ...document.querySelectorAll('input[name="interests"]:checked'),
    ].map((input) => input.value),
  };
}
function restorePreferences() {
  try {
    const saved = JSON.parse(localStorage.getItem(PREFS_KEY) || "{}");
    if (saved.lang) $("pref-lang").value = saved.lang;
    for (const input of document.querySelectorAll('input[name="interests"]'))
      input.checked = (saved.interests || []).includes(input.value);
  } catch {}
}
function enableNext() {
  clearTimeout(nextTimer);
  const delay = Math.max(0, nextAllowed - Date.now());
  $("next").disabled = delay > 0;
  if (delay)
    nextTimer = setTimeout(() => {
      if (active && socket?.readyState === WebSocket.OPEN)
        $("next").disabled = false;
    }, delay);
}

function status(title, detail = "") {
  $("status").textContent = title;
  $("status-detail").textContent = detail;
  $("connection-badge").textContent = title;
}
function notice(message = "") {
  $("notice").textContent = message;
}
function send(data) {
  if (socket?.readyState !== WebSocket.OPEN) return false;
  socket.send(JSON.stringify(data));
  return true;
}
function join(type = "join") {
  send({ type, ...preferences() });
}
function message(text, kind = "") {
  $("messages").querySelector(".chat-empty")?.remove();
  const row = document.createElement("div");
  row.className = "bubble " + kind;
  row.textContent = text;
  $("messages").append(row);
  while ($("messages").children.length > 200)
    $("messages").firstElementChild.remove();
  $("messages").scrollTop = $("messages").scrollHeight;
}
function chatEnabled(enabled) {
  $("message").disabled = $("send-button").disabled = !enabled;
}
function report(event, extra = {}) {
  if (lastMatch) send({ type: "stats", match_id: lastMatch, event, ...extra });
}
function closePeer() {
  configRequest?.abort();
  configRequest = null;
  clearTimeout(connectTimer);
  clearTimeout(restartTimer);
  clearTimeout(disconnectTimer);
  peer?.close();
  peer = null;
  matchId = null;
  resumeToken = null;
  everConnected = restarting = false;
  restartAttempts = 0;
  candidates = [];
  $("remoteVideo").srcObject = null;
  $("remote-empty").hidden = false;
  $("peer-label").textContent = "새로운 친구";
  chatEnabled(false);
}
function failCall(title) {
  if (!everConnected) report("failed");
  closePeer();
  status(title, "다음 상대를 눌러 다시 시도해 주세요.");
}
function showConnected() {
  $("remote-empty").hidden = true;
  status("대화가 연결됐어요");
  chatEnabled(true);
}
async function usesRelay(pc) {
  const stats = await pc.getStats();
  let pair;
  stats.forEach((s) => {
    if (s.type === "transport" && s.selectedCandidatePairId)
      pair = stats.get(s.selectedCandidatePairId);
  });
  if (!pair)
    stats.forEach((s) => {
      if (s.type === "candidate-pair" && (s.selected || s.nominated) && s.state === "succeeded")
        pair = s;
    });
  return [pair?.localCandidateId, pair?.remoteCandidateId].some(
    (id) => id && stats.get(id)?.candidateType === "relay",
  );
}
async function onConnected(pc) {
  if (peer !== pc) return;
  clearTimeout(connectTimer);
  clearTimeout(disconnectTimer);
  showConnected();
  if (restarting) finishRestart(pc, true);
  if (!everConnected) {
    everConnected = true;
    const setup = Math.round(performance.now() - matchedAt);
    report("connected", {
      setup_ms: Math.min(setup, 120000),
      relay: await usesRelay(pc).catch(() => false),
    });
  }
}
function requestRestart(pc) {
  if (peer !== pc || restarting) return;
  if (!everConnected) return failCall("영상 연결에 실패했어요");
  if (restartAttempts >= 2) return failCall("영상 연결을 복구하지 못했어요");
  beginRestart(pc);
  if (initiator) offerRestart(pc);
  else send({ type: "signal", match_id: matchId, signal: { restart: true } });
}
function beginRestart(pc) {
  restarting = true;
  restartAttempts++;
  restartStarted = performance.now();
  status("연결 복구 중", "영상 연결을 다시 맺고 있습니다.");
  clearTimeout(restartTimer);
  restartTimer = setTimeout(() => {
    if (peer === pc && restarting) finishRestart(pc, false);
  }, 12000);
}
async function offerRestart(pc) {
  await pc.setLocalDescription(await pc.createOffer({ iceRestart: true }));
  if (peer === pc)
    send({
      type: "signal",
      match_id: matchId,
      signal: { description: pc.localDescription.toJSON() },
    });
}
function finishRestart(pc, recovered) {
  clearTimeout(restartTimer);
  restarting = false;
  const restart_ms = Math.min(Math.round(performance.now() - restartStarted), 120000);
  if (initiator) report(recovered ? "recovered" : "restart_failed", { restart_ms });
  if (recovered) restartAttempts = 0;
  else requestRestart(pc); // one more attempt, then give up
}
// A restart over a path that never really broke fires no state change: check after negotiating.
function checkRecovered(pc) {
  if (restarting && pc.connectionState === "connected") onConnected(pc);
}
function mediaState() {
  return {
    audio: !!stream?.getAudioTracks()[0]?.enabled,
    video: !!stream?.getVideoTracks()[0]?.enabled,
  };
}
function syncMedia() {
  const state = mediaState();
  $("toggle-camera").textContent = state.video ? "카메라 끄기" : "카메라 켜기";
  $("toggle-mute").textContent = state.audio ? "마이크 끄기" : "마이크 켜기";
  $("toggle-camera").setAttribute("aria-pressed", String(!state.video));
  $("toggle-mute").setAttribute("aria-pressed", String(!state.audio));
  $("localVideo").style.visibility = state.video ? "visible" : "hidden";
  $("local-empty").hidden = state.video;
  if (matchId) send({ type: "media", match_id: matchId, ...state });
}
async function start() {
  if (active) return;
  active = true;
  const run = ++generation;
  $("start").disabled = true;
  $("stop").disabled = false;
  notice();
  status("카메라와 마이크 확인 중", "브라우저의 접근 권한을 허용해 주세요.");
  try {
    if (!navigator.mediaDevices?.getUserMedia)
      throw new Error("secure-context");
    const acquired = await navigator.mediaDevices.getUserMedia({
      video: {
        width: { ideal: 640 },
        height: { ideal: 480 },
        frameRate: { ideal: 24, max: 30 },
      },
      audio: { echoCancellation: true, noiseSuppression: true },
    });
    if (run !== generation || !active) {
      acquired.getTracks().forEach((t) => t.stop());
      return;
    }
    stream = acquired;
    stream.getTracks().forEach((t) =>
      t.addEventListener("ended", () => {
        if (active) {
          stop();
          notice(
            "카메라 또는 마이크 연결이 끊어졌습니다. 장치를 확인해 주세요.",
          );
        }
      }),
    );
    $("localVideo").srcObject = stream;
    $("toggle-camera").disabled = $("toggle-mute").disabled = false;
    $("start").hidden = true;
    $("next").hidden = false;
    syncMedia();
    connect(run);
  } catch (error) {
    if (run !== generation) return;
    stop();
    const errors = {
      NotAllowedError: "카메라와 마이크 권한을 허용한 후 다시 시작해 주세요.",
      NotFoundError:
        "카메라와 마이크를 찾을 수 없습니다. 장치 연결을 확인해 주세요.",
      NotReadableError:
        "다른 앱에서 장치를 사용 중일 수 있습니다. 장치를 확인해 주세요.",
      AbortError:
        "장치를 시작하지 못했습니다. 다른 앱이 카메라를 사용 중인지 확인해 주세요.",
      OverconstrainedError:
        "지원되는 카메라 해상도를 찾지 못했습니다. 다른 카메라를 연결해 주세요.",
    };
    notice(
      !window.isSecureContext
        ? "카메라를 열 수 없습니다. HTTPS 또는 localhost에서 접속해 주세요."
        : errors[error.name] ||
            "카메라를 열 수 없습니다. 장치 연결과 브라우저 권한을 확인해 주세요.",
    );
  }
}
function connect(run) {
  if (!active || run !== generation) return;
  if (!resumeToken) status("서버 연결 중");
  $("next").disabled = true;
  const ws = new WebSocket(
    (location.protocol === "https:" ? "wss://" : "ws://") +
      location.host +
      "/ws/chat/",
  );
  socket = ws;
  chain = Promise.resolve();
  const openTimer = setTimeout(() => {
    if (ws.readyState !== WebSocket.OPEN) ws.close();
  }, 10000);
  ws.onopen = () => {
    clearTimeout(openTimer);
    lastPong = Date.now();
    heartbeat = setInterval(() => {
      if (Date.now() - lastPong > 40000) ws.close();
      else send({ type: "ping" });
    }, 15000);
  };
  ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    chain = chain
      .then(async () => {
        if (socket !== ws || run !== generation) return;
        await handle(data);
      })
      .catch((error) => {
        if (
          socket === ws &&
          active &&
          (!data.match_id || data.match_id === matchId)
        ) {
          closePeer();
          status(
            "연결을 완료하지 못했어요",
            "다음 상대를 눌러 다시 연결해 주세요.",
          );
          notice(
            error.message.startsWith("같은 네트워크")
              ? error.message
              : "미디어 연결에 실패했습니다. 네트워크를 확인해 주세요.",
          );
        }
      });
  };
  ws.onclose = (event) => {
    clearTimeout(openTimer);
    if (socket !== ws) return;
    clearInterval(heartbeat);
    // Mid-call, keep the media connection: the server holds the call for the next socket.
    const keepCall = active && matchId && resumeToken && event.code !== 4029;
    if (!keepCall) closePeer();
    if (!active) return;
    if (event.code === 4029) {
      stop();
      notice(
        "같은 네트워크에서 연결이 너무 많습니다. 다른 탭을 닫고 잠시 후 다시 시도해 주세요.",
      );
      return;
    }
    $("next").disabled = true;
    if (++reconnects > 3) {
      stop();
      notice("서버에 연결할 수 없습니다. 잠시 후 다시 시작해 주세요.");
      return;
    }
    if (keepCall) {
      chatEnabled(false);
      status("연결 복구 중", "대화를 유지한 채 서버에 다시 연결하고 있습니다.");
    } else status("연결이 끊어졌어요", "서버에 다시 연결하고 있습니다.");
    reconnectTimer = setTimeout(
      () => connect(run),
      keepCall ? 500 * reconnects : 1000 * 2 ** (reconnects - 1),
    );
  };
  ws.onerror = () => notice("서버 연결을 확인하고 있습니다.");
}
async function handle(data) {
  if (data.type === "ready") {
    nextAllowed = Date.now() + 1200;
    if (matchId && resumeToken) send({ type: "resume", token: resumeToken });
    else join();
  } else if (data.type === "pong") {
    lastPong = Date.now();
    reconnects = 0;
  } else if (data.type === "waiting") {
    closePeer();
    enableNext();
    status("대화 상대를 찾고 있어요", "상대가 준비되면 자동으로 연결됩니다.");
  } else if (data.type === "resumed" && data.match_id === matchId) {
    resumeToken = data.resume_token;
    reconnects = 0;
    notice();
    enableNext();
    if (peer?.connectionState === "connected") showConnected();
    else if (peer) requestRestart(peer);
  } else if (data.type === "resume_failed") {
    closePeer();
    message("연결이 끊긴 사이 대화가 종료됐어요.", "system");
    join();
  } else if (data.type === "peer_reconnecting" && data.match_id === matchId) {
    chatEnabled(false);
    status(
      "상대방 연결이 잠시 끊겼어요",
      `${data.grace}초 동안 다시 연결되기를 기다립니다.`,
    );
  } else if (data.type === "peer_resumed" && data.match_id === matchId) {
    if (peer?.connectionState === "connected") showConnected();
    else if (peer) requestRestart(peer);
  } else if (data.type === "matched") {
    closePeer();
    notice();
    matchId = lastMatch = data.match_id;
    resumeToken = data.resume_token;
    initiator = data.initiator;
    matchedAt = performance.now();
    $("report").disabled = false;
    enableNext();
    status("새로운 연결을 준비 중", "영상과 음성을 연결하고 있습니다.");
    sharedLabel = (data.common || []).map(interestLabel).join(" · ");
    if (sharedLabel) {
      $("peer-label").textContent = "새로운 친구 · " + sharedLabel;
      message("공통 관심사: " + sharedLabel, "system");
    }
    const id = matchId;
    const controller = new AbortController();
    configRequest = controller;
    const configTimeout = setTimeout(() => controller.abort(), 5000);
    let config;
    try {
      const response = await fetch(configUrl, {
        cache: "no-store",
        signal: controller.signal,
      });
      if (response.status === 429)
        throw new Error("같은 네트워크에서 연결 요청이 많습니다. 잠시 후 다음 상대를 눌러 주세요.");
      if (!response.ok) throw new Error("RTC configuration unavailable");
      config = await response.json();
    } finally {
      clearTimeout(configTimeout);
      if (configRequest === controller) configRequest = null;
    }
    if (!active || matchId !== id || controller.signal.aborted) return;
    const pc = new RTCPeerConnection(config);
    peer = pc;
    const signal = (value) => {
      if (peer === pc) send({ type: "signal", match_id: id, signal: value });
    };
    stream.getTracks().forEach((track) => pc.addTrack(track, stream));
    pc.onicecandidate = (event) => {
      if (event.candidate) signal({ candidate: event.candidate.toJSON() });
    };
    pc.ontrack = (event) => {
      if (peer !== pc) return;
      $("remoteVideo").srcObject = event.streams[0];
      $("remoteVideo")
        .play()
        .catch((error) => {
          if (error.name === "NotAllowedError")
            notice("상대방 음성을 재생하려면 화면을 한 번 눌러 주세요.");
        });
    };
    pc.onconnectionstatechange = () => {
      if (peer !== pc) return;
      if (pc.connectionState === "connected") onConnected(pc);
      else if (pc.connectionState === "failed") requestRestart(pc);
      else if (pc.connectionState === "disconnected") {
        status("연결 복구 중", "네트워크 연결을 확인하고 있습니다.");
        // "disconnected" often heals by itself; restart only if it lingers.
        clearTimeout(disconnectTimer);
        disconnectTimer = setTimeout(() => {
          if (peer === pc && pc.connectionState === "disconnected")
            requestRestart(pc);
        }, 3000);
      }
    };
    connectTimer = setTimeout(() => {
      if (peer === pc && !everConnected) failCall("연결 시간이 초과됐어요");
    }, 25000);
    syncMedia();
    if (initiator) {
      await pc.setLocalDescription(await pc.createOffer());
      signal({ description: pc.localDescription.toJSON() });
    }
  } else if (data.type === "peer_left" && data.match_id === matchId) {
    closePeer();
    status(
      "상대방이 대화를 종료했어요",
      "다음 상대를 눌러 새로운 대화를 시작하세요.",
    );
    message("상대방이 나갔습니다.", "system");
  } else if (data.type === "signal" && data.match_id === matchId && peer) {
    const pc = peer;
    if (data.signal.restart) {
      if (initiator && !restarting) {
        beginRestart(pc);
        await offerRestart(pc);
      }
    } else if (data.signal.description) {
      await pc.setRemoteDescription(data.signal.description);
      for (const candidate of candidates) await pc.addIceCandidate(candidate);
      candidates = [];
      if (data.signal.description.type === "offer") {
        await pc.setLocalDescription(await pc.createAnswer());
        if (peer === pc)
          send({
            type: "signal",
            match_id: matchId,
            signal: { description: pc.localDescription.toJSON() },
          });
      }
      checkRecovered(pc);
    } else if (data.signal.candidate) {
      if (pc.remoteDescription) await pc.addIceCandidate(data.signal.candidate);
      else candidates.push(data.signal.candidate);
    }
  } else if (data.type === "chat" && data.match_id === matchId) {
    message(data.username + ": " + data.message);
  } else if (data.type === "media" && data.match_id === matchId) {
    $("peer-label").textContent =
      "상대방" +
      (sharedLabel ? " · " + sharedLabel : "") +
      (data.audio ? "" : " · 음소거") +
      (data.video ? "" : " · 카메라 꺼짐");
  } else if (data.type === "reported") {
    status(
      "신고가 접수됐어요",
      "이 상대와는 다시 연결되지 않아요. 다음 상대를 눌러 계속하세요.",
    );
    message("신고가 접수되었습니다.", "system");
  } else if (data.type === "banned") {
    stop();
    notice(
      `신고가 누적되어 이용이 일시 제한되었습니다. 약 ${Math.ceil(data.retry_after / 60)}분 후 다시 시도해 주세요.`,
    );
  } else if (data.type === "error") notice(data.message);
}
function stop() {
  active = false;
  generation++;
  send({ type: "leave" });
  clearInterval(heartbeat);
  clearTimeout(reconnectTimer);
  clearTimeout(nextTimer);
  if (socket) {
    socket.onclose = null;
    socket.close();
    socket = null;
  }
  closePeer();
  lastMatch = null;
  $("report").disabled = true;
  if ($("report-dialog").open) $("report-dialog").close();
  stream?.getTracks().forEach((track) => track.stop());
  stream = null;
  $("localVideo").srcObject = null;
  $("local-empty").hidden = false;
  $("start").hidden = false;
  $("start").disabled = false;
  $("next").hidden = true;
  $("stop").disabled =
    $("toggle-camera").disabled =
    $("toggle-mute").disabled =
      true;
  reconnects = 0;
  status(
    "새로운 대화를 시작해 보세요",
    "대화 시작을 누르면 상대를 찾아드립니다.",
  );
}
$("start").addEventListener("click", start);
$("stop").addEventListener("click", stop);
$("next").addEventListener("click", () => {
  if (Date.now() < nextAllowed) {
    notice("잠시 후 다시 눌러 주세요.");
    return;
  }
  if (socket?.readyState !== WebSocket.OPEN) return;
  nextAllowed = Date.now() + 1200;
  enableNext();
  closePeer();
  notice();
  status("대화 상대를 찾고 있어요");
  join("next");
});
$("preferences").addEventListener("change", (event) => {
  const checked = document.querySelectorAll('input[name="interests"]:checked');
  if (checked.length > 3) {
    event.target.checked = false;
    notice("관심사는 3개까지 고를 수 있어요.");
  }
  try {
    localStorage.setItem(PREFS_KEY, JSON.stringify(preferences()));
  } catch {}
});
$("preferences").addEventListener("submit", (event) => event.preventDefault());
$("report").addEventListener("click", () => {
  if (!lastMatch) return;
  $("report-form").reset();
  $("report-dialog").returnValue = "";
  $("report-dialog").showModal();
});
$("report-cancel").addEventListener("click", () => $("report-dialog").close());
$("report-dialog").addEventListener("close", () => {
  const reason = new FormData($("report-form")).get("reason");
  if ($("report-dialog").returnValue !== "submit" || !reason || !lastMatch)
    return;
  if (send({ type: "report", match_id: lastMatch, reason })) {
    lastMatch = null;
    $("report").disabled = true;
    closePeer();
    status("신고를 접수하고 있어요");
  }
});
for (const [id, kind] of [
  ["toggle-camera", "video"],
  ["toggle-mute", "audio"],
]) {
  $(id).addEventListener("click", () => {
    const track = stream?.getTracks().find((t) => t.kind === kind);
    if (track) {
      track.enabled = !track.enabled;
      syncMedia();
    }
  });
}
$("message-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const text = $("message").value.trim();
  if (
    text &&
    matchId &&
    !$("send-button").disabled &&
    send({ type: "chat", match_id: matchId, message: text })
  ) {
    message("나: " + text, "mine");
    $("message").value = "";
  }
});
document.addEventListener("click", () => {
  if ($("remoteVideo").srcObject)
    $("remoteVideo")
      .play()
      .catch(() => {});
});
window.addEventListener("pagehide", stop);
restorePreferences();
