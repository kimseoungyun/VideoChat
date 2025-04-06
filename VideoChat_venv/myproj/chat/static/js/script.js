const localVideo = document.getElementById('localVideo');
const messagesContainer = document.getElementById('messages');
const messageInput = document.getElementById('message');
const sendButton = document.getElementById('send-button');
const toggleCameraButton = document.getElementById('toggle-camera');  // 카메라 토글 버튼
const toggleMuteButton = document.getElementById('toggle-mute'); // 음소거 토글 버튼
const placeholder = document.getElementById('placeholder');  // 대체 이미지 요소
const remoteVideo = document.getElementById('remoteVideo');
const loadingScreen = document.getElementById('loadingScreen');
const imageContainer = document.getElementById('imageContainer');
const remotePlaceholder = document.getElementById('remote-placeholder'); // 상대방 대체 이미지 요소
const toggleRedirectButton = document.getElementById('redirect-button'); // 방 이동 또는 생성 기능

const signalingSocket = new WebSocket('ws://' + window.location.host + '/ws/chat/' + roomName + '/');

let localStream;
let peerConnection;
const configuration = {
    iceServers: [
        { urls: 'stun:stun.l.google.com:19302' },
        { urls: 'stun:stun1.l.google.com:19302' },
        { urls: 'stun:stun2.l.google.com:19302' }
    ]
};

signalingSocket.onopen = () => {
    console.log('WebSocket is open now.');
};

signalingSocket.onclose = () => {
    console.log('WebSocket is closed now.');
    remoteVideo.srcObject = null; // 비디오 소스를 비웁니다.

};

signalingSocket.onerror = (error) => {
    console.error('WebSocket error observed:', error);
};

signalingSocket.onmessage = (event) => {
    const data = JSON.parse(event.data);
    console.log('Received message', event.data); // 수신 메시지 로그
    // 방이 가득 찼을 경우 리디렉션
    if (data.sdp) {
        // console.log('Received SDP:', data.sdp); // SDP 수신 로그
        handleSDP(data.sdp);
    } else if (data.candidate) {
        // console.log('Received ICE candidate:', data.candidate); // ICE 후보 로그
        handleCandidate(data.candidate);
    } else if (data.message) {
        displayMessage(`${data.username}: ${data.message}`);
    } else if (data.videoEnabled !== undefined) {
        // 상대방의 비디오 상태 업데이트
        updateRemoteVideo(data.videoEnabled);
    } else if (data.audioEnabled !== undefined) {
        // 상대방의 오디오 상태 업데이트
        updateRemoteAudio(data.audioEnabled);
    } else if (data.join) {
        displayMessage(data.join);
        sendUser(data.join);
    } else if (data.out) {
        displayMessage(data.out);
        // sendUser(data.out);
    } else if (data.usermessage){
        displayMessage(data.usermessage);
    }
};

window.onload = function() {
    startLocalVideo();
};

function startLocalVideo() {
    navigator.mediaDevices.getUserMedia({ video: true, audio: false }) 
        .then((stream) => {
            localVideo.srcObject = stream;  // 로컬 비디오에 스트림 연결
            localStream = stream;
            createPeerConnection();          // 피어 연결 생성
        })
        .catch(error => {
            console.error("Error accessing media devices.", error);
            alert("카메라 또는 마이크 접근을 허용해 주세요."); // 사용자에게 경고
        });
}

