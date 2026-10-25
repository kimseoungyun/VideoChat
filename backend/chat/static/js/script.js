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
function closePeer() {
  configRequest?.abort();
  configRequest = null;
  clearTimeout(connectTimer);
  peer?.close();
  peer = null;
  matchId = null;
  candidates = [];
  $("remoteVideo").srcObject = null;
  $("remote-empty").hidden = false;
  $("peer-label").textContent = "새로운 친구";
  chatEnabled(false);
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
    };
    notice(
      errors[error.name] ||
        "카메라를 열 수 없습니다. HTTPS 또는 localhost에서 접속해 주세요.",
    );
  }
}
function connect(run) {
  if (!active || run !== generation) return;
  status("서버 연결 중");
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
      .catch(() => {
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
          notice("미디어 연결에 실패했습니다. 네트워크를 확인해 주세요.");
        }
      });
  };
  ws.onclose = (event) => {
    clearTimeout(openTimer);
    if (socket !== ws) return;
    clearInterval(heartbeat);
    closePeer();
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
    status("연결이 끊어졌어요", "서버에 다시 연결하고 있습니다.");
    reconnectTimer = setTimeout(
      () => connect(run),
      1000 * 2 ** (reconnects - 1),
    );
  };
  ws.onerror = () => notice("서버 연결을 확인하고 있습니다.");
}
async function handle(data) {
  if (data.type === "ready") {
    nextAllowed = Date.now() + 1200;
    send({ type: "join" });
  } else if (data.type === "pong") {
    lastPong = Date.now();
    reconnects = 0;
  } else if (data.type === "waiting") {
    closePeer();
    enableNext();
    status("대화 상대를 찾고 있어요", "상대가 준비되면 자동으로 연결됩니다.");
  } else if (data.type === "matched") {
    closePeer();
    notice();
    matchId = lastMatch = data.match_id;
    $("report").disabled = false;
    enableNext();
    status("새로운 연결을 준비 중", "영상과 음성을 연결하고 있습니다.");
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
      if (pc.connectionState === "connected") {
        clearTimeout(connectTimer);
        $("remote-empty").hidden = true;
        status("대화가 연결됐어요");
        chatEnabled(true);
      } else if (pc.connectionState === "failed") {
        closePeer();
        status(
          "영상 연결에 실패했어요",
          "다음 상대를 눌러 다시 시도해 주세요.",
        );
      } else if (pc.connectionState === "disconnected") {
        status("연결 복구 중", "네트워크 연결을 확인하고 있습니다.");
      }
    };
    connectTimer = setTimeout(() => {
      if (peer === pc && pc.connectionState !== "connected") {
        closePeer();
        status(
          "연결 시간이 초과됐어요",
          "다음 상대를 눌러 다시 시도해 주세요.",
        );
      }
    }, 25000);
    syncMedia();
    if (data.initiator) {
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
    if (data.signal.description) {
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
    } else if (data.signal.candidate) {
      if (pc.remoteDescription) await pc.addIceCandidate(data.signal.candidate);
      else candidates.push(data.signal.candidate);
    }
  } else if (data.type === "chat" && data.match_id === matchId) {
    message(data.username + ": " + data.message);
  } else if (data.type === "media" && data.match_id === matchId) {
    $("peer-label").textContent =
      "상대방" +
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
  send({ type: "next" });
});
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
