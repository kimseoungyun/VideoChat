# 화상채팅 웹 서비스 프로젝트

## 프로젝트 소개
- WebRTC를 활용한 화상채팅 웹 서비스를 django를 활용해서 만든 프로젝트입니다.

## 프로젝트 기간
- 2025.03 ~ 2025.03

## 사용한 기법
- Django
- WebRTC
- Redis

## 사용법
- Redis 압축파일을 해제한 다음, 그 안에 Redis-server를 실행합니다.
- django 프로젝트를 열어서 가상환경에 진입합니다.(.\Scrips\activate.bat)
- pip install -r requiremenets 를 실행하여 필요한 라이브러리를 다운받습니다.
- django 프로젝트 폴더로 진입하여, python manage.py runserver를 실행합니다.
- 127.0.0.1에 접근하여, 프로그램을 실행합니다.
- python manage.py init을 실행할 경우, 데이터베이스에 남아있는 Room number에 대한 데이터를 초기화합니다.

## 기능
- 첫 사용자가 화상채팅을 시작할 경우, 랜덤으로 1~100 사이의 방 번호를 부여 받습니다.
- 그 다음 사용자부터는 1명인 방이 있을 경우, 그 방들 중 랜덤으로 방으로 입장하게 됩니다.
- 만약, 1명이 방이 없는 경우(모두 2명인 방 or 첫 사용자), 현재 존재하는 방 번호를 제외한 1~100 사이의 방 번호를 부여 받습니다.
- 넘기기 기능을 할 경우, 현재 방을 제외한, 1명인 방으로 랜덤으로 입장하게 됩니다.
- 숨기기,음소거 기능을 통해, video와 audio를 숨길 수 있습니다.
- 채팅 탭을 삭제하여 채팅방을 나갈 수 있습니다.
- 채팅 탭을 삭제하기 전에, 서버가 종료되면, Room number에 대한 데이터가 데이터베이스에 남아있어서 python manage.py init을 통해 초기화가 필요합니다.

## 배운 점
- WebRTC라는 기술 공부할 수 있는 기회여서 좋았습니다.
- django framework에 대해 점점 많이 알아가고 익숙해지는 기회여서 좋았습니다.
- 로그인 및 회원가입을 만드는 것은 아직 버거워서 별도의 프로젝트로 연습해볼 예정입니다.

ps : 현재 제 노트북 사운드카드가 고장나서, chat앱의 static/js/scripts.js파일에서 localvideochat을 얻기 위해서 getusermedia 명령어를 할 때, 'audio : false'로 설정되어 있습니다. 이를 true로 하셔야지 audio 데이터도 넘겨 받으실 수 있습니다.