// 카메라 토글 기능
toggleCameraButton.addEventListener('click', () => {
    const videoTrack = localStream.getVideoTracks()[0]; // 비디오 트랙 가져오기
    if (videoTrack) {
        videoTrack.stop(); // 트랙을 중지하여 카메라 사용 중지
        localStream.removeTrack(videoTrack); // 스트림에서 비디오 트랙 제거
        signalingSocket.send(JSON.stringify({ videoEnabled: false })); // 상대방에게 비디오 상태 전송

        toggleCameraButton.textContent = '카메라 켜기'; // 버튼 텍스트 변경
        localVideo.style.display = 'none';  // 비디오 숨기기
        placeholder.style.display = 'block'; // 대체 이미지 보이기
    } else {
        startLocalVideo(); // 새로운 비디오 스트림 시작
        signalingSocket.send(JSON.stringify({ videoEnabled: true })); // 상대방에게 비디오 상태 전송

        toggleCameraButton.textContent = '카메라 끄기'; // 버튼 텍스트 변경
        localVideo.style.display = 'block';  // 비디오 보이기
        placeholder.style.display = 'none';  // 대체 이미지 숨기기
    }
});

// 음소거 토글 기능
toggleMuteButton.addEventListener('click', () => {
    const audioTrack = localStream.getAudioTracks()[0]; // 오디오 트랙 가져오기
    if (audioTrack) {
        audioTrack.enabled = !audioTrack.enabled; // 오디오 트랙의 활성화 상태 토글
        signalingSocket.send(JSON.stringify({ audioEnabled: audioTrack.enabled })); // 상대방에게 오디오 상태 전송

        toggleMuteButton.textContent = audioTrack.enabled ? '음소거' : '음소거 해제'; // 버튼 텍스트 변경
    }
});

// 새로운 방으로 리디렉션 또는 방 생성
toggleRedirectButton.addEventListener('click', function() {
    const currentRoomNumber = roomName;  // 현재 방 번호
    window.location.href = `/chat/redirect_room/${currentRoomNumber}/`; // 서버의 redirect_room 함수로 이동
});



// 상대방 비디오 상태 업데이트
function updateRemoteVideo(videoEnabled) {
    if (videoEnabled) {
        remoteVideo.style.display = 'block'; // 원격 비디오 보이기
        remotePlaceholder.style.display = 'none'; // 대체 이미지 숨기기
    } else {
        remoteVideo.style.display = 'none'; // 원격 비디오 숨기기
        remotePlaceholder.style.display = 'block'; // 대체 이미지 보이기
    }
}

// 상대방 오디오 상태 업데이트
function updateRemoteAudio(audioEnabled) {
    // 오디오 상태에 따라 추가적인 로직을 구현할 수 있습니다.
}

// 1. 첫 번째 function  => createPeerConnection() 함수
function createPeerConnection() {
    peerConnection = new RTCPeerConnection(configuration);

    // 로컬 스트림의 모든 트랙을 피어 연결에 추가
    localStream.getTracks().forEach(track => {
        peerConnection.addTrack(track, localStream);
    });

    // Offer 생성 및 전송
    peerConnection.createOffer()
        .then(offer => {
            // console.log('Creating offer:', offer); // Offer 생성 로그
            return peerConnection.setLocalDescription(offer);
        })
        .then(() => {
            if (signalingSocket.readyState === WebSocket.OPEN) {
                // console.log('Sending SDP:', peerConnection.localDescription); 
                signalingSocket.send(JSON.stringify({ sdp: peerConnection.localDescription })); // SDP 전송 로그, 이제 ICE 후보 생성 가능
            }
        })
        .catch(error => {
            console.error("Error creating an offer:", error);
        });
    

    // ICE 후보 수신 처리
    peerConnection.onicecandidate = (event) => {
        if (event.candidate) {
            // console.log('Adding ICE candidate:', event.candidate);
            if (signalingSocket.readyState === WebSocket.OPEN) {
                signalingSocket.send(JSON.stringify({ candidate: event.candidate })); // ice candidate 전송
            }
        } else {
            // console.log('All ICE candidates have been sent.');
        }
    };

    // 원격 트랙 수신 처리
    peerConnection.ontrack = (event) => {
        // console.log('Received remote track:', event.streams[0]); // 원격 트랙 로그
        if (event.streams[0]) {
            remoteVideo.srcObject = event.streams[0];  // 원격 비디오에 스트림 연결
            // console.log('complete remote track');
        } else {
            console.error('No streams found in the event');
        }
    };

    // ICE 연결 상태 변경 모니터링
    peerConnection.oniceconnectionstatechange = (event) => {
        // console.log('ICE connection state changed to:', peerConnection.iceConnectionState);
        if (peerConnection.iceConnectionState === 'connected') {
            loadingScreen.style.display = 'none';  // 로딩 화면 숨기기
            imageContainer.style.display = 'none';
            remoteVideo.style.display = 'block';  // remoteVideo 보이기
            console.log('Peers are connected!');
        } else if (peerConnection.iceConnectionState === 'disconnected') {
            remoteVideo.style.display = 'none';  // remoteVideo 숨기기
            imageContainer.style.display = 'flex';
            loadingScreen.style.display = 'flex';  // 로딩 화면 보이기
            console.log('Peers are disconnected.');
        } else if (peerConnection.iceConnectionState === 'failed') {
            console.error('ICE connection failed.');
        } else if(peerConnection.iceConnectionState === "checking") {
            console.log("It is checking right now");
        }
    };
}

