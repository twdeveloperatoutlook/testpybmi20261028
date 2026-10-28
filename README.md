# BMI 計算器

使用 Flask 製作的成人 BMI 網頁計算器。輸入姓名、身高（公分）和體重（公斤）後，頁面會顯示 BMI（小數點後一位）、體位分類、生活建議及歷史折線圖，並自動儲存每次計算。

## 啟動

需安裝 Python 3.9 以上版本。在專案資料夾執行：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

接著開啟 http://127.0.0.1:5000/ 。若 PowerShell 不允許啟用虛擬環境，也可以使用 `.\.venv\Scripts\python.exe -m pip install -r requirements.txt` 和 `.\.venv\Scripts\python.exe app.py`。

## 計算方式

BMI = 體重（公斤）÷ 身高（公尺）²。分類採臺灣成人體位參考標準：低於 18.5 為體重過輕、18.5 至未滿 24 為健康體位、24 至未滿 27 為體重過重、27 以上為肥胖。頁面以顯示至小數點後一位的 BMI 進行分類。

這只是成人體位參考，不能取代專業醫療評估，也不適用於兒童、青少年或孕婦。

BMI 達肥胖標準（顯示值大於或等於 27）時，計算結果、折線圖標註與歷史數據表中的 BMI 數字會以紅色顯示；未達標準則維持原色。

## BMI 半圓形儀表板

計算結果及歷史紀錄的結果頁會顯示半圓形 SVG 指針儀表板，不需 JavaScript 或外部圖表服務。指針依頁面顯示至小數點後一位的 BMI 定位，分類分界與文字結果一致；圖例同時列出分類名稱與數值範圍，不只以顏色區別。儀表板可隨畫面寬度縮放，並提供包含 BMI 數值與分類的螢幕閱讀器文字。

刻度顯示 0 至 40；超出範圍時指針停留於端點並顯示提示，實際 BMI 數值與分類不會被截斷或替換成刻度上限。重新計算會同步更新指針、數值與分類；無效輸入不顯示儀表板。紀錄儲存失敗時，仍顯示本次有效計算的儀表板及未儲存警告。

## JSON 紀錄與折線圖

按「計算並儲存 BMI」會將每次有效計算各自寫入 `data\<UUID>.json`，包含 `id`、`name`、`recorded_at`（含時區的 UTC ISO 8601 時間）、`height_cm`、`weight_kg`、`bmi`（數值）及 `category`。姓名必填，限 1 至 80 個字，前後空白會去除；檔名使用隨機 UUID 而非姓名。每筆檔案先完整寫入暫存檔再原子發布，並行計算不會覆蓋其他紀錄。

相同姓名／固定暱稱的紀錄會依時間排序，使用本機產生的 SVG 折線圖呈現，不依賴外部圖表服務或 JavaScript。圖上附 BMI 分類參考線與健康體位區，時間以 UTC+8 顯示；第一筆先顯示資料點，第二筆起連成折線。紀錄較多時可橫向捲動，也能展開完整數據表。按「只查詢此姓名的歷史紀錄」不需要輸入身高、體重，也不會新增紀錄。成功儲存後會重新導向結果頁，重新整理不會重複寫入。

點選首頁的「查看所有用戶的 BMI 紀錄」可開啟 `/users` 用戶名單，列出所有已儲存紀錄的姓名（同名僅列一次，依姓名排序）。點選姓名會顯示該用戶最新結果、歷史折線圖，以及預設展開的完整數據表，列出每筆 BMI 與計算時間（UTC+8，精確至秒）。瀏覽名單與紀錄不會新增資料；尚無紀錄時會顯示提示，讀取失敗時會顯示錯誤。

**隱私限制：目前沒有登入或身分驗證，同名者的紀錄會合併，所有訪客可透過用戶名單查看全部姓名及各姓名的歷史紀錄；持有結果頁連結者也可查看紀錄。僅適合本機／受信任環境，請使用不含敏感個資的固定暱稱。** JSON 是伺服器端明文檔案，不是公開靜態檔案；實際紀錄與暫存檔已排除於 Git，請自行限制資料夾存取權限並備份。

