# 라즈베리파이 5 게이트웨이 배포 (초안)

> **상태: 초안 — M2 준비 단계.** 지금은 ingest(`INFERENCE_MODE=mock`) + cloud-sync(`SYNC_MODE=dry_run`)만 Pi에 올린다.
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

`.local`이 안 되면 공유기 관리 페이지에서 Pi IP를 찾아 `ssh <사용자>@<PI_IP>`로 접속한다.

## 2. 첫 부팅 설정

```bash
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y git curl
sudo reboot
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

## 3. Docker 설치

```bash
curl -fsSL https://get.docker.com -o get-docker.sh
sh get-docker.sh                       # 내용 확인 후 실행: less get-docker.sh
sudo usermod -aG docker $USER
exit                                   # 재접속해야 그룹이 적용된다
```

```bash
docker run --rm hello-world
docker compose version                 # v2 플러그인 확인
sudo systemctl is-enabled docker       # enabled → 재부팅 시 컨테이너 자동 시작
```

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
time docker compose up -d --build      # 첫 빌드 시간은 아래 측정 기록에 남긴다
docker compose ps                      # ingest, cloud-sync 모두 (healthy)
docker compose logs -f                 # Ctrl+C로 빠져나와도 컨테이너는 계속 돈다
```

## 6. 노트북에서 전송 테스트

```powershell
# 노트북 (PowerShell, 레포 루트, ppe-ingest 환경)
conda run -n ppe-ingest python gateway/scripts/fake_esp32.py --url http://<PI_IP>:8000 --token <DEVICE_TOKEN> --count 10 --wait
curl.exe http://<PI_IP>:8000/api/v1/stats
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

보내는 동안 Pi에서 `docker stats`로 CPU·메모리를 본다.

### 측정 기록

측정할 때마다 한 줄씩 추가하고, 같은 내용을 PR/이슈 코멘트로 공유한다.

| 날짜 | 커밋 | 구성 | 첫 빌드 시간 | 유휴 메모리 (ingest / cloud-sync) | 50장 전송 중 최대 메모리·CPU | 온도·스로틀 | 비고 |
|---|---|---|---|---|---|---|---|
| | | ingest mock + cloud-sync dry_run | | | | | |

## 8. 재부팅 자동 시작 확인

```bash
sudo reboot
# 재접속 후
cd ~/ppe-edge-guard/gateway
docker compose ps                      # 손대지 않아도 (healthy)
timedatectl | grep synchronized        # yes
```

`restart: unless-stopped`이므로 `docker compose down`으로 직접 내린 경우가 아니면 부팅 시 자동으로 올라온다.

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
| 노트북에서 `http://<PI_IP>:8000` 연결 안 됨 | 같은 네트워크인지, Pi에서 `curl localhost:8000/healthz`는 되는지, 공용 Wi-Fi의 기기 간 통신 차단(AP isolation) 여부 |
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
