# WordBridge – User Guide

**WordBridge** is an NVDA addon that helps users identify and correct homophone-based typos in Chinese.

In addition to identifying and correcting homophone typos, WordBridge generates detailed reports that list the original typos, suggested corrections, and detailed descriptions of each character. This helps users learn from their mistakes and gradually master correct usage, effectively improving both language proficiency and typing accuracy.

---

## Running a Text Check

To check text for typos, select the desired content and press `NVDA+Alt+O`. A sound effect will play during the check. Once complete, the corrected text will be automatically copied to the clipboard for further use.

---

## Viewing Reports

Each time a check is performed, WordBridge generates a web-based report that clearly lists all identified typos. Each typo appears as a clickable button—clicking it reveals detailed descriptions of both the incorrect and corrected characters, helping users better understand proper usage.

If the **“Automatically Show Correction Report”** option is enabled, the report page will open automatically after each check. Otherwise, you can open it manually at any time by pressing `NVDA+Alt+R`.

---

## Configuring Settings

You can configure WordBridge via `NVDA Menu → Preferences → Settings → WordBridge`. The available settings include:

- **Service Provider**  
  Select the cloud computing provider that powers the correction service.

- **Large Language Model (LLM)**  
  Choose an appropriate language model based on the selected provider.

- **Correction Mode**  
  - *Standard Mode*: Produces corrections that closely match the original pronunciation, suitable for users who want to avoid overextending to loosely related homophones.  
  - *Lightweight Mode*: May produce corrections that differ more from the original pronunciation, suitable for input contexts where users want to explore broader homophone associations.

- **Simplified/Traditional Chinese**  
  Specify whether the language model should process Simplified or Traditional Chinese. Input text will be automatically converted to match the selected form.

- **Personal Dictionary**  
  Provide a custom vocabulary list to improve correction accuracy for domain-specific or specialized terminology.

---

## Keyboard Shortcuts

| Function                           | Shortcut Key     |
|------------------------------------|------------------|
| Execute typo correction            | `NVDA+Alt+O`     |
| Show correction report             | `NVDA+Alt+R`     |
| Open WordBridge settings           | `NVDA+Alt+W`     |
| Open personal dictionary editor    | `NVDA+Alt+D`     |
| Submit correction feedback         | `NVDA+Alt+F`     |

## Reporting Errors

If you notice incorrect corrections while using the **Coseeing** service provider, press `NVDA+Alt+F` to report them. Your feedback helps us continuously refine the correction algorithm and improve overall accuracy.

## test history

The following provides test results on accuracy and cost under various conditions for users' reference and selection.

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
