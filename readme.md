# WordBridge – User Guide

WordBridge is an AI-powered NVDA add-on that helps users identify and correct homophone-based typos in Chinese.

After each check, WordBridge generates a correction report showing the original text, suggested corrections, and explanations of related words and characters. Users can review their word choices and learn vocabulary as they proofread, building familiarity with correct usage and gradually improving their writing skills.

## Table of Contents

- [Running a Text Check](#running-a-text-check)
- [Viewing Reports](#viewing-reports)
- [Configuring Settings](#configuring-settings)
- [Coseeing Service](#coseeing-service)
- [Data Privacy](#data-privacy)

---

## Running a Text Check

To check text for typos, select the desired content and press `NVDA+Alt+O`. A sound effect will play during the check. Once complete, the corrected text will be automatically copied to the clipboard for further use.

---

## Viewing Reports

Each time a text check is performed, WordBridge generates a report listing all identified typos. Each typo appears as a clickable button. Click it to view explanations of the original and corrected words and characters. This helps users learn vocabulary and become more familiar with correct usage as they proofread, improving their writing skills.

If the **“Automatically Show Correction Report”** option is enabled, the report page opens automatically after each check. Otherwise, you can open it at any time with the **“Show Correction Report”** gesture.

---

## Configuring Settings

You can configure WordBridge via `NVDA Menu → Preferences → Settings → WordBridge`. The available settings include:

- **Service Provider**\
  Select the cloud service provider that handles text correction.

- **Large Language Model (LLM)**\
  Choose an appropriate language model based on the selected provider.

- **Correction Mode**\
  - *Standard Mode*: Produces corrections whose pronunciation stays close to the original text, suitable for users who want to avoid extending suggestions to weakly related homophones.\
  - *Lightweight Mode*: May produce corrections that differ more from the original pronunciation, suitable for input contexts where users want to explore broader homophone associations.

- **Simplified/Traditional Chinese**\
  Specify whether the text to be processed is in Simplified or Traditional Chinese. Input text is automatically converted to the selected form.

- **Personal Dictionary**\
  Provide a custom vocabulary list to improve correction accuracy for domain-specific or specialized terminology. You can open the dictionary editor from Settings to add terms. During a text check, WordBridge sends these terms to the LLM as reference material.

---

## Coseeing Service

Coseeing offers a rate-limited free allowance suitable for trying the features for a short time. If you need to use the service extensively, consider signing up with a supported service provider to obtain your own API key for faster and more reliable service.

---

## Data Privacy

When you run a text check, the selected text is sent to your configured **Service Provider** for processing. Please review your chosen provider's privacy policy before use.