資料夾會在首次儲存時自動建立。設定環境變數 `BMI_DATA_DIR` 可指定持久化資料夾（例如 `$env:BMI_DATA_DIR = 'D:\BMIStorage\data'`）。資料夾必須可讀寫；檔案格式錯誤或讀寫失敗會顯示錯誤，不會宣稱儲存成功或覆寫損壞紀錄。若部署到 Azure，請將 `BMI_DATA_DIR` 指向部署目錄以外的持久化 `data` 資料夾，避免重新部署影響紀錄；多台實例需共用同一可寫入儲存位置才能看到完整歷史。

## 健康建議

計算成功後，結果區會依四種成人體位分類顯示飲食方向、健康追蹤及一般成人活動建議，並提供參考來源連結。建議依公開衛教資料整理為繁體中文摘要，固定存放於應用程式中；計算時不需要連線抓取資料，也不會將使用者的身高、體重傳送給來源網站。

參考資料（查閱日期：2026-10-12）：

- [國民健康署：成人 BMI 與健康體重](https://www.hpa.gov.tw/Pages/Detail.aspx?nodeid=542&pid=9737)：18 歲（含）以上成人體位分類與健康體重方向。
- [WHO：健康飲食](https://www.who.int/news-room/fact-sheets/detail/healthy-diet)：均衡、多樣化飲食，減少糖、鹽及不健康脂肪。
- [WHO：身體活動](https://www.who.int/news-room/fact-sheets/detail/physical-activity)：一般成人每週至少 150 分鐘中等強度活動、肌力活動及減少久坐。

以上為一般衛教資訊，不是個人化診斷或治療處方；有慢性病、身體不適或非預期體重下降時，應尋求醫療專業評估。

執行測試：`python -m unittest discover -s tests`

## 部署到 Azure Web App

`.github/workflows/deploy-azure.yml` 在 `main` 分支的應用程式、測試或 workflow 異動時執行，也可以從 GitHub Actions 手動觸發。流程會在 Windows runner 上執行測試、下載官方 Python 3.14.8 可嵌入版本，將 Python 與相依套件一起部署到 `NTUSTweb00`（資源群組 `NTUSTlab2026`）。站點透過 `web.config` 的 IIS HttpPlatformHandler 啟動 `serve.py`，以 Waitress 提供 Flask 服務。

此方法使用**隨部署包提供的 Python**，不依賴 Windows App Service 內建 Python 執行環境；HttpPlatformHandler 必須在目標站點可用。`NTUSTweb00` 目前是 Windows Web App，部署時會確認作業系統。

在 GitHub 儲存庫 **Settings → Secrets and variables → Actions** 確認：

- Repository secret `AZURE_CREDENTIALS`：Azure 服務主體的 `clientId`、`clientSecret`、`subscriptionId`、`tenantId` 組成的 JSON。此 Secret 已設定，不要把內容寫進程式碼。

請確認該服務主體對 `NTUSTweb00` 具有部署權限（例如該站點的 **Website Contributor**）。推送符合上述條件的 `main` 分支異動，或從 GitHub Actions 手動執行工作流程即可部署。

### dev 分支的 test slot

`.github/workflows/deploy-azure-test.yml` 在 `dev` 分支每次 push 時執行（不限制異動檔案），也支援手動觸發。它沿用正式環境的測試、Windows Python 打包與 Azure 登入流程，但只部署到同一個 Web App 的 `test` slot，不會交換 slot 或部署到正式環境；兩個工作流程使用不同的 concurrency group。

此工作流程沿用 repository variables `AZURE_WEBAPP_NAME` 與 `AZURE_RESOURCE_GROUP`，以及 secret `AZURE_CREDENTIALS`。請先在目標 Web App 建立名稱為 `test` 的 deployment slot（App Service 方案需支援 slot），並確認服務主體具有該 slot 的部署權限。部署前會檢查 `test` slot 存在且為 Windows 站點；不會自動建立 slot。

請在 `test` slot 設定獨立的持久化 `BMI_DATA_DIR`，並將它標記為 deployment slot setting，避免測試資料與正式資料混用。
