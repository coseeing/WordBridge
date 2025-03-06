# WordBridge User Guide

WordBridge is a tool specifically designed to correct Chinese homophone errors. It automatically detects and corrects homophonic character mistakes in your text, helping users significantly reduce the occurrence of typos.

Beyond just detecting and correcting errors, WordBridge offers detailed reports clearly displaying incorrect and corrected words along with explanations. This allows users to learn from mistakes and gradually master the correct usage and associated vocabulary, effectively enhancing language proficiency and input accuracy.

## How to Perform Text Checks

Select the text you wish to check, then press the shortcut key NVDA+Alt+O to initiate the checking process. You will hear beeping sounds during the check. Once completed, the corrected text will automatically be copied to the clipboard for your further use.

## How to View Correction Reports

Each time a text check and correction are completed, the system generates a web-based report clearly listing all corrected errors. Incorrect characters are displayed as clickable buttons; clicking them reveals detailed explanations about the incorrect and corrected characters, helping you better understand proper usage.

If you have enabled the "Automatically Show Correction Report" option, the report webpage will automatically open after each check. If this option is disabled, you can manually open the report anytime by pressing the shortcut key NVDA+Alt+U.

## Adjusting Settings

You can customize settings via the NVDA Menu → Preferences → Settings → WordBridge. The adjustable settings include:

* Service Provider: Choose the cloud computing resource provider.
* Large Language Model (LLM): Select an appropriate language model based on the chosen service provider.
* Correction Mode:
 * Standard Mode: Corrected words closely match the pronunciation of the original input, minimizing excessive corrections.
 * Lightweight Mode: Corrected words might differ from the original pronunciation, suitable for contexts with similar-sounding words.
* Chinese Simplified/Traditional: Select the language style (Traditional or Simplified Chinese) that the language model processes by default and automatically convert the input text accordingly.
* Custom Dictionary: Provide a custom vocabulary list to the language model to enhance accuracy for specialized terminology.

## Reporting Errors

If you encounter incorrect corrections when using the Coseeing service provider, please report them by pressing the shortcut key NVDA+Alt+F. Your feedback helps us continually optimize the algorithm to enhance correction accuracy.

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