//================================================================================================================================================
// 2. 두 번재 function => handleSDP() 함수
function handleSDP(sdp) {
    // console.log('Setting remote SDP'); // SDP 설정 로그
    peerConnection.setRemoteDescription(new RTCSessionDescription(sdp))  // 이 부분을 거치고 peerConnection.localDescription = null이 된다.
        .then(() => {
            // console.log('Remote description set successfully');
            if (sdp.type === 'offer') {
                return peerConnection.createAnswer(); // Offer인 경우에만 Answer 생성
            }
        })
        .then(answer => {
            // console.log('Creating answer:', answer);
            return peerConnection.setLocalDescription(answer); // 로컬 설명 설정
        })
        .then(() => {
            // 생성된 Answer를 상대방에게 전송
            if (signalingSocket.readyState === WebSocket.OPEN) {
                signalingSocket.send(JSON.stringify({ sdp: peerConnection.localDescription }));
                // console.log('Sending SDP Answer:', peerConnection.localDescription);
            }
        })
        .catch(error => {
            console.error("Error setting remote description:", error);
        });
}

//================================================================================================================================================
// 3. 세 번째 function => handleCandidate() 함수

function handleCandidate(candidate) {
    // console.log('process ICE candidate'); // 추가된 로그
    peerConnection.addIceCandidate(new RTCIceCandidate(candidate))
        .then(() => {
            // console.log('ICE candidate added successfully');
            // console.log('ICE connection state:', peerConnection.iceConnectionState);
        })
        .catch(error => {
            console.error("Error adding received ice candidate:", error);
        });
}

//================================================================================================================================================

sendButton.addEventListener('click', sendMessage);

messageInput.addEventListener('keypress', (event) => {
    if (event.key === 'Enter') {
        sendMessage();
    }
});

function sendMessage() {
    const message = messageInput.value;
    if (message) {
        if (signalingSocket.readyState === WebSocket.OPEN) {
            signalingSocket.send(JSON.stringify({ message: message }));
            messageInput.value = '';  // 입력 필드 초기화
            displayMessage(`나: ${message}`);  // 자신의 메시지 표시
        } else {
            console.warn('WebSocket not open, cannot send message. Current state:', signalingSocket.readyState);
        }
    }
}

function sendUser(usermessage) {
    if (usermessage) {
        if (signalingSocket.readyState === WebSocket.OPEN) {
            signalingSocket.send(JSON.stringify({ usermessage: usermessage }));
        } else {
            console.warn('WebSocket not open, cannot send usermessage. Current state:', signalingSocket.readyState);
        }
    }
}   

function displayMessage(message) {
    const messageElement = document.createElement('div');


    // 현재 시간 가져오기
    const now = new Date();
    const timeString = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

    // 시간과 메시지를 결합
    messageElement.textContent = `[${timeString}] ${message}`;
    messagesContainer.appendChild(messageElement);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;  // 스크롤을 아래로 이동
}
