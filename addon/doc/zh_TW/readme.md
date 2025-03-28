# WordBridge 使用說明

WordBridge 是一款專為校正中文同音錯別字所設計的工具，能夠自動檢測並更正輸入內容中出現的同音字錯誤，協助使用者降低錯別字發生的機率。

除了提供錯別字檢測與修正功能外，WordBridge 更透過詳盡的報告頁面，清楚呈現錯誤及其正確用字，搭配字詞解釋，幫助使用者從錯誤經驗中學習，逐步掌握字詞正確用法與相關聯的詞彙，有效提升語文能力及輸入的精確度。

## 如何進行文字檢查

請先選取欲檢查的文字，接著按下快速鍵 NVDA+Alt+O 即可開始文字檢查，檢查期間會有嗶嗶聲作為提示。完成檢查後，結果將自動複製到剪貼簿，供使用者進一步使用。

## 如何瀏覽錯字報告

每次執行完文字檢查與校正後，系統將產生一份報告網頁，清楚列出所有經修正的錯別字。報告中，原錯字將以按鈕形式呈現，點擊即可查看錯字與修正字的詳細解釋，有助於深入理解字詞的正確用法。

若您已在設定中勾選「自動顯示改錯字報告」，系統將於每次檢查完成後自動開啟報告頁面；若未勾選，則可透過快速鍵 NVDA+Alt+R 主動開啟報告頁面。

## 如何調整設定

您可以從 NVDA 功能表 → 偏好 → 設定 → WordBridge 進入設定頁面，可調整以下項目：

* 服務提供商：選擇提供大語言模型的服務商。
* 大語言模型：依據服務商提供的模型，選擇合適的大語言模型。
* 校正模式：
 * 標準模式：校正後的字詞將盡可能與原輸入的發音相同，避免過度修正。
 * 輕量模式：校正後的字詞可能與原輸入的發音不同，適用於發音相近的情境。
* 中文繁簡：設定大語言模型預設處理的語言，可選擇繁體中文或簡體中文，並自動進行文字轉換。
* 客製詞典：可提供自訂詞彙給大語言模型，強化特定領域詞彙的校正準確度。

## 如何回報錯誤

若您在使用由 Coseeing 服務商提供的檢查功能時發現誤判情形，歡迎按下快速鍵 NVDA+Alt+F 將錯誤回報給我們，以協助持續優化演算法，提升校正的準確性。

## 測試紀錄

以下提供各種情況下的精準度與成本的測試結果供使用者選用參考

### 2024/6/15

| Model | Accuracy | Input Token | Output Token | Input Price ($/1M token) | Output Price ($/1M token) | Character Count (without punctuation) | Price ($) / 1k Character |
| --- | --- | --- | --- | --- | --- | --- | --- |
| gpt-3.5-turbo | 94.40% | 46539 | 7189 | 0.5 | 1.5 | 3745 | 0.0091 |
| gpt-4-turbo | 95.60% | 45467 | 7110 | 10.0 | 30.0 | 3745 | 0.1784 |
| gpt-4o | 97.20% | 35628 | 4483 | 5.0 | 15.0 | 3745 | 0.0655 |
| gpt-4o Simple Mode | 93.20% | 19887 | 3900 | 5.0 | 15.0 | 3745 | 0.0422 |

### 2024/5/15

| Model | Accuracy | Input Token | Output Token | Input Price ($/1M token) | Output Price ($/1M token) | Character Count (without punctuation) | Price ($) / 1k Character |
| --- | --- | --- | --- | --- | --- | --- | --- |
| gpt-3.5-turbo | 90.40% | 69950 | 8228 | 0.5 | 1.5 | 3745 | 0.0126 |
| gpt-4-turbo | 92.80% | 65746 | 7961 | 10.0 | 30.0 | 3745 | 0.2393 |
| gpt-4o | 96.40% | 53803 | 5303 | 5.0 | 15.0 | 3745 | 0.0931 |
| gpt-4o Lite Mode | 90.00% | 29169 | 3553 | 5.0 | 15.0 | 3745 | 0.0532 |
