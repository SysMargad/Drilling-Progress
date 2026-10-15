# Drilling Progress

Python дата боловсруулалт + GitHub Pages dashboard. Drone Track / Mapping төслийн адил `main` руу push хийхэд `dist/` сайт GitHub Actions-аар нийтлэгдэнэ.

Repository: https://github.com/SysMargad/Drilling-Progress

GitHub Pages: https://sysmargad.github.io/Drilling-Progress/

## Python ажиллуулах

Python 3.10+ шаардлагатай. Local CSV/XLSX уншихад нэмэлт package хэрэггүй.

```powershell
py -3 drilling_sync.py
py -3 drilling_sync.py --watch 300 --serve
```

Local dashboard: http://127.0.0.1:4318. `start-dashboard.cmd` ашиглаж болно.

`input/` нь 2026.10.14-нд Drive-ээс уншсан эхний CSV хувилбаруудтай. Шинэ XLSX-ийг энэ хавтас дотор хийж болно; XLSX-д CSV-ээс давуу эрх өгнө. Seed CSV-ийг input-оос архивлаж гаргасны дараа зөвхөн шинэ XLSX уншина.

Local дата шинэчлээд GitHub руу автоматаар push хийх:

```powershell
py -3 drilling_sync.py --source local --publish
```

Зөвхөн `dist/data.json` болон `dist/data-log.json` commit хийнэ. `main` branch болон `SysMargad/Drilling-Progress` origin шаардлагатай. Бусад staged файлтай үед зогсоно. Force push хийхгүй; GitHub-ийн өөрчлөлттэй зөрвөл local дата, commit-ийг хадгалж алдааг мэдээлнэ. GitHub нэвтрэлт Git Credential Manager эсвэл таны SSH тохиргоогоор ажиллана.

## Google Drive автомат шинэчлэлт

Drive folder: https://drive.google.com/drive/folders/1b3n84juCY9UbrCMz7D6aITuV3lhgbvVI

GitHub Actions-ийн `Sync drilling data from Google Drive` workflow нь **өдөр бүр 08:00 Asia/Shanghai** цагийн хуваарьтай, мөн гараар ажиллуулж болно. Google credential байхгүй үед аюулгүй skip хийнэ; дата өөрчлөгдвөл commit/push болон Pages deploy-ийг нэг workflow дотор гүйцэтгэнэ.

Нэг удаагийн тохиргоо:

1. Google Drive API read-only service account-ийг эх хавтас унших эрхтэй болгоно.
2. Repository → Settings → Secrets and variables → Actions дотор `GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON` secret-д credential JSON-ийг хадгална.
3. Actions → Sync drilling data from Google Drive → Run workflow.

Credential болон token-ийг repository файлд хийхгүй. Өмнөх Mapping repository-ийн secret өөр repository-д автоматаар дамжихгүй.

Local Drive sync:

```powershell
py -3 -m pip install -r requirements.txt
$env:GOOGLE_APPLICATION_CREDENTIALS = 'C:\private\google-drive-credentials.json'
py -3 drilling_sync.py --source drive --watch 300 --publish
```

Local watch ажиллахад компьютер асаалттай, процесс ажиллаж байх шаардлагатай. Cloud workflow компьютер унтарсан үед ч credential тохируулсны дараа ажиллана. Site service token шаардлагагүй.

## Өгөгдлийн шалгалт

```powershell
py -3 -B -m unittest test_drilling_sync -v
py -3 -B validate_data.py
```

Давхардлыг өрөм + огноо + ээлж + цооногоор хасна. Хоосон гүн нь 0 биш, `null` байна. Ээлжийн гүн/метр, ажлын цаг зөрвөл нийтлэхгүй. Collar болон ээлжийн гүнийг хүснэгтэд тус тусад нь харуулна. Өгөгдөл өөрчлөгдөөгүй бол дата файлыг хэвээр үлдээж, бодит уншилтын түүхийг Data Log-д нэмнэ.

Веб нээлттэй үед 60 секунд тутам `data.json`-ийг дахин уншина. GitHub Pages нийтэд нээлттэй: сайт болон repository-д хадгалсан өгөгдлийг хэн ч үзэж болно. Drive эх файлуудын эрх өөрчлөгдөхгүй.

## Файлын бүтэц

- `drilling_sync.py`: Drive/local → дата → GitHub push; local Python сервер
- `dist/`: Pages HTML/CSS/JS болон data.json
- `input/`: эх CSV болон local XLSX
- `.github/workflows/pages.yml`: push → Pages deploy
- `.github/workflows/drive-sync.yml`: Drive → шалгалт → push → Pages deploy
- `test_drilling_sync.py`, `validate_data.py`: шалгалт
- `requirements.txt`: Drive authentication package

Official API references: [Google Drive download/export](https://developers.google.com/workspace/drive/api/guides/manage-downloads), [Google authentication](https://google-auth.readthedocs.io/en/latest/reference/google.oauth2.credentials.html).

## Харагдац ба Data Log

Талбай: **Нэргүй Өндөр**. Дөрвөн KPI карт нь ерөнхий тойм, цооногийн бүртгэл, ашиглалт болон ROP хэсгийг нээнэ.

Гүйцэтгэлийг Ээлж, Өдөр, 7 хоног, Сар-аар сонгоно. Норм өрөм тус бүрт 30 м/ээлж, 60 м/өдөр, 420 м/7 хоног; сарынх 60 м × календарийн хоног байна. Дутуу 7 хоног/сар бүтэн үеийн нормтой харьцуулагдана.

`dist/data-log.json` нь Python-оор өгөгдөл уншсан сүүлийн 500 бодит үйлдлийг хадгална: хугацаа, local/Drive эх үүсвэр, өөрчлөгдсөн/өөрчлөлтгүй/алдаатай төлөв, файлын тоо, цооног, ээлж, метр. Өмнөх бүртгэгдээгүй түүхийг зохиомлоор нөхөхгүй. Drive синк алдаатай үед өмнөх дата болон алдааны бүртгэл хадгалагдана.

Графикийн нийлбэр, норм, leap year болон жилийн заагийн шалгалт:

    node test_chart.cjs
## Цооногийн ахиц ба участик

Талбай нь Нэргүй Өндөр; участик нь Дорнын Төмөр эсвэл Замт Хөндий. Дээд хэсэгт талбай, участик, өрмөөр шүүнэ. Участик болон өрмийн шүүлтүүр KPI, гүйцэтгэл, цооног, ээлжийн бүртгэлд хамт үйлчилнэ.

Цооногийн ахиц зөвхөн Бүртгэлтэй цооног картыг дарахад нээгдэнэ. Цооногийн дугаар сонгоход тухайн мөрийн доор хугацаа–гүний график дэлгэгдэнэ. Гүн нь 0-оос доош хасах утгаар, өдөр/шөнийн ээлжийн дарааллаар дүрслэгдэнэ. Мэдээлэл тасарсан интервалуудыг холбож интерполяц хийхгүй. Ээлжийн мэдээлэлгүй цооногт зохиомол график зурахгүй.