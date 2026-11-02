# 라즈베리파이 5 게이트웨이 배포 (초안)

> **상태: 초안 — M2 준비 단계. 1차 실측 완료 (2026-11-02, [측정 기록](#측정-기록)).** 지금은 ingest(`INFERENCE_MODE=mock`) + cloud-sync(`SYNC_MODE=dry_run`)만 Pi에 올린다.
> inference(I1), 실제 Supabase 업로드(S1), 실제 ESP32(F1)가 붙을 때마다 이 문서를 갱신하고, M4에서 완성한다.
> 담당: 김세광 (Pi는 김세광만 가지고 있다).

명령은 모두 **Pi의 SSH 셸(bash)** 기준이다. 노트북(PowerShell)에서 실행하는 명령은 따로 표시한다.

## 0. 준비물

| 항목 | 권장 | 이유 |
|---|---|---|
| 보드 | Raspberry Pi 5 4GB | 팀 보유 장비 |
| 전원 | 공식 27W USB-C (5V 5A) | 부족하면 스로틀·USB 전력 제한 |
| 냉각 | Active Cooler | inference 연속 실행 시 발열 스로틀 방지 |
| 저장장치 | microSD 32GB 이상 (A2 등급), 가능하면 NVMe SSD | 이미지 빌드·사진·SQLite 쓰기 |
| OS | Raspberry Pi OS **Lite (64-bit)** 최신 | arm64 필수. 데스크톱 불필요 (메모리 절약) |
| 네트워크 | ESP32와 **같은 Wi-Fi/LAN** | ESP32가 Pi IP로 직접 POST |

## 1. OS 설치 (노트북에서 Raspberry Pi Imager)

1. Raspberry Pi Imager → 장치 `Raspberry Pi 5` → OS `Raspberry Pi OS Lite (64-bit)`.
2. 설정(톱니바퀴)에서 미리 지정한다.
   - 호스트 이름: `ppe-gateway`
   - 사용자 이름·비밀번호 (팀 공유 드라이브의 비공개 메모에만 기록. git 금지)
   - Wi-Fi SSID·비밀번호, 국가 `KR`
   - 시간대 `Asia/Seoul` (표시용일 뿐이다. 게이트웨이 데이터는 모두 UTC)
   - **SSH 사용** (비밀번호 또는 공개키)
3. 굽고 부팅한 뒤 노트북에서 접속한다.

```powershell
# 노트북 (PowerShell)
ssh <사용자>@ppe-gateway.local
```

**`.local` 이름이 안 되면** 노트북에서 `arp -a`로 같은 네트워크의 IP 목록을 보고 Pi의 IP를 찾아 `ssh <사용자>@<PI_IP>`로 접속한다. Pi를 켜기 전후의 `arp -a` 결과를 비교하면 새로 생긴 항목이 Pi다. IP를 찾은 뒤 아래 `HostName`에 `.local` 대신 IP를 넣으면 된다.

- 공유기·통신사 DNS에 따라 `ppe-gateway.local`이 **엉뚱한 인터넷 주소로 바뀌는** 경우가 있다(SK 공유기에서 `218.38.x.x`로 바뀌어 접속 시간 초과). `Resolve-DnsName ppe-gateway.local` 결과가 같은 네트워크 주소(예: `192.168.x.x`)가 아니면 IP로 접속한다.
- Pi MAC 주소를 알면(`ip link show wlan0`) `arp -a`에서 바로 찾을 수 있다. 목록에 없으면 같은 대역에 한 번 접속을 시도해 ARP 표를 채운 뒤 다시 본다.
- `HostName`을 IP로 바꿀 때 `HostKeyAlias ppe-gateway.local`을 같이 넣으면, IP가 바뀌어도 이미 등록한 Pi 호스트 키를 그대로 쓴다.

### 노트북 SSH 키 등록 (처음 한 번)

Imager에서 공개키를 넣었더라도 **지금 쓰는 노트북·Windows 계정에 그 개인 키가 없으면** `Permission denied (publickey,password)`가 난다. 이 노트북용 키를 만들어 등록한다. 마지막 명령에서 Pi 비밀번호를 한 번 묻는다.

```powershell
# 노트북 (PowerShell). passphrase는 Enter (비워 두면 자동화 스크립트에서 쓸 수 있다)
ssh-keygen -t ed25519 -f $HOME\.ssh\id_ed25519 -C "<이름>-laptop"
type $HOME\.ssh\id_ed25519.pub | ssh <사용자>@ppe-gateway.local "mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"
Add-Content $HOME\.ssh\config "Host ppe-gateway`n    HostName ppe-gateway.local`n    User <사용자>`n"
ssh ppe-gateway "whoami"              # 비밀번호 없이 사용자 이름이 나오면 끝
```

- `Host key verification failed`: `known_hosts`에 그 이름(`ppe-gateway` vs `ppe-gateway.local`)이 아직 없다. 대화형 터미널에서 한 번 접속해 지문을 확인하고 `yes`로 등록한다. OS를 다시 구웠다면 `ssh-keygen -R ppe-gateway.local`로 옛 키를 지운 뒤 등록한다.
- 노트북 PowerShell 5.1에서 `ssh ppe-gateway "..."`로 원격 명령을 보낼 때 **안쪽 큰따옴표가 지워진다.** 긴 명령은 스크립트 파일을 `scp`로 보낸 뒤 `ssh ppe-gateway 'bash ~/x.sh'`처럼 실행한다.

## 2. 첫 부팅 설정

```bash
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y git curl
[ -f /var/run/reboot-required ] && sudo reboot   # 커널 등 재부팅이 필요한 업데이트가 있을 때만
```

**sudo 비밀번호** — Imager로 만든 사용자는 sudo마다 비밀번호를 물을 수 있다(2026-11 Trixie 이미지에서 확인). 노트북에서 스크립트로 원격 설치하려면 이 사용자만 비밀번호 없이 sudo를 쓰게 한다. 게이트웨이 전용 장비이고 SSH는 키로 접속하므로 허용한다. 되돌리려면 이 파일만 지운다.

```bash
echo "$USER ALL=(ALL) NOPASSWD:ALL" | sudo tee /etc/sudoers.d/010-$USER-nopasswd > /dev/null
sudo chmod 440 /etc/sudoers.d/010-$USER-nopasswd && sudo visudo -c    # "parsed OK"
```

**시각 동기화 확인** — 게이트웨이의 `received_at`은 Pi 시계를 쓰고, ESP32 시각이 이상한지도 이 시계 기준으로 판단한다.

```bash
timedatectl          # "System clock synchronized: yes" 여야 한다
```

`no`면 네트워크 연결과 `systemctl status systemd-timesyncd`를 확인한다.

**IP 고정** — ESP32는 mDNS(`ppe-gateway.local`)를 쓰지 않고 IP로 접속한다. 공유기에서 Pi MAC 주소에 **DHCP 예약(고정 할당)**을 걸어 IP가 바뀌지 않게 한다. 학교·공용 Wi-Fi처럼 예약이 불가능하면 시연용 공유기를 따로 쓴다.

```bash
hostname -I          # 이 IP를 기록 → ESP32 펌웨어 GATEWAY_HOST, fake_esp32 --url
```

### Wi-Fi 추가·변경 (SSH로 원격 작업할 때)

**ESP32(XIAO ESP32S3)는 2.4GHz만 지원한다.** Pi도 같은 공유기의 2.4GHz 네트워크에 붙이면 연결 문제를 따질 일이 줄어든다.

`sudo nmcli --ask device wifi connect '<SSID>'`는 **비밀번호를 묻기 전에 지금 연결을 먼저 끊는다.** 그 연결로 SSH를 쓰고 있으면 SSH가 끊기면서 비밀번호를 입력할 수 없고, `no-secrets`로 실패한 뒤 원래 Wi-Fi로 돌아간다. 그래서 **비밀번호를 먼저 저장하고 연결을 시작한다.**

```bash
ssh ppe-gateway                                  # 노트북에서 접속한 뒤 Pi 안에서 실행
sudo nmcli device wifi rescan; nmcli -t -f SSID,FREQ,SIGNAL device wifi list    # SSID와 2.4GHz(24xx MHz) 확인

# 프로필이 없으면 먼저 만든다 (연결은 아직 시작하지 않는다)
sudo nmcli connection add type wifi ifname wlan0 con-name '<SSID>' ssid '<SSID>' connection.autoconnect yes
# 비밀번호 저장(화면·기록에 남지 않음) → 연결 시작. 여기서 SSH가 끊기는 게 정상
read -rsp 'Wi-Fi password: ' P; echo; sudo nmcli connection modify '<SSID>' wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$P"; unset P; sudo nmcli connection up '<SSID>'
```

노트북도 같은 Wi-Fi로 옮긴 뒤 새 IP를 찾아(위 `arp -a` 방법) `~\.ssh\config`의 `HostName`을 바꾸고 다시 접속한다. 그다음 새 Wi-Fi를 기존 Wi-Fi보다 먼저 쓰게 한다. 기존 Wi-Fi(예: 핫스팟)는 남겨 두면 새 Wi-Fi가 없는 곳에서 자동으로 붙는다.

```bash
sudo nmcli connection modify '<SSID>' connection.autoconnect-priority 10
nmcli -t -f NAME,AUTOCONNECT,AUTOCONNECT-PRIORITY connection show
```

- 비밀번호가 틀리면 `connection up`이 실패하고 Pi는 원래 Wi-Fi에 남는다. SSH가 살아 있으면 같은 줄을 다시 실행한다.
- 노트북 Wi-Fi 목록에 새 네트워크가 안 보이면(`netsh wlan connect`가 "not available") Wi-Fi를 껐다 켜서 다시 검색시킨다. **노트북이 그 네트워크에 붙을 수 있는지 먼저 확인한 뒤** Pi를 옮긴다. 그렇지 않으면 Pi에 접속할 방법이 없어진다.
- 옮긴 뒤 IP가 바뀌지 않게 공유기에서 Pi MAC에 **DHCP 예약**을 건다. ESP32 펌웨어에 IP를 넣기 전에 해 둔다.

## 3. Docker 설치

```bash
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh                  # 내용 확인 후 실행: less get-docker.sh (약 1분)
sudo usermod -aG docker $USER
sudo systemctl enable --now docker     # 재부팅 시 Docker(→ 컨테이너) 자동 시작
exit                                   # 재접속해야 그룹이 적용된다
```

```bash
docker run --rm hello-world            # "Hello from Docker!" (arm64v8)
docker compose version
```

### memory cgroup 켜기 (필수, 재부팅 필요)

Raspberry Pi 커널은 기본으로 `cgroup_disable=memory`라서 **compose의 `mem_limit`이 무시되고 `docker stats` 메모리가 `0B / 0B`로 나온다.** 빌드 로그에 `Your kernel does not support memory limit capabilities ... Limitation discarded`가 찍히고, `docker info`에 `WARNING: No memory limit support`가 나온다. 컨테이너를 만들기 **전에** 켠다.

```bash
f=/boot/firmware/cmdline.txt
sudo cp -p $f $f.bak                                   # 백업
sudo sed -i '1 s/$/ cgroup_enable=memory cgroup_memory=1/' $f
cat $f; grep -c '' $f                                  # 한 줄이어야 한다 (1)
sudo reboot
```

```bash
grep -w memory /sys/fs/cgroup/cgroup.controllers && echo OK    # 재접속 후
```

- `cmdline.txt`는 **한 줄짜리 파일**이다. 줄바꿈이 생기면 부팅이 안 될 수 있다. 그때는 SD 카드를 PC에 꽂고 `bootfs` 드라이브의 `cmdline.txt.bak`을 `cmdline.txt`로 되돌린다.
- 이미 컨테이너를 만든 뒤에 켰다면 제한값이 0으로 저장돼 있으므로 `docker compose up -d --force-recreate`로 다시 만든다(볼륨·데이터 유지).

## 4. 레포와 `.env`

```bash
cd ~
git clone https://github.com/physical-ai-team/ppe-edge-guard.git
cd ppe-edge-guard/gateway
cp .env.example .env
chmod 600 .env
openssl rand -hex 16                   # 출력값을 DEVICE_TOKEN으로
nano .env
```

M2 준비 단계의 `.env` 값:

| 키 | 값 | 비고 |
|---|---|---|
| `DEVICE_TOKEN` | 위에서 만든 랜덤 값 | ESP32 `secrets.h`의 `DEVICE_TOKEN`과 같게. 노트북 테스트 때는 `--token`으로 전달 |
| `INFERENCE_MODE` | `mock` | I1 머지 후 `http` |
| `SYNC_MODE` | `dry_run` | S1 완료 후 `supabase` + URL·service_role 키 |
| 나머지 | 기본값 | |

`.env`는 git에 올리지 않는다. service_role 키는 이 파일에만 둔다.

## 5. 빌드와 실행

```bash
cd ~/ppe-edge-guard/gateway
time docker compose up -d --build      # 첫 빌드 약 3~4분. 시간은 아래 측정 기록에 남긴다
docker compose ps                      # ingest, cloud-sync 모두 (healthy)
docker compose logs -f                 # Ctrl+C로 빠져나와도 컨테이너는 계속 돈다
```

- 이미지 크기는 서비스당 약 0.7GB다(ingest 731MB, cloud-sync 697MB). 빌드 캐시도 약 1.3GB 쌓이므로 SD 여유 공간을 본다.
- 노트북에서 원격으로 빌드할 때는 SSH가 끊겨도 계속되도록 `setsid nohup ... > ~/build.log 2>&1 < /dev/null &`로 돌리고 로그를 본다.

## 6. 노트북에서 전송 테스트

```powershell
# 노트북 (PowerShell, 레포 루트, ppe-ingest 환경)
conda run -n ppe-ingest python gateway/scripts/fake_esp32.py --url http://<PI_IP>:8000 --token <DEVICE_TOKEN> --count 10 --wait
curl.exe http://<PI_IP>:8000/api/v1/stats
```

- 토큰을 화면·히스토리에 남기지 않으려면 `--token` 대신 환경변수로 넘긴다(`fake_esp32.py`는 `DEVICE_TOKEN` 환경변수를 읽는다).
  ```powershell
  $env:DEVICE_TOKEN = (ssh ppe-gateway 'grep ^DEVICE_TOKEN= ~/ppe-edge-guard/gateway/.env | cut -d= -f2').Trim()
  ```
- 전부 `202`이고, `--wait` 결과가 `compliant`/`pending_upload`로 바뀌면 성공.
- `stats`의 `by_status`에서 `pending_upload`가 남지 않고 `uploaded`로 넘어가야 한다(dry_run).
- Pi에서 dry_run 결과 확인: `docker compose exec cloud-sync find /data/sync-dryrun -type f | head`

연결이 안 되면 → [문제 해결](#문제-해결).

## 7. 점검과 측정

```bash
cd ~/ppe-edge-guard/gateway
bash scripts/pi_check.sh               # 읽기 전용 점검 (시각, 메모리, 디스크, 컨테이너, API)
```

부하 측정 (노트북에서 50장을 0.5초 간격으로):

```powershell
conda run -n ppe-ingest python gateway/scripts/fake_esp32.py --url http://<PI_IP>:8000 --token <DEVICE_TOKEN> --count 50 --interval 0.5
```

보내는 동안 Pi에서 `docker stats`로 CPU·메모리를 본다. `docker stats --no-stream` 한 번에 약 2~3초가 걸리므로 1초 간격으로 돌려도 실제 샘플은 2~3초마다 하나다.

### 측정 기록

측정할 때마다 한 줄씩 추가하고, 같은 내용을 PR/이슈 코멘트로 공유한다. 메모리는 `docker stats` 값이다(제한 256MiB). CPU는 코어 1개 기준 %다.

| 날짜 | 커밋 | 구성 | 첫 빌드 시간 | 유휴 메모리 (ingest / cloud-sync) | 전송 테스트 | 50장 중 최대 메모리 / CPU (ingest · cloud-sync) | 온도·스로틀 | 비고 |
|---|---|---|---|---|---|---|---|---|
| 2026-11-02 | `2ae62a9` | ingest mock + cloud-sync dry_run. Pi OS Lite 64-bit (Debian 13 trixie, kernel 6.18.50), Docker 29.9.2, Compose v5.6.1, microSD(루트 57GB), Wi-Fi | **201초** (3분 21초, Docker 설치 약 1분 별도) | 58 / 46 MiB | 10장 `--wait`: 202 10/10, 14초. 50장 0.5초 간격: 202 50/50, 34초. dry_run 업로드 누락 0 | 53 / 46 MiB · 2.5% / 1.1% | 최고 53°C, `0x0` | memory cgroup을 켠 뒤 측정. 켜기 전에는 `docker stats`가 0B라 호스트 RSS로 잼(ingest 66, cloud-sync 60 MiB). 재부팅 후 수동 조작 없이 두 컨테이너 `healthy`, 데이터 유지 |

## 8. 재부팅 자동 시작 확인

```bash
sudo reboot
# 재접속 후
cd ~/ppe-edge-guard/gateway
docker compose ps                      # 손대지 않아도 (healthy)
timedatectl | grep synchronized        # yes
```

`restart: unless-stopped`이므로 `docker compose down`으로 직접 내린 경우가 아니면 부팅 시 자동으로 올라온다. 재부팅 명령 후 약 20초 만에 부팅됐고, 1~2분 뒤 재접속했을 때 두 컨테이너 모두 `healthy`였다.

- `/tmp`는 재부팅하면 비워진다. 측정용 스크립트 등은 홈 폴더에 둔다.

## 9. 업데이트 배포

```bash
cd ~/ppe-edge-guard
git pull --ff-only
cd gateway
docker compose up -d --build           # 바뀐 서비스만 다시 만든다
docker image prune -f                  # 이전 이미지 정리 (SD 용량)
```

- 데이터(사진 + `gateway.db`)는 named volume `ppe-edge-guard_gateway-data`에 남는다. **`docker compose down -v`는 위반 사진까지 지우므로 Pi에서는 쓰지 않는다.**
- 스키마가 바뀐 버전(예: v1.2의 `sync_permanent_failures`)도 시작할 때 자동으로 마이그레이션된다.

## 문제 해결

| 증상 | 확인 |
|---|---|
| `ppe-gateway.local`을 못 찾음, 또는 인터넷 주소로 바뀌어 시간 초과 | 노트북에서 `arp -a`로 Pi IP를 찾아 IP로 접속 ([1단계](#1-os-설치-노트북에서-raspberry-pi-imager)) |
| Wi-Fi 변경 중 SSH `Connection reset` 후 Pi가 원래 Wi-Fi로 돌아옴 | 비밀번호를 받기 전에 연결이 끊긴 것(`no-secrets`) → [Wi-Fi 추가·변경](#wi-fi-추가변경-ssh로-원격-작업할-때)처럼 비밀번호를 먼저 저장 |
| SSH `Permission denied (publickey,password)` | 이 노트북에 등록된 키가 없다 → [노트북 SSH 키 등록](#노트북-ssh-키-등록-처음-한-번) |
| SSH `Host key verification failed` | `known_hosts`에 그 호스트 이름이 없거나 OS를 다시 구움 → 대화형으로 한 번 접속해 등록, 필요하면 `ssh-keygen -R` |
| 노트북에서 `http://<PI_IP>:8000` 연결 안 됨 | 같은 네트워크인지, Pi에서 `curl localhost:8000/healthz`는 되는지, 공용 Wi-Fi의 기기 간 통신 차단(AP isolation) 여부 |
| `docker stats` 메모리가 `0B / 0B`, `mem_limit` 무시 | memory cgroup 꺼짐 → [3단계 cgroup 켜기](#memory-cgroup-켜기-필수-재부팅-필요) 후 `--force-recreate`. `pi_check.sh`가 경고로 알려 준다 |
| `401 invalid_token` | 노트북 `--token`과 Pi `.env`의 `DEVICE_TOKEN` 일치 여부. `.env` 수정 후 `docker compose up -d` 재실행 |
| `clock_synced=false`가 계속 나옴 | Pi `timedatectl` 동기화 여부. ESP32 NTP 문제일 수도 있다 (`X-Captured-At` 미전송) |
| 컨테이너가 `unhealthy`·재시작 반복 | `docker compose logs <서비스>`. cloud-sync는 `SYNC_MODE=supabase`인데 키가 비어 있으면 시작하지 않는다 |
| 빌드 중 멈춤·OOM | `free -h`로 스왑 확인. 다른 컨테이너를 내리고 서비스별로 `docker compose build <서비스>` |
| `vcgencmd get_throttled`가 `0x0`이 아님 | 전원 어댑터(27W)와 쿨러 확인 |

## 다음 단계에서 추가할 내용

- [ ] inference 컨테이너(I1): `models/` 배포(공유 드라이브 → `gateway/models/`), `INFERENCE_MODE=http`, 추론 속도·메모리, 스왑 크기 결정
- [ ] 실제 업로드(S1 이후): `SYNC_MODE=supabase`, 웹에서 실시간 표시 확인
- [ ] 실제 ESP32(F1 이후): `GATEWAY_HOST` 설정, 전송 시간, 쿨다운
- [ ] 카메라 거치 위치·각도, 시연장 네트워크 (M4)
